# coding: utf-8
"""
Qwen3-ASR 推理引擎：纯 CTC / 两遍 / 纯 LLM 三模式编排

数据流（按模式）：

- ``ctc``      ：音频 → Whisper 特征 → Qwen3-ASR 编码器（ONNX）→ CTC 头（ONNX）
                 → 贪心折叠 → 字节级反解 → 文本 + 字级时间戳
- ``two_pass`` ：同一次编码器输出既喂 CTC 首遍（选字符 + 起始帧），又喂 LLM 二遍
                 （出完整文本含标点），两者用 NW 对齐合成「LLM 文本 + 字级时间戳」
- ``llm``      ：编码器输出直接喂 LLM 二遍，只有文本、没有时间戳

模式不是配置直接决定的：CTC 头可能不存在，也可能维度不匹配（0.6B 的编码器
输出 1024 维，没有任何 CTC 头）。所以 `initialize()` 先如实探测「CTC 头可用性」，
再交给 `resolve_mode()` 按规格 §7.2 的矩阵判定，并把结果固化到 `mode` /
`has_timestamps` 两个属性上。`enable_ctc` 只是**请求**而非门槛：请求了两遍但
CTC 头不可用时降级为纯 LLM 并打 WARNING，不是启动失败。

加载顺序（规格 §5.3，顺序本身是正确性的一部分）：

1. llama.cpp 运行时（DLL + backend）——必须在任何 torch/transformers 导入之前；
   **只在配了解码器时才加载**（纯 CTC 不需要 LLM，也就不需要 llama.cpp 的 DLL）；
2. 解码器 GGUF + LlamaContext（配了路径但文件不存在 = 硬错误，规格 §7.4(2)）；
3. ONNX 编码器（这一步才惰性 import transformers 的 WhisperFeatureExtractor）；
4. ONNX CTC 头（只有 `enable_ctc=True` 且路径非空时才加载）；
5. 维度校验 + 模式判定；
6. 解码器预热（把 ~2s 的首帧开销挪到启动阶段，失败向上抛、绝不吞掉）。

本模块保留规格里三个「静默出错」的坑的固化实现：

1. **帧率是 13 fps，不是 50**：有效输出帧数 = `full*13 + ceil(leave/8)`。
2. **特征不补到 30 秒**：`padding=False` 取真实长度，再零填到 3000 帧桶。
3. **反解走字节**：`tokens.txt` 存的是 base64 原始字节，一个中文字符可能横跨
   多个 token，必须先拼字节再整体 decode。

另外：**编码器是按 30 秒桶导出的**，超过 30 秒的音频必须按 30 秒切段，
否则 WhisperFeatureExtractor 会静默截断（特征提取器的 padding 行为）。
"""

import os

# 必须在任何 onnxruntime 导入之前设置：Windows 上 onnxruntime 与 llama.cpp
# 各带一份 OpenMP 运行时，重复载入会让进程直接 abort（不是抛异常）。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger as default_logger
from loguru._logger import Logger

from . import llama_cpp
from .align import align_ctc_to_llm
from .encoder import (
    FRAME_RATE_HZ,
    MEL_FRAMES,
    FusedEncoder,
    SplitEncoder,
    resolve_providers,
    valid_frames,
)
from .schema import RecognitionResult, RecognitionStream
from .tokens import decode_bytes, load_tokens

# Qwen3-ASR 编码器的帧率（13 fps）与 30 秒桶在 encoder.py 里定义，这里 re-export
FRAME_SEC = 1.0 / FRAME_RATE_HZ

SEGMENT_SEC = 30.0

SAMPLE_RATE = 16000

# CTC 尖峰式发射的系统性偏置（对 MFA 词级真值实测：起点晚 100ms、终点早 78.5ms）
DEFAULT_START_BIAS = 0.100
DEFAULT_END_BIAS = 0.0785

# 三种推理模式（resolve_mode 的返回值，也是 engine.mode 的取值域）
MODE_CTC = "ctc"
MODE_TWO_PASS = "two_pass"
MODE_LLM = "llm"
MODES = (MODE_CTC, MODE_TWO_PASS, MODE_LLM)


