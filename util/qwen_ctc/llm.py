# coding: utf-8
"""
Qwen3-ASR 二遍解码器（LLM 头的纯文本识别）

流程：encoder 输出的音频 embedding ``[T, n_embd]`` → 注入 ChatML 提示
（prefix + 音频段 + suffix）→ llama.cpp 贪心生成 → 文本。

把「静默出错」的坑固化在实现里：

1. **M-RoPE 位置必须段优先（section-major）**：本模型 arch 是 ``qwen3vl``，
   llama.cpp 映射成 ``LLAMA_ROPE_TYPE_IMROPE``（``n_rope_type == 40``）。
   预填充 embedding 批时位置数组要按 ``pos[j*n + i]`` 排布（j=0..3），
   即 ``[arange(n), arange(n), arange(n), zeros(n)]``，共 4n 个 int32。
   位置容量也需要 4n，所以 ``decode_embd`` 内部按 4n 分配批次。
2. **生成阶段不要自己算位置**：单 token 走 ``decode_tokens``，位置由
   llama.cpp 从 KV 末尾自动续接。
3. **文本按字节拼接再整体解码**：一个汉字可能横跨多个 token，逐 token
   解码会得到乱码（``�``）。必须先 ``token_to_bytes`` 拼字节流，再
   UTF-8 一次性 decode。
4. **停止符必须显式解析**，不能拿 GGUF 的 eos 元数据当唯一依据（上游导出
   的 GGUF 里 eos 被错设成 id 11 逗号；本期文件恰好是对的也不依赖它）。
5. **上下文容量要自己兜底**：``n_prefill + n_predict > n_ctx`` 时把本次
   生成上限收紧为 ``n_ctx - n_prefill``，而不是让 llama.cpp 满载报错。

加载顺序约束（见 llama_cpp.py 顶部）：本模块只在 llama.cpp 之后使用，
**不 import torch / transformers**，否则会在 llama 初始化前拉起 torch。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional, Set

import numpy as np

from .gguf_embed import TokenEmbedding
from .llama_cpp import Context, Model

_MODULE_LOGGER = logging.getLogger(__name__)

#: 特殊 token 字面量 → 回退 id（tokenize 解析失败时使用，规格 §9.3）
SPECIAL_TOKENS = {
    "<|endoftext|>": 151643,
    "<|im_start|>": 151644,
    "<|im_end|>": 151645,
    "<|audio_start|>": 151669,
    "<|audio_end|>": 151670,
    "<|audio_pad|>": 151676,
    "<asr_text>": 151704,
}

#: system 提示（实测有效的最短形态）
SYSTEM_PROMPT = "You are a helpful assistant."

#: 本模型 arch（qwen3vl）在 llama.cpp 里的 rope 类型
IMROPE = 40

#: 上下文窗口下限（再小连提示都装不下，视为配置错误）
MIN_N_CTX = 512

#: 单次 decode 的最大 token 数（规格 §9.10：min(n_ctx, 2048)）
DEFAULT_N_BATCH = 2048

#: 微批大小（规格 §9.10）
DEFAULT_N_UBATCH = 512

#: 复读判定窗口与不同值阈值（规格 §9.7：最近 30 个 token 的不同值 ≤ 3）
REPEAT_WINDOW = 30
REPEAT_MIN_DISTINCT = 3

#: 复读熔断的最大重试次数（升温 0.3 / 0.6 / 0.9 / 1.2）
MAX_REPEAT_RETRIES = 4

#: 每次重试的温度增量
TEMP_STEP = 0.3


class QwenLLMDecoder:
    """
    Qwen3-ASR 的 LLM 二遍解码器

    Args:
        gguf_path: 解码器 GGUF 路径（含 ``token_embd.weight`` 与 qwen3vl 权重）
        n_ctx: 上下文窗口，**不能小于 512**（规格 §9.10）
        n_threads: llama 推理线程数（与 ONNX encoder 的 num_threads 独立）
        n_predict: 单段音频的最大生成 token 数
        verbose: 为 True 时把每次生成的耗时打到 INFO
        logger: 可注入的日志器（loguru / std logging 均可），默认用模块 logger

    Note:
        释放顺序必须是 ``Context`` → ``Model`` → ``TokenEmbedding``，
        :meth:`close` 已经封装好；顺序错会在 Windows 上留下模型文件锁。
    """

    def __init__(
        self,
        gguf_path: str | Path,
        n_ctx: int = 4096,
        n_threads: int = 6,
        n_predict: int = 256,
        verbose: bool = False,
        logger: Optional[object] = None,
    ):
        self.path = Path(gguf_path).expanduser()
        if not self.path.is_file():
            raise FileNotFoundError(f"解码器 GGUF 不存在: {self.path}")

        self._logger = logger if logger is not None else _MODULE_LOGGER
        self.verbose = bool(verbose)

        if int(n_ctx) < MIN_N_CTX:
            raise ValueError(
                f"n_ctx={n_ctx} 小于下限 {MIN_N_CTX}（提示 14 + T + 6，"
                f"再小连预填充都装不下）"
            )
        if int(n_predict) <= 0:
            raise ValueError(f"n_predict 必须为正，收到 {n_predict}")

        self._n_ctx = int(n_ctx)
        self._n_predict = int(n_predict)
        self._n_threads = max(1, int(n_threads))
        self._closed = False

        # 先置空，保证初始化中途抛异常时 close() 也是安全的（幂等 + 只关已建好的）
        self._ctx = None
        self._model = None
        self._embed = None
        self._prefix_embd = None
        self._suffix_embd = None

        # ── 1. llama.cpp 模型（必须先于任何 torch 相关 import） ──
        self._model = Model(self.path)
        self.n_embd = int(self._model.n_embd)
        self.n_vocab = int(self._model.n_vocab)
        self.rope_type = int(self._model.n_rope_type)
        if self.rope_type != IMROPE:
            self._log(
                "warning",
                f"解码器 rope_type={self.rope_type}，期望 IMROPE={IMROPE}；"
                "4 平面 M-RoPE 位置注入可能不匹配",
            )

        # ── 2. token embedding 按行读取器 ──
        self._embed = TokenEmbedding(self.path)

        # ── 3. 特殊 token 与提示形态 ──
        self._im_start = self._resolve_special("<|im_start|>")
        self._im_end = self._resolve_special("<|im_end|>")
        self._audio_start = self._resolve_special("<|audio_start|>")
        self._audio_end = self._resolve_special("<|audio_end|>")
        self._asr_text = self._resolve_special("<asr_text>")
        self._endoftext = self._resolve_special("<|endoftext|>")

        # 停止符：显式解析出来的两个，不依赖 GGUF 的 eos 元数据
        self.stop_ids: Set[int] = {self._im_end, self._endoftext}

        tok = self._tokenize_plain
        self.prefix_ids: List[int] = (
            [self._im_start]
            + tok("system\n" + SYSTEM_PROMPT)
            + [self._im_end]
            + [self._im_start]
            + tok("user\n")
            + [self._audio_start]
        )
        self.suffix_ids: List[int] = (
            [self._audio_end, self._im_end, self._im_start]
            + tok("assistant\n")
            + [self._asr_text]
        )

        # 提示两端的 embedding 只算一次（20 行，按需反量化，不碰整表）
        self._prefix_embd = self._embed.rows(self.prefix_ids)
        self._suffix_embd = self._embed.rows(self.suffix_ids)

        # ── 4. 推理上下文 ──
        self._n_batch = min(self._n_ctx, DEFAULT_N_BATCH)
        self._ctx = Context(
            self._model,
            self._n_ctx,
            n_batch=self._n_batch,
            n_ubatch=DEFAULT_N_UBATCH,
            n_threads=self._n_threads,
        )

        self._log(
            "info",
            f"Qwen LLM 解码器载入完成: {self.path.name} n_embd={self.n_embd} "
            f"n_vocab={self.n_vocab} rope={self.rope_type} n_ctx={self._n_ctx} "
            f"n_predict={self._n_predict} prompt={len(self.prefix_ids)}+T+"
            f"{len(self.suffix_ids)}",
        )

    # ── 生命周期 ──────────────────────────────────────────────────────

    def _ensure_alive(self) -> None:
        if self._closed:
            raise RuntimeError("QwenLLMDecoder 已关闭（close() 之后不能再使用）")

    def close(self) -> None:
        """释放 Context → Model → TokenEmbedding（顺序不可颠倒，且幂等）"""
        if getattr(self, "_closed", False):
            return
        self._closed = True

        ctx = getattr(self, "_ctx", None)
        model = getattr(self, "_model", None)
        embed = getattr(self, "_embed", None)
        self._ctx = self._model = self._embed = None
        self._prefix_embd = None
        self._suffix_embd = None

        for name, obj, release in (
            ("Context", ctx, "free"),
            ("Model", model, "free"),
            ("TokenEmbedding", embed, "close"),
        ):
            if obj is None:
                continue
            try:
                getattr(obj, release)()
            except Exception as exc:  # pragma: no cover - 退出路径
                logger_to_use = getattr(self, "_logger", _MODULE_LOGGER)
                try:
                    logger_to_use.debug(f"释放 {name} 失败（忽略）: {exc}")
                except Exception:
                    pass

    def __enter__(self) -> "QwenLLMDecoder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):  # pragma: no cover - 解释器退出路径
        try:
            self.close()
        except Exception:
            pass

    # ── 提示构造 ──────────────────────────────────────────────────────

    def _tokenize_plain(self, text: str) -> List[int]:
        """普通文本 → token id（不解析特殊 token，与实测序列一致）"""
        return self._model.tokenize(text, add_special=False, parse_special=False)

    def _resolve_special(self, literal: str) -> int:
        """
        把特殊 token 字面量解析成**单个** id

        解析结果长度不为 1（新版词表把字面量拆开了）时回退到已知 id 表，
        并留一条 WARNING —— 静默回退容易掩盖词表与预期不一致。
        """
        ids = self._model.tokenize(literal, add_special=False, parse_special=True)
        if len(ids) == 1:
            return int(ids[0])

        fallback = SPECIAL_TOKENS.get(literal)
        if fallback is None:
            raise ValueError(
                f"特殊 token {literal!r} 无法解析为单个 id（得到 {ids}），"
                "且没有已知回退值"
            )
        self._log(
            "warning",
            f"特殊 token {literal!r} 解析为 {len(ids)} 个 id {ids}，回退到 {fallback}",
        )
        return int(fallback)

    def _build_prompt(self, audio_embd: np.ndarray) -> np.ndarray:
        """prefix_embd + 音频段 + suffix_embd → ``[n, n_embd]`` float32"""
        audio = np.ascontiguousarray(audio_embd, dtype=np.float32)
        if audio.ndim != 2:
            raise ValueError(f"audio_embd 必须是二维 [T, n_embd]，实际 ndim={audio.ndim}")
        if audio.shape[0] <= 0:
            raise ValueError("audio_embd 不能为空（T=0）")
        if audio.shape[1] != self.n_embd:
            raise ValueError(
                f"audio_embd 的列数 {audio.shape[1]} != 模型 n_embd {self.n_embd}"
            )
        return np.concatenate(
            [self._prefix_embd, audio, self._suffix_embd], axis=0
        ).astype(np.float32, copy=False)

    # ── 容量计算 ──────────────────────────────────────────────────────

    def effective_n_predict(self, n_prefill: int) -> int:
        """
        本次生成可用的 token 上限

        ``min(n_predict, max(n_ctx - n_prefill, 0))``；被上下文收紧时留 WARNING，
        避免 llama.cpp 在满载时静默截断或报错。
        """
        n_prefill = int(n_prefill)
        available = max(self._n_ctx - n_prefill, 0)
        limit = min(self._n_predict, available)
        if limit < self._n_predict:
            self._log(
                "warning",
                f"提示 {n_prefill} token + 生成上限 {self._n_predict} 超过 "
                f"n_ctx={self._n_ctx}，本次生成上限收紧为 {limit}",
            )
        return int(limit)

    # ── 预填充 / 解码 ─────────────────────────────────────────────────

    def _prefill(self, full: np.ndarray) -> float:
        """
        一次调用完成整段 embedding 的预填充，返回耗时（毫秒）

        位置**显式**按 4 平面段优先传入（规格 §9.4）：M-RoPE 模型要读
        ``pos[j*n + i]``（j=0..3），依赖 ``decode_embd`` 的缺省布局太脆，
        这里自己算，换后端 / 改默认值都不会悄悄错位。

        整段必须**一次** decode 完成：``decode_embd`` 每次都会分配
        ``max(4n, 8192)`` 的批次（≈64MB），循环分块会把开销乘上去。
        """
        n = int(full.shape[0])
        if n > self._n_batch:
            raise ValueError(
                f"提示 {n} token 超过 n_batch={self._n_batch}"
                "（调大 n_ctx 或缩短音频）"
            )
        pos = np.arange(n, dtype=np.int32)
        pos4 = np.concatenate(
            [pos, pos, pos, np.zeros(n, dtype=np.int32)]
        ).astype(np.int32, copy=False)

        self._ctx.clear_kv()
        t0 = time.perf_counter()
        rc = self._ctx.decode_embd(full, pos4)
        ms = (time.perf_counter() - t0) * 1000.0
        if rc != 0:
            raise RuntimeError(f"embedding 预填充失败（llama_decode rc={rc}）")
        return ms

    def _pick(self, logits: np.ndarray, temperature: float) -> int:
        """按温度挑下一个 token：``temperature <= 0`` 走确定性 argmax"""
        if temperature <= 0.0:
            return int(np.argmax(logits))
        # 数值稳定：先减最大值再除温度，softmax 用 float64 累加
        scaled = (np.asarray(logits, dtype=np.float64) - float(np.max(logits))) / temperature
        probs = np.exp(scaled)
        probs /= probs.sum()
        return int(np.random.choice(probs.size, p=probs))

    def _is_repeating(self, tokens: List[int]) -> bool:
        """最近 REPEAT_WINDOW 个 token 的不同值 ≤ REPEAT_MIN_DISTINCT 视为复读"""
        if len(tokens) < REPEAT_WINDOW:
            return False
        tail = tokens[-REPEAT_WINDOW:]
        return len(set(tail)) <= REPEAT_MIN_DISTINCT

    def _decode_loop(
        self, limit: int, temperature: float = 0.0
    ) -> tuple[List[int], bool, float]:
        """
        预填充之后的自回归解码

        Returns:
            (生成的 token id（不含停止符）, 是否判定为复读, 耗时毫秒)
        """
        out: List[int] = []
        repeating = False
        t0 = time.perf_counter()
        for _ in range(limit):
            logits = self._ctx.logits_ith(-1)
            tid = self._pick(logits, temperature)
            if tid in self.stop_ids:
                break
            rc = self._ctx.decode_tokens([tid])
            if rc != 0:
                raise RuntimeError(f"单 token 解码失败（llama_decode rc={rc}）")
            out.append(tid)
            if self._is_repeating(out):
                repeating = True
                break
        return out, repeating, (time.perf_counter() - t0) * 1000.0

    # ── 对外生成 ──────────────────────────────────────────────────────

    def generate(self, audio_embd: np.ndarray) -> str:
        """
        音频 embedding → 文本

        Args:
            audio_embd: encoder 输出 ``[T, n_embd]``（``n_embd`` 必须与模型一致）

        Returns:
            生成的文本（不 strip；逐 token 字节拼接后整体 UTF-8 解码）

        Raises:
            ValueError: 形状 / 上下文容量不合法
            RuntimeError: llama 解码失败或已 close()
        """
        self._ensure_alive()

        full = self._build_prompt(audio_embd)
        n_prefill = int(full.shape[0])
        limit = self.effective_n_predict(n_prefill)
        if limit <= 0:
            raise ValueError(
                f"n_ctx={self._n_ctx} 装不下 {n_prefill} token 的提示，无法生成"
            )

        tokens, text = self._generate_with_breaker(full, limit)
        if self.verbose:
            self._log(
                "info",
                f"LLM 生成 {len(tokens)} token / 上限 {limit}: {text!r}",
            )
        return text

    def _generate_with_breaker(
        self, full: np.ndarray, limit: int
    ) -> tuple[List[int], str]:
        """贪心生成 + 复读熔断（清 KV、升温 +0.3 重试，最多 4 次）"""
        attempts = 0
        temperature = 0.0
        tokens: List[int] = []

        while True:
            prefill_ms = self._prefill(full)
            tokens, repeating, gen_ms = self._decode_loop(limit, temperature)

            self._log(
                "debug",
                f"prefill {int(full.shape[0])} token {prefill_ms:.1f} ms，"
                f"生成 {len(tokens)} token {gen_ms:.1f} ms"
                f"（{gen_ms / max(len(tokens), 1):.1f} ms/token，T={temperature:.1f}）",
            )
            if self.verbose:
                self._log(
                    "info",
                    f"prefill {prefill_ms:.0f} ms，生成 {len(tokens)} token "
                    f"{gen_ms:.0f} ms（T={temperature:.1f}）",
                )

            if not repeating or attempts >= MAX_REPEAT_RETRIES:
                break
            attempts += 1
            temperature = round(TEMP_STEP * attempts, 2)
            self._log(
                "warning",
                f"检测到复读（最近 {REPEAT_WINDOW} token 的不同值 ≤ "
                f"{REPEAT_MIN_DISTINCT}），清 KV 后升温至 {temperature:.1f} 重试 "
                f"{attempts}/{MAX_REPEAT_RETRIES}",
            )

        return tokens, self._decode_text(tokens)

    def _decode_text(self, tokens: List[int]) -> str:
        """token id 列表 → 文本（先拼字节再整体 UTF-8 解码，避免 CJK 被拆坏）"""
        if not tokens:
            return ""
        raw = b"".join(self._model.token_to_bytes(t) for t in tokens)
        return raw.decode("utf-8", errors="replace")

    def warmup(self) -> None:
        """
        预热：1 帧静音跑一次完整 prefill + 1 token 生成

        首次 prefill 有约 2 s 的一次性开销（llama 图 reserve），第二次起约 20 ms。
        预热故意只生成 1 个 token（不在静音上跑到 n_predict），异常只记日志不抛。
        """
        self._ensure_alive()
        try:
            t0 = time.perf_counter()
            full = self._build_prompt(np.zeros((1, self.n_embd), np.float32))
            prefill_ms = self._prefill(full)
            self._decode_loop(1, 0.0)
            self._ctx.clear_kv()
            total_ms = (time.perf_counter() - t0) * 1000.0
            self._log(
                "info",
                f"LLM 预热完成：prefill {prefill_ms:.0f} ms（总计 {total_ms:.0f} ms）",
            )
        except Exception as exc:
            self._log("warning", f"预热失败（不影响后续生成）: {exc}")

    # ── 日志 ──────────────────────────────────────────────────────────

    def _log(self, level: str, message: str) -> None:
        """按级别转发日志（std logging 与 loguru 的方法签名兼容）"""
        fn = getattr(self._logger, level, None)
        if fn is None:  # pragma: no cover - 注入的日志器缺级别
            fn = getattr(self._logger, "info", None)
        if fn is None:  # pragma: no cover - 连 info 都没有
            return
        try:
            fn(message)
        except Exception:  # pragma: no cover - 日志失败不影响推理
            pass