@dataclass
class QwenCTCConfig:
    """Qwen3-ASR 引擎配置（纯 CTC / 两遍 / 纯 LLM 共用）"""

    # 编码器：融合（1.7B）用 encoder_onnx_path；
    # 0.6B 拆分版用 encoder_frontend_path + encoder_backend_path（必须成对）
    encoder_onnx_path: str
    ctc_onnx_path: str
    tokens_path: str
    preprocessor_path: str
    blank_id: int = 72466
    unk_id: int = 72467
    mel_frames: int = MEL_FRAMES
    num_threads: int = 6
    provider: str = "cpu"  # "cpu" 或 "dml"
    start_bias: float = DEFAULT_START_BIAS
    end_bias: float = DEFAULT_END_BIAS
    verbose: bool = False
    # 解码器（GGUF）。空 = 纯 CTC 模式；非空 = 两遍（CTC 头可用）或纯 LLM
    decoder_gguf_path: str = ""
    # 0.6B 拆分编码器（两者都非空才启用；只配一端是硬错误）
    encoder_frontend_path: str = ""
    encoder_backend_path: str = ""
    # 是否请求 CTC 首遍（只有配了解码器时才有意义；CTC 头不可用会自动降级）
    enable_ctc: bool = True
    llm_n_ctx: int = 4096
    llm_n_threads: int = 6
    llm_n_predict: int = 256


def resolve_mode(
    split_encoder: bool,
    has_decoder: bool,
    enable_ctc: bool,
    ctc_usable: bool,
) -> str:
    """
    按规格 §7.2 的模式矩阵判定推理模式。

    **判定顺序本身是语义的一部分**，不能重排：

    1. 0.6B 拆分编码器没有 CTC 头，没配解码器就没有任何推理路径 —— 这个检查
       必须排在最前面，否则 ``(split=True, has_decoder=False, ctc_usable=False)``
       会被后面的「纯 CTC」分支误判成一个能跑的模式；
    2. 既没解码器又禁用 CTC，同样没有推理路径；
    3. 有解码器 + 请求两遍 + CTC 头可用 → ``two_pass``；
    4. 有解码器（其余情况）→ ``llm``；
    5. 没解码器但启用 CTC → ``ctc``。

    Args:
        split_encoder: 是否使用 0.6B 前后端拆分编码器
        has_decoder: 是否成功加载了 LLM 解码器
        enable_ctc: 配置里的 `enable_ctc`
        ctc_usable: CTC 头文件存在且输入维度与编码器输出维度一致

    Returns:
        ``"ctc"`` / ``"two_pass"`` / ``"llm"``

    Raises:
        ValueError: 组合下没有任何推理路径
    """
    if split_encoder:
        # 0.6B 编码器输出 1024 维，没有任何 CTC 头与之匹配：即便有文件、
        # 维度凑巧相等，也一律按不可用处理
        ctc_usable = False

    if split_encoder and not has_decoder:
        raise ValueError(
            "0.6B 编码器（前后端拆分）没有 CTC 头，必须配置解码器"
            "（decoder_gguf_path），否则无推理路径"
        )

    if not has_decoder and not enable_ctc:
        raise ValueError(
            "既未配置解码器（decoder_gguf_path 为空），又禁用了 CTC"
            "（enable_ctc=False），无推理路径"
        )

    if has_decoder and enable_ctc and ctc_usable:
        return MODE_TWO_PASS

    if has_decoder:
        return MODE_LLM

    if enable_ctc:
        return MODE_CTC

    # 理论上不可达（上面的分支已覆盖全部组合），留作防御
    raise ValueError(
        f"无法判定推理模式: split_encoder={split_encoder}, has_decoder={has_decoder}, "
        f"enable_ctc={enable_ctc}, ctc_usable={ctc_usable}"
    )


def _session_input_dim(session) -> Optional[int]:
    """ONNX 会话首个输入的最后一维；动态/未知维度返回 None"""
    try:
        return int(session.get_inputs()[0].shape[-1])
    except (IndexError, TypeError, ValueError):
        return None


class QwenCTCEngine:
    """
    Qwen3-ASR 推理引擎（纯 CTC / 两遍 / 纯 LLM）

    对外接口与 sherpa-onnx 兼容：
        engine.create_stream() -> stream
        stream.accept_waveform(sample_rate, audio)
        engine.decode_stream(stream)
        stream.result.text / .tokens / .timestamps

    模式相关属性（`initialize()` 之后才有意义）：
        engine.mode            ∈ {"ctc", "two_pass", "llm"}
        engine.has_timestamps  == mode in ("ctc", "two_pass")
    """

    FRAME_SEC = FRAME_SEC
    SAMPLE_RATE = SAMPLE_RATE

    def __init__(self, config: QwenCTCConfig, logger: Optional[Logger] = None):
        self.config = config
        self.logger = logger if logger is not None else default_logger
        self._enc = None
        self._ctc = None
        self._llm = None
        self._is_split = False
        self.mode: str = ""
        self.has_timestamps: bool = False
        self.id2bytes: Dict[int, bytes] = {}

    # ── 初始化 ────────────────────────────────────────────────────────
    def initialize(self) -> "QwenCTCEngine":
        """
        按规格 §5.3 的顺序装配引擎并判定模式。

        任何一步失败都会把已建好的资源关掉再原样抛出（不吞错）。
        """
        if self._enc is not None:
            return self

        try:
            self._initialize_impl()
        except BaseException:
            # 半初始化状态下不能把句柄留着：关掉再抛，错误照旧向上传播
            self.cleanup()
            raise
        return self

    def _initialize_impl(self) -> None:
        cfg = self.config

        # ①＋② llama.cpp 运行时 + 解码器（可选）
        #
        # 纯 CTC 模式完全不碰 llama.cpp / GGUF：规格 §10.2 里纯 CTC 只需要
        # encoder + CTC 头 + tokens + preprocessor，`bin/` 缺 DLL 不该拖死一个
        # 用不到 LLM 的部署。有解码器时 init_lib() 仍先于建 encoder（§5.3 的
        # 顺序约束不变：llama.cpp 运行时必须早于 transformers 的导入）。
        if cfg.decoder_gguf_path:
            if not Path(cfg.decoder_gguf_path).is_file():
                # 规格 §7.4(2)：配了路径但文件不存在是硬错误。静默降级会把
                # 「想要两遍」变成「无标点的纯 CTC」，而且用户只看到一条 WARNING
                raise ValueError(
                    f"解码器 GGUF 不存在: {cfg.decoder_gguf_path}；"
                    "要么下载该文件，要么把 model_paths.qwen_llm_path 留空"
                    "以使用纯 CTC"
                )

            # ① llama.cpp 运行时（DLL + backend_init）
            llama_cpp.init_lib()

            # 惰性导入：纯 CTC 模式完全不加载 llm.py 的依赖链
            from .llm import QwenLLMDecoder

            self._llm = QwenLLMDecoder(
                cfg.decoder_gguf_path,
                n_ctx=cfg.llm_n_ctx,
                n_threads=cfg.llm_n_threads,
                n_predict=cfg.llm_n_predict,
                verbose=cfg.verbose,
                logger=self.logger,
            )

        # ③ 编码器：这一步才真正 import transformers（encoder.py 内惰性导入），
        #    有解码器时必须排在 llama.cpp 运行时之后
        self._enc = self._build_encoder()

        # ④ CTC 头（可选）：只在「请求了 CTC 首遍」且文件存在时建会话，可用性
        #    留到 ⑤ 用维度判定。禁用 CTC 时白加载一个用不到的 ONNX，只会让
        #    「一个本该无关的 CTC 文件损坏」卡死启动。
        ctc_path = cfg.ctc_onnx_path or ""
        if cfg.enable_ctc and ctc_path and Path(ctc_path).is_file():
            import onnxruntime as ort

            providers = resolve_providers(ort, cfg.provider)
            so = ort.SessionOptions()
            so.intra_op_num_threads = cfg.num_threads or 0
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._ctc = ort.InferenceSession(
                ctc_path, sess_options=so, providers=providers
            )
        elif cfg.enable_ctc:
            # 规格 §7.3：CTC 头缺失必须让用户看见，不能静默
            if ctc_path:
                self.logger.warning(f"CTC 头不存在，已忽略: {ctc_path}")
            elif cfg.decoder_gguf_path:
                self.logger.warning("未配置 CTC 头，已降级为纯 LLM")
            else:
                # 纯 CTC 且没配 CTC 头：下面第 ⑥ 步会硬失败，这里先如实提示
                self.logger.warning("未配置 CTC 头（ctc_onnx_path 为空）")

        # ⑤ 维度校验 + CTC 头可用性
        enc_dim = self._enc.output_dim

        if self._llm is not None and self._llm.n_embd != enc_dim:
            raise ValueError(
                f"解码器维度 {self._llm.n_embd} ≠ 编码器输出维度 {enc_dim}："
                f"decoder_gguf_path（{Path(cfg.decoder_gguf_path).name}）与编码器配置不匹配"
            )

        ctc_dim = _session_input_dim(self._ctc) if self._ctc is not None else None
        if self._ctc is not None and self._is_split:
            # 0.6B 的 1024 维输出没有配套 CTC 头；文件维度恰好为 1024 也不可信
            self.logger.warning(
                "0.6B 拆分编码器没有配套的 CTC 头，CTC 首遍已禁用"
            )
            self._ctc = None
        elif self._ctc is not None and ctc_dim != enc_dim:
            self.logger.warning(
                f"CTC 头输入维度 {ctc_dim} ≠ 编码器输出维度 {enc_dim}，CTC 首遍已禁用"
            )
            self._ctc = None

        ctc_usable = self._ctc is not None

        # ⑥ 模式判定（顺序语义见 resolve_mode 的 docstring）
        has_decoder = self._llm is not None
        self.mode = resolve_mode(
            split_encoder=self._is_split,
            has_decoder=has_decoder,
            enable_ctc=cfg.enable_ctc,
            ctc_usable=ctc_usable,
        )
        self.has_timestamps = self.mode in (MODE_CTC, MODE_TWO_PASS)

        # 纯 CTC 模式没有 CTC 头 = 没有推理路径，必须启动时就硬失败
        # （而不是等第一段音频进来才抛 KeyError/AttributeError）
        if self.mode == MODE_CTC and self._ctc is None:
            raise ValueError(
                "纯 CTC 模式缺少可用的 CTC 头（ctc_onnx_path 不存在或维度不符），"
                "无推理路径"
            )

        # 只有 CTC 首遍会用到紧凑词表；纯 LLM 模式不该因为 tokens 缺失而起不来
        if self.mode in (MODE_CTC, MODE_TWO_PASS):
            self.id2bytes = load_tokens(cfg.tokens_path)

        # ⑦ 预热：失败向上抛（真实错误不能吞），把首帧开销挪到启动阶段
        if self._llm is not None:
            self._llm.warmup()

        ctc_desc = Path(cfg.ctc_onnx_path).name if self._ctc is not None else "无"
        llm_desc = Path(cfg.decoder_gguf_path).name if self._llm is not None else "无"
        self.logger.info(
            f"Qwen3-ASR 引擎载入完成: mode={self.mode}, "
            f"encoder={'split' if self._is_split else 'fused'}, "
            f"encoder_dim={enc_dim}, "
            f"vocab={len(self.id2bytes)}, ctc={ctc_desc}, llm={llm_desc}, "
            f"has_timestamps={self.has_timestamps}"
        )

    def _build_encoder(self):
        """融合（1.7B）或前后端拆分（0.6B）编码器；只配一端是硬错误"""
        cfg = self.config
        frontend = cfg.encoder_frontend_path or ""
        backend = cfg.encoder_backend_path or ""

        if frontend and backend:
            for path in (frontend, backend):
                if not Path(path).is_file():
                    raise ValueError(f"0.6B 编码器文件不存在: {path}")
            self._is_split = True
            return SplitEncoder(
                frontend,
                backend,
                cfg.preprocessor_path,
                num_threads=cfg.num_threads,
                provider=cfg.provider,
                logger=self.logger,
            )

        if frontend or backend:
            raise ValueError(
                "0.6B 编码器前后端必须成对配置：encoder_frontend_path 与 "
                "encoder_backend_path 只配了其中一个"
            )

        if not Path(cfg.encoder_onnx_path).is_file():
            raise ValueError(f"编码器 ONNX 不存在: {cfg.encoder_onnx_path}")

        return FusedEncoder(
            cfg.encoder_onnx_path,
            cfg.preprocessor_path,
            num_threads=cfg.num_threads,
            provider=cfg.provider,
            mel_frames=cfg.mel_frames,
            logger=self.logger,
        )

    # ── 编码 ──────────────────────────────────────────────────────────
    @staticmethod
    def _valid_frames(mel_len: int) -> int:
        """兼容旧调用（实现已迁到 encoder.valid_frames）"""
        return valid_frames(mel_len)

    def _encode(self, audio: np.ndarray) -> np.ndarray:
        """音频 -> 音频 embedding [valid_frames, output_dim]"""
        return self._enc.encode(audio)

    # ── CTC 解码 ──────────────────────────────────────────────────────
    def _ctc_ids(self, enc_output: np.ndarray) -> np.ndarray:
        """
        embedding -> 逐帧 token id

        CTC 头输出 logits [1, time, vocab]，在 30 秒音频上是 113MB。
        这里在主机侧做 argmax（上游用「图内追加 ArgMax」优化，但依赖 onnx 包，
        本机没有 onnx，故保留主机侧实现）。
        """
        out = self._ctc.run(None, {"enc_output": enc_output[None]})[0]
        if out.dtype == np.int64:
            # 已经是 argmax 后的 id（部分导出会把 argmax 放进图里）
            return out[0]
        return np.argmax(out[0], axis=-1)

    def _collapse(self, ids: np.ndarray) -> List[Tuple[int, int]]:
        """
        贪心折叠：去掉连续重复，去掉 blank / unk

        Returns:
            [(紧凑 id, 帧号), ...]
        """
        kept: List[Tuple[int, int]] = []
        prev = None
        for frame, tok in enumerate(ids):
            tok = int(tok)
            if tok == prev:
                continue
            prev = tok
            if tok in (self.config.blank_id, self.config.unk_id):
                continue
            kept.append((tok, frame))
        return kept

    def _decode_kept(
        self, kept: List[Tuple[int, int]], time_offset: float
    ) -> Tuple[str, List[str], List[float]]:
        """
        CTC token 序列 -> (文本, 字级 token, 字级时间戳)

        **必须走字节**：紧凑词表只保留 89 个字节基元，一个中文字符可能
        横跨多个 token。逐 token 各自 decode 会丢字节、产生乱码；正确做法
        是把所有 token 的字节按顺序拼成一条字节流，再整体解码。

        这里在字节流上做增量解码，同时记录每个字节属于哪个 token，从而
        得到「字符 -> 帧号」的映射，用于时间戳。

        token 一律拆到**单字符**，与 util/fun_asr_gguf 的 CTC 对齐结果保持
        一致（那边 tokens 是 char 粒度）。这样 `"".join(tokens) == text`
        恒成立，客户端的字幕对齐（util/client/srt_from_txt.py 按字符映射
        word 索引）才能正常工作。

        Returns:
            (文本, 字级 token 列表, 字级时间戳列表)
        """
        # 1. 拼字节流，并记录每个字节来自哪个 token 的哪一帧
        byte_frames: List[int] = []
        raw = bytearray()
        for tid, frame in kept:
            data = self.id2bytes.get(tid, b"")
            raw += data
            byte_frames.extend([frame] * len(data))

        # 2. 增量解码出字符
        tokens: List[str] = []
        timestamps: List[float] = []
        i = 0
        n = len(raw)
        while i < n:
            b = raw[i]
            if b < 0x80:
                length = 1
            elif 0xC0 <= b < 0xE0:
                length = 2
            elif 0xE0 <= b < 0xF0:
                length = 3
            elif 0xF0 <= b < 0xF8:
                length = 4
            else:
                length = 1  # 非法起始字节，单独吞掉

            chunk = bytes(raw[i : i + length])
            try:
                ch = chunk.decode("utf-8")
            except UnicodeDecodeError:
                ch = "\ufffd"

            start_frame = byte_frames[i] if i < len(byte_frames) else 0
            end_frame = (
                byte_frames[i + length - 1]
                if i + length - 1 < len(byte_frames)
                else start_frame
            )

            start = max(start_frame * FRAME_SEC - self.config.start_bias, 0.0)
            end = max((end_frame + 1) * FRAME_SEC - self.config.end_bias, start)
            tokens.append(ch)
            timestamps.append(start + time_offset)
            i += length

        return "".join(tokens), tokens, timestamps

    # ── 三种模式的单段解码 ────────────────────────────────────────────
    def _decode_ctc(
        self, enc: np.ndarray, time_offset: float
    ) -> Tuple[str, List[str], List[float]]:
        """纯 CTC：折叠 + 字节反解（时间戳平移到段起点）"""
        kept = self._collapse(self._ctc_ids(enc))
        return self._decode_kept(kept, time_offset)

    def _decode_two_pass(
        self, enc: np.ndarray, chunk: np.ndarray, time_offset: float
    ) -> Tuple[str, List[str], List[float]]:
        """
        两遍：CTC 首遍选字符/起始帧，LLM 二遍出文本，再 NW 对齐合成时间戳。

        同一个 encoder 输出喂两遍（不重复编码）。LLM 失败时回退该段的
        CTC 文本与时间戳，保证「降级也仍有输出」。
        """
        kept = self._collapse(self._ctc_ids(enc))
        ctc_text, ctc_chars, ctc_starts = self._decode_kept(kept, 0.0)

        try:
            llm_text = self._llm.generate(enc)
        except Exception as exc:
            self.logger.error(
                f"LLM 二遍生成失败，回退该段 CTC 文本: {exc}"
            )
            timestamps = [ts + time_offset for ts in ctc_starts]
            return ctc_text, list(ctc_chars), timestamps

        llm_text = llm_text or ""
        if not llm_text:
            # 空串当作静音段：两遍模式丢这一段（CTC 文本也不回退），避免把
            # CTC 的噪声字混进来。只有 LLM **抛异常** 时才回退 CTC 文本（见上面的
            # except 分支，规格 §7.6）。
            return "", [], []

        duration = len(chunk) / float(SAMPLE_RATE)
        starts = align_ctc_to_llm(ctc_chars, ctc_starts, llm_text, duration)
        timestamps = [float(s) + time_offset for s in starts]
        return llm_text, list(llm_text), timestamps

    def _decode_llm(self, enc: np.ndarray) -> str:
        """纯 LLM：只有文本，没有时间戳"""
        return self._llm.generate(enc) or ""

    # ── 公开 API ──────────────────────────────────────────────────────
    def decode(self, audio: np.ndarray) -> RecognitionResult:
        """
        识别一段音频（任意长度，内部按 30 秒切段）

        Args:
            audio: float32 单声道 16kHz 波形

        Returns:
            RecognitionResult（text / tokens / timestamps）。
            纯 LLM 模式下 tokens / timestamps 为空列表。
        """
        if not self.mode:
            raise RuntimeError("引擎尚未初始化：请先调用 initialize()")

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        seg_len = int(SEGMENT_SEC * SAMPLE_RATE)

        all_tokens: List[str] = []
        all_timestamps: List[float] = []
        text_parts: List[str] = []

        for i, start in enumerate(range(0, max(len(audio), 1), seg_len)):
            chunk = audio[start : start + seg_len]
            if chunk.size == 0:
                break
            offset = i * SEGMENT_SEC
            enc = self._encode(chunk)

            if self.mode == MODE_CTC:
                chunk_text, tokens, timestamps = self._decode_ctc(enc, offset)
            elif self.mode == MODE_TWO_PASS:
                chunk_text, tokens, timestamps = self._decode_two_pass(
                    enc, chunk, offset
                )
            else:
                chunk_text, tokens, timestamps = self._decode_llm(enc), [], []

            text_parts.append(chunk_text)
            all_tokens += tokens
            all_timestamps += timestamps

        return RecognitionResult(
            text="".join(text_parts), tokens=all_tokens, timestamps=all_timestamps
        )

    def create_stream(self) -> RecognitionStream:
        """创建识别流（兼容 sherpa-onnx API）"""
        return RecognitionStream(sample_rate=SAMPLE_RATE)

    def decode_stream(self, stream: RecognitionStream) -> RecognitionResult:
        """
        解码识别流（兼容 sherpa-onnx API）

        注意：sherpa-onnx 的 decode_stream 是原地写入 stream.result，
        这里保持一致，同时返回结果方便调用方直接使用。
        """
        if stream.audio_data is None:
            stream.set_result(text="", timestamps=[], tokens=[])
            return stream.result

        t0 = time.perf_counter()
        result = self.decode(stream.audio_data)
        elapsed = time.perf_counter() - t0

        stream.set_result(
            text=result.text, timestamps=result.timestamps, tokens=result.tokens
        )
        if self.config.verbose:
            self.logger.debug(
                f"Qwen3-ASR[{self.mode}] 解码耗时 {elapsed:.3f}s, "
                f"{len(result.tokens)} tokens, 文本 {result.text[:50]!r}"
            )
        return stream.result

    def transcribe(self, audio: np.ndarray) -> RecognitionResult:
        """识别音频（便捷接口）"""
        return self.decode(audio)

    def cleanup(self) -> None:
        """释放资源：解码器 → 编码器 → CTC 头（llama 侧先放）"""
        for attr in ("_llm", "_enc"):
            obj = getattr(self, attr, None)
            setattr(self, attr, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception as exc:  # 释放失败不该打断调用方的收尾流程
                    self.logger.debug(f"关闭 {attr} 失败: {exc}")
        self._ctc = None
        # config 是公开可变属性：split 初始化 → cleanup → 改 fused 再 initialize 时，
        # 若不复位，_build_encoder 的 fused 分支不会把它设回 False，模式判定会误判
        self._is_split = False
        self.id2bytes = {}
        self.mode = ""
        self.has_timestamps = False


def create_qwen_ctc_engine(
    encoder_onnx_path: str,
    ctc_onnx_path: str,
    tokens_path: str,
    preprocessor_path: str,
    blank_id: int = 72466,
    unk_id: int = 72467,
    mel_frames: int = MEL_FRAMES,
    num_threads: int = 6,
    provider: str = "cpu",
    start_bias: float = DEFAULT_START_BIAS,
    end_bias: float = DEFAULT_END_BIAS,
    verbose: bool = False,
    logger: Optional[Logger] = None,
    decoder_gguf_path: str = "",
    encoder_frontend_path: str = "",
    encoder_backend_path: str = "",
    enable_ctc: bool = True,
    llm_n_ctx: int = 4096,
    llm_n_threads: int = 6,
    llm_n_predict: int = 256,
) -> QwenCTCEngine:
    """便捷构造：返回已初始化（含模式判定与预热）的引擎"""
    engine = QwenCTCEngine(
        QwenCTCConfig(
            encoder_onnx_path=encoder_onnx_path,
            ctc_onnx_path=ctc_onnx_path,
            tokens_path=tokens_path,
            preprocessor_path=preprocessor_path,
            blank_id=blank_id,
            unk_id=unk_id,
            mel_frames=mel_frames,
            num_threads=num_threads,
            provider=provider,
            start_bias=start_bias,
            end_bias=end_bias,
            verbose=verbose,
            decoder_gguf_path=decoder_gguf_path,
            encoder_frontend_path=encoder_frontend_path,
            encoder_backend_path=encoder_backend_path,
            enable_ctc=enable_ctc,
            llm_n_ctx=llm_n_ctx,
            llm_n_threads=llm_n_threads,
            llm_n_predict=llm_n_predict,
        ),
        logger=logger,
    )
    return engine.initialize()
