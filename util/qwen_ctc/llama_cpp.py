# coding: utf-8
"""
Qwen 两遍引擎专用的 llama.cpp ctypes 绑定层

为什么自己写而不复用 ``util/fun_asr_gguf/llama.py``：
Qwen 功能要求所有代码落在 ``util/qwen_ctc/``，不允许 import 那边的大杂烩
模块（它还会加载采样器、GGUF 工具等一堆这里不需要的东西）。这里只绑定
LLM 二遍解码真正用到的符号。

ABI 依据（随包二进制 = llama.cpp b11675，win-vulkan-x64）：
    - 结构体字段顺序照抄 ``util/fun_asr_gguf/llama.py`` 里已对齐 b11675 的
      ``llama_model_params`` / ``llama_context_params`` / ``llama_batch``；
    - 调用序列照抄已跑通的 ``dev/_spike_qwen3vl_load.py`` 与
      ``dev/_spike_qwen3vl_asr.py``：4 平面 M-RoPE 位置、embd 批次、
      ``llama_get_logits_ith`` 取整行 logits。

M-RoPE（IMROPE，rope_type=40）的位置布局要点：
    - ``llama_batch.pos`` 是单个指针，容量按 ``llama_batch_init(n_tokens_alloc,
      ...)`` 分配，而 M-RoPE 需要每个 token 4 个位置，所以 batch 要按
      ``max(n*4, 8192)`` 分配、只填前 n 个 token 行；
    - 4 个平面是「段优先」（section-major）：``pos[j*n + i]``，j ∈ 0..3，
      j<3 取该 token 的时间位置，j=3 恒为 0；
    - embedding 批次必须把 ``batch.token`` 置 NULL，否则 llama.cpp 会走
      token id 查表路径，忽略 ``batch.embd``。
"""

from __future__ import annotations

import os

# Windows 上 llama.cpp 与 onnxruntime 会各自带一份 OpenMP 运行时，
# 同时加载会直接 abort；必须在 import numpy/ctypes 之前设好。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import ctypes  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
from collections import deque  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import List, Optional, Sequence, Union  # noqa: E402

import numpy as np  # noqa: E402

__all__ = ["Context", "LlamaLoadError", "Model", "init_lib"]

_BIN_DIR = Path(__file__).resolve().parent / "bin"

llama_token = ctypes.c_int32
llama_pos = ctypes.c_int32
llama_seq_id = ctypes.c_int32

# Qwen3-ASR 解码器用的 M-RoPE 平面数
_MROPE_PLANES = 4
# 位置数组的最小分配量：llama.cpp 要求 batch 的 pos 容量按 token 数分配，
# 这里给出 4 倍余量并设下限，避免小批次反复重新分配。
_MIN_BATCH_ALLOC = 8192


# =========================================================================
# ctypes 结构体（对齐 llm.cpp b11675 的 include/llama.h）
# =========================================================================
class llama_model_params(ctypes.Structure):
    """b11675: use_mmap/use_mlock 已被 load_mode/lazy_mode 取代，末尾多了 load_mtp"""

    _fields_ = [
        ("devices", ctypes.POINTER(ctypes.c_void_p)),
        ("tensor_buft_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("n_gpu_layers", ctypes.c_int32),
        ("split_mode", ctypes.c_int32),
        ("load_mode", ctypes.c_int32),
        ("lazy_mode", ctypes.c_int32),
        ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.POINTER(ctypes.c_float)),
        (
            "progress_callback",
            ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_float, ctypes.c_void_p),
        ),
        ("progress_callback_user_data", ctypes.c_void_p),
        ("kv_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("vocab_only", ctypes.c_bool),
        ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool),
        ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool),
        ("load_mtp", ctypes.c_bool),
    ]


class llama_context_params(ctypes.Structure):
    """b11675 在 n_seq_max 后新增 n_rs_seq 等字段，type_v 后新增 moe_cache_size"""

    _fields_ = [
        ("n_ctx", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint32),
        ("n_ubatch", ctypes.c_uint32),
        ("n_seq_max", ctypes.c_uint32),
        ("n_rs_seq", ctypes.c_uint32),
        ("n_outputs_max", ctypes.c_uint32),
        ("n_outputs_max_per_seq", ctypes.c_uint32),
        ("n_threads", ctypes.c_int32),
        ("n_threads_batch", ctypes.c_int32),
        ("ctx_type", ctypes.c_int32),
        ("rope_scaling_type", ctypes.c_int32),
        ("pooling_type", ctypes.c_int32),
        ("attention_type", ctypes.c_int32),
        ("flash_attn_type", ctypes.c_int32),
        ("rope_freq_base", ctypes.c_float),
        ("rope_freq_scale", ctypes.c_float),
        ("yarn_ext_factor", ctypes.c_float),
        ("yarn_attn_factor", ctypes.c_float),
        ("yarn_beta_fast", ctypes.c_float),
        ("yarn_beta_slow", ctypes.c_float),
        ("yarn_orig_ctx", ctypes.c_uint32),
        ("defrag_thold", ctypes.c_float),
        ("cb_eval", ctypes.c_void_p),
        ("cb_eval_user_data", ctypes.c_void_p),
        ("type_k", ctypes.c_int32),
        ("type_v", ctypes.c_int32),
        ("moe_cache_size", ctypes.c_size_t),
        ("abort_callback", ctypes.c_void_p),
        ("abort_callback_data", ctypes.c_void_p),
        ("embeddings", ctypes.c_bool),
        ("offload_kqv", ctypes.c_bool),
        ("no_perf", ctypes.c_bool),
        ("op_offload", ctypes.c_bool),
        ("swa_full", ctypes.c_bool),
        ("kv_unified", ctypes.c_bool),
        ("samplers", ctypes.POINTER(ctypes.c_void_p)),
        ("n_samplers", ctypes.c_size_t),
        ("ctx_other", ctypes.c_void_p),
    ]


class llama_batch(ctypes.Structure):
    """legacy batch；pos 容量由 llama_batch_init 的 n_tokens 决定（M-RoPE 时 ×4）"""

    _fields_ = [
        ("n_tokens", ctypes.c_int32),
        ("token", ctypes.POINTER(llama_token)),
        ("embd", ctypes.POINTER(ctypes.c_float)),
        ("pos", ctypes.POINTER(llama_pos)),
        ("n_seq_id", ctypes.POINTER(ctypes.c_int32)),
        ("seq_id", ctypes.POINTER(ctypes.POINTER(llama_seq_id))),
        ("logits", ctypes.POINTER(ctypes.c_int8)),
    ]


class llama_sampler_chain_params(ctypes.Structure):
    """本任务不接采样器（T5 用贪心取 argmax），仅保留 ABI 定义备后续使用"""

    _fields_ = [
        ("no_perf", ctypes.c_bool),
    ]


# =========================================================================
# 库加载与符号绑定
# =========================================================================
class LlamaLoadError(RuntimeError):
    """GGUF 模型加载失败（区别于 DLL 本身加载失败）"""


_lib: Optional[ctypes.CDLL] = None
_ggml: Optional[ctypes.CDLL] = None
_ggml_base: Optional[ctypes.CDLL] = None
_dll_dir_handle = None
_log_callback = None
_lock = threading.RLock()
_log_tail: "deque[str]" = deque(maxlen=64)

# 绑定的 C 符号；init_lib() 成功后才有值
llama_backend_init = None
llama_backend_free = None
llama_log_set = None
llama_model_default_params = None
llama_model_load_from_file = None
llama_model_free = None
llama_model_n_embd = None
llama_model_rope_type = None
llama_model_get_vocab = None
llama_vocab_n_tokens = None
llama_vocab_eos = None
llama_tokenize = None
llama_token_to_piece = None
llama_batch_init = None
llama_batch_free = None
llama_batch_get_one = None
llama_context_default_params = None
llama_init_from_model = None
llama_free = None
llama_decode = None
llama_get_logits_ith = None
llama_get_memory = None
llama_memory_clear = None


def _dll_names() -> tuple[str, str, str]:
    if sys.platform == "win32":
        return "ggml.dll", "ggml-base.dll", "llama.dll"
    if sys.platform == "darwin":
        return "libggml.dylib", "libggml-base.dylib", "libllama.dylib"
    return "libggml.so", "libggml-base.so", "libllama.so"


def _bind(lib, name: str, argtypes=None, restype=None):
    """按名字绑定一个导出符号，并设置 argtypes/restype"""
    try:
        func = getattr(lib, name)
    except AttributeError as exc:  # pragma: no cover - 二进制版本不匹配时才会走到
        raise RuntimeError(
            f"当前 llama.cpp 二进制缺少符号 {name!r}（{lib._name}）"
        ) from exc
    if argtypes is not None:
        func.argtypes = argtypes
    if restype is not None:
        func.restype = restype
    return func


def _on_llama_log(level, text, user_data):  # pragma: no cover - 只做静默与留痕
    """把 llama.cpp 日志收进环形缓冲，默认不打印（避免污染测试输出）"""
    try:
        if text:
            _log_tail.append(text.decode("utf-8", "replace").rstrip())
    except Exception:
        traceback.print_exc()


def init_lib() -> None:
    """加载 bin/ 下的 ggml/llama DLL 并初始化 backend（幂等）"""
    global _lib, _ggml, _ggml_base, _dll_dir_handle, _log_callback
    global llama_backend_init, llama_backend_free, llama_log_set
    global llama_model_default_params, llama_model_load_from_file
    global llama_model_free, llama_model_n_embd, llama_model_rope_type
    global llama_model_get_vocab, llama_vocab_n_tokens, llama_vocab_eos
    global llama_tokenize, llama_token_to_piece
    global llama_batch_init, llama_batch_free, llama_batch_get_one
    global llama_context_default_params, llama_init_from_model, llama_free
    global llama_decode, llama_get_logits_ith, llama_get_memory, llama_memory_clear

    if _lib is not None:
        return

    with _lock:
        if _lib is not None:
            return

        if not _BIN_DIR.is_dir():
            raise RuntimeError(
                f"找不到 llama.cpp 二进制目录: {_BIN_DIR}；"
                "请把 llama.dll / ggml*.dll / libomp.dll 放到该目录"
                "（可直接从 util/fun_asr_gguf/bin 复制）"
            )

        # ggml backend 的 DLL 依赖（如 libomp.dll）需要从这里解析
        if hasattr(os, "add_dll_directory"):
            _dll_dir_handle = os.add_dll_directory(str(_BIN_DIR))
        os.environ["PATH"] = str(_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

        ggml_name, ggml_base_name, llama_name = _dll_names()
        try:
            ggml = ctypes.CDLL(str(_BIN_DIR / ggml_name))
            ggml_base = ctypes.CDLL(str(_BIN_DIR / ggml_base_name))
            lib = ctypes.CDLL(str(_BIN_DIR / llama_name))
        except OSError as exc:
            raise RuntimeError(
                f"加载 llama.cpp DLL 失败（{_BIN_DIR}）：{exc}"
            ) from exc

        # 先接管日志，避免 backend/模型加载时的 INFO 直接打到 stderr
        LOG_CALLBACK = ctypes.CFUNCTYPE(
            None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p
        )
        log_set = _bind(lib, "llama_log_set", [LOG_CALLBACK, ctypes.c_void_p], None)
        _log_callback = LOG_CALLBACK(_on_llama_log)
        log_set(_log_callback, None)

        # b11675 的 ggml_backend_load_all() 不再自动发现同目录的 backend DLL，
        # 必须按路径显式加载；CPU 后端是模型能加载的前提。
        backend_load = _bind(
            ggml, "ggml_backend_load", [ctypes.c_char_p], ctypes.c_bool
        )
        loaded_any = False
        for backend_name in ("ggml-cpu-x64.dll", "ggml-vulkan.dll"):
            backend_path = _BIN_DIR / backend_name
            if not backend_path.is_file():
                continue
            try:
                if backend_load(str(backend_path).encode("utf-8")):
                    loaded_any = True
            except Exception:
                # Vulkan 在没装显卡驱动的机器上加载失败是正常情况
                if backend_name == "ggml-cpu-x64.dll":
                    raise
        if not loaded_any:
            raise RuntimeError(
                f"未能加载任何 ggml backend（检查 {_BIN_DIR} 下的 "
                "ggml-cpu-x64.dll / ggml-vulkan.dll）"
            )

        backend_init = _bind(lib, "llama_backend_init", [], None)
        backend_init()

        # ── model ──
        model_default_params = _bind(
            lib, "llama_model_default_params", [], llama_model_params
        )
        model_load = _bind(
            lib,
            "llama_model_load_from_file",
            [ctypes.c_char_p, llama_model_params],
            ctypes.c_void_p,
        )
        model_free = _bind(lib, "llama_model_free", [ctypes.c_void_p], None)
        model_n_embd = _bind(
            lib, "llama_model_n_embd", [ctypes.c_void_p], ctypes.c_int32
        )
        model_rope_type = _bind(
            lib, "llama_model_rope_type", [ctypes.c_void_p], ctypes.c_int32
        )
        model_get_vocab = _bind(
            lib, "llama_model_get_vocab", [ctypes.c_void_p], ctypes.c_void_p
        )

        # ── vocab ──
        vocab_n_tokens = _bind(
            lib, "llama_vocab_n_tokens", [ctypes.c_void_p], ctypes.c_int32
        )
        vocab_eos = _bind(lib, "llama_vocab_eos", [ctypes.c_void_p], llama_token)
        tokenize = _bind(
            lib,
            "llama_tokenize",
            [
                ctypes.c_void_p,  # vocab
                ctypes.c_char_p,  # text
                ctypes.c_int32,  # text_len
                ctypes.POINTER(llama_token),  # tokens
                ctypes.c_int32,  # n_tokens_max
                ctypes.c_bool,  # add_special
                ctypes.c_bool,  # parse_special
            ],
            ctypes.c_int32,
        )
        token_to_piece = _bind(
            lib,
            "llama_token_to_piece",
            [
                ctypes.c_void_p,  # vocab
                llama_token,  # token
                ctypes.c_char_p,  # buf
                ctypes.c_int32,  # length
                ctypes.c_int32,  # lstrip
                ctypes.c_bool,  # special
            ],
            ctypes.c_int32,
        )

        # ── batch ──
        batch_init = _bind(
            lib,
            "llama_batch_init",
            [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32],
            llama_batch,
        )
        batch_free = _bind(lib, "llama_batch_free", [llama_batch], None)
        batch_get_one = _bind(
            lib,
            "llama_batch_get_one",
            [ctypes.POINTER(llama_token), ctypes.c_int32],
            llama_batch,
        )

        # ── context / decode ──
        context_default_params = _bind(
            lib, "llama_context_default_params", [], llama_context_params
        )
        init_from_model = _bind(
            lib,
            "llama_init_from_model",
            [ctypes.c_void_p, llama_context_params],
            ctypes.c_void_p,
        )
        free_ctx = _bind(lib, "llama_free", [ctypes.c_void_p], None)
        decode = _bind(
            lib, "llama_decode", [ctypes.c_void_p, llama_batch], ctypes.c_int32
        )
        # 返回一整行 logits（n_vocab 个 float）的首地址；必须显式声明，
        # 默认 restype 是 c_int，会把指针截断成 32 位。
        get_logits_ith = _bind(
            lib,
            "llama_get_logits_ith",
            [ctypes.c_void_p, ctypes.c_int32],
            ctypes.POINTER(ctypes.c_float),
        )
        get_memory = _bind(lib, "llama_get_memory", [ctypes.c_void_p], ctypes.c_void_p)
        memory_clear = _bind(
            lib, "llama_memory_clear", [ctypes.c_void_p, ctypes.c_bool], None
        )

        # 全部绑定成功后才发布全局状态，失败时下次调用可以重试
        backend_free = _bind(lib, "llama_backend_free", [], None)

        llama_log_set = log_set
        llama_backend_init = backend_init
        llama_backend_free = backend_free
        llama_model_default_params = model_default_params
        llama_model_load_from_file = model_load
        llama_model_free = model_free
        llama_model_n_embd = model_n_embd
        llama_model_rope_type = model_rope_type
        llama_model_get_vocab = model_get_vocab
        llama_vocab_n_tokens = vocab_n_tokens
        llama_vocab_eos = vocab_eos
        llama_tokenize = tokenize
        llama_token_to_piece = token_to_piece
        llama_batch_init = batch_init
        llama_batch_free = batch_free
        llama_batch_get_one = batch_get_one
        llama_context_default_params = context_default_params
        llama_init_from_model = init_from_model
        llama_free = free_ctx
        llama_decode = decode
        llama_get_logits_ith = get_logits_ith
        llama_get_memory = get_memory
        llama_memory_clear = memory_clear

        # 最后再置位“已初始化”哨兵，避免半初始化状态被后续调用当成成功
        _ggml = ggml
        _ggml_base = ggml_base
        _lib = lib


def _require_lib() -> None:
    if _lib is None:
        raise RuntimeError("llama.cpp 尚未初始化，请先调用 init_lib()")


# =========================================================================
# Model
# =========================================================================
class Model:
    """GGUF 模型的薄封装：词表 + 元数据 + 生命周期"""

    def __init__(self, path: Union[str, Path], n_gpu_layers: int = -1):
        model_path = Path(path).expanduser()
        if not model_path.is_file():
            raise LlamaLoadError(f"模型文件不存在: {model_path}")

        init_lib()

        params = llama_model_default_params()
        params.n_gpu_layers = int(n_gpu_layers)

        # 绝对路径加载：进程 cwd 可能被别的模块切走
        self.path = model_path.resolve()
        self._ptr = llama_model_load_from_file(
            str(self.path).encode("utf-8"), params
        )
        if not self._ptr:
            raise LlamaLoadError(f"llama.cpp 无法加载模型: {path}")

        self._vocab = llama_model_get_vocab(self._ptr)
        self.n_embd = int(llama_model_n_embd(self._ptr))
        self.n_rope_type = int(llama_model_rope_type(self._ptr))
        self.n_vocab = int(llama_vocab_n_tokens(self._vocab))

    def _ensure_alive(self) -> None:
        if not self._ptr:
            raise RuntimeError("模型已释放（Model.free() 之后不能再使用）")

    @property
    def rope_type(self) -> int:
        """``n_rope_type`` 的只读别名（规格 §9.4 自检项用 n_rope_type）"""
        return self.n_rope_type

    def tokenize(
        self, text: str, add_special: bool = False, parse_special: bool = True
    ) -> List[int]:
        """文本 → token id 列表（默认不自动加 BOS，但解析 <|im_start|> 等特殊 token）"""
        self._ensure_alive()
        text_bytes = text.encode("utf-8")
        n_max = len(text_bytes) + 32
        tokens = (llama_token * n_max)()
        n = llama_tokenize(
            self._vocab,
            text_bytes,
            len(text_bytes),
            tokens,
            n_max,
            add_special,
            parse_special,
        )
        if n < 0:
            # 负返回值 = 需要的缓冲区大小
            n_max = -n
            tokens = (llama_token * n_max)()
            n = llama_tokenize(
                self._vocab,
                text_bytes,
                len(text_bytes),
                tokens,
                n_max,
                add_special,
                parse_special,
            )
        return [int(tokens[i]) for i in range(n)] if n > 0 else []

    def token_to_bytes(self, token_id: int) -> bytes:
        """单个 token → 原始字节（一个汉字可能横跨多个 token，必须先拼字节）"""
        self._ensure_alive()
        buf = ctypes.create_string_buffer(256)
        n = llama_token_to_piece(
            self._vocab, int(token_id), buf, ctypes.sizeof(buf), 0, True
        )
        if n < 0:
            buf = ctypes.create_string_buffer(-n)
            n = llama_token_to_piece(
                self._vocab, int(token_id), buf, ctypes.sizeof(buf), 0, True
            )
        return buf.raw[:n] if n > 0 else b""

    def detokenize(self, tokens: Sequence[int]) -> str:
        """token id 列表 → 文本（按字节整体解码，避免截断 UTF-8）"""
        if not tokens:
            return ""
        return b"".join(self.token_to_bytes(t) for t in tokens).decode(
            "utf-8", errors="replace"
        )

    def free(self) -> None:
        """释放模型；必须先释放所有引用它的 Context"""
        if self._ptr:
            llama_model_free(self._ptr)
            self._ptr = None
            self._vocab = None

    def __del__(self):  # pragma: no cover - 解释器退出路径
        try:
            self.free()
        except Exception:
            pass


# =========================================================================
# Context
# =========================================================================
class Context:
    """推理上下文：embd 批次预填充 + 单 token 解码"""

    def __init__(
        self,
        model: Model,
        n_ctx: int,
        n_batch: Optional[int] = None,
        n_ubatch: int = 512,
        n_threads: int = 6,
    ):
        init_lib()
        if not isinstance(model, Model):
            raise TypeError("Context 需要 llama_cpp.Model 实例")
        if not model._ptr:
            raise RuntimeError("模型已释放，不能创建 Context")

        self.model = model  # 持有引用，防止 Model 被提前回收
        self.n_ctx = int(n_ctx)
        # n_batch 未显式给出时取 n_ctx：预填充整段 prompt 不会被批次上限截断
        self.n_batch = int(n_batch) if n_batch is not None else self.n_ctx
        self.n_ubatch = max(1, min(int(n_ubatch), self.n_batch))
        self.n_threads = max(1, int(n_threads))

        params = llama_context_default_params()
        params.n_ctx = self.n_ctx
        params.n_batch = self.n_batch
        params.n_ubatch = self.n_ubatch
        params.n_seq_max = 1
        # prefill 与 decode 共用同一线程数（Ruling R3：接口只暴露 n_threads）
        params.n_threads = self.n_threads
        params.n_threads_batch = self.n_threads
        # b11675 默认 flash_attn_type = AUTO(-1)，在 Vulkan 后端上对它这个
        # M-RoPE 模型会启用 FA 并输出全 NaN；显式关掉（与 fun_asr_gguf 的
        # 默认 flash_attn=False 一致），CPU/GPU 结果都正确。
        params.flash_attn_type = 0
        params.no_perf = True
        params.offload_kqv = True

        self._ptr = llama_init_from_model(model._ptr, params)
        if not self._ptr:
            raise RuntimeError("上下文初始化失败（llama_init_from_model 返回 NULL）")

    def _ensure_alive(self) -> None:
        _require_lib()
        if not self._ptr:
            raise RuntimeError("上下文已释放（Context.free() 之后不能再使用）")
        if not self.model._ptr:
            raise RuntimeError("底层模型已释放，上下文不可再用")

    def decode_embd(
        self, rows: np.ndarray, pos: Optional[np.ndarray] = None
    ) -> int:
        """把 [n, n_embd] 的 embedding 行作为一个批次注入，返回 llama_decode 的返回码

        ``pos`` 为 None 时按单平面递增位置合成 4 平面 M-RoPE 位置
        （j<3 用 token 位置、j=3 恒 0）；显式传入时必须是长度 4n 的数组。
        """
        self._ensure_alive()
        rows = np.ascontiguousarray(rows, dtype=np.float32)
        if rows.ndim != 2:
            raise ValueError(f"rows 必须是二维数组，实际 ndim={rows.ndim}")
        n = int(rows.shape[0])
        if n <= 0:
            raise ValueError("rows 不能为空")
        if rows.shape[1] != self.model.n_embd:
            raise ValueError(
                f"rows 的列数 {rows.shape[1]} != 模型 n_embd {self.model.n_embd}"
            )
        if n > self.n_batch:
            raise ValueError(
                f"单批 token 数 {n} 超过 n_batch={self.n_batch}"
                "（创建 Context 时调大 n_batch/n_ctx）"
            )

        if pos is None:
            planes = np.arange(n, dtype=np.int32)
            pos4 = np.concatenate(
                [planes] * (_MROPE_PLANES - 1)
                + [np.zeros(n, dtype=np.int32)]
            )
        else:
            pos4 = np.ascontiguousarray(pos, dtype=np.int32).reshape(-1)
            if pos4.size != _MROPE_PLANES * n:
                raise ValueError(
                    f"pos 长度必须是 {_MROPE_PLANES * n}（4 平面 M-RoPE），"
                    f"实际 {pos4.size}"
                )

        # pos 容量需要 4n，而只填 n 个 token 行，所以按 4 倍分配
        n_tokens_max = max(n * _MROPE_PLANES, _MIN_BATCH_ALLOC)
        batch = llama_batch_init(n_tokens_max, self.model.n_embd, 1)
        try:
            ctypes.memmove(batch.embd, rows.ctypes.data, rows.nbytes)
            ctypes.memmove(batch.pos, pos4.ctypes.data, pos4.nbytes)
            batch.n_tokens = n
            for i in range(n):
                batch.n_seq_id[i] = 1
                batch.seq_id[i][0] = 0
                batch.logits[i] = 1 if i == n - 1 else 0
            # token 指针置 NULL，强制 llama.cpp 走 embd 路径
            batch.token = ctypes.cast(None, ctypes.POINTER(llama_token))
            return int(llama_decode(self._ptr, batch))
        finally:
            llama_batch_free(batch)

    def decode_tokens(self, tokens: Sequence[int]) -> int:
        """解码若干 token（位置由 llama.cpp 按 KV 末尾自动续接）"""
        self._ensure_alive()
        ids = [int(t) for t in tokens]
        if not ids:
            raise ValueError("tokens 不能为空")
        if len(ids) > self.n_batch:
            raise ValueError(
                f"单批 token 数 {len(ids)} 超过 n_batch={self.n_batch}"
            )
        arr = (llama_token * len(ids))(*ids)
        # llama_batch_get_one 按值返回结构体，且它不拥有 arr 的内存；
        # 这里不能 llama_batch_free（见 llama.h 注释）。
        batch = llama_batch_get_one(arr, len(ids))
        return int(llama_decode(self._ptr, batch))

    def logits_ith(self, i: int = -1) -> np.ndarray:
        """取第 i 个 token 的整行 logits（i=-1 表示批次最后一个）"""
        self._ensure_alive()
        ptr = llama_get_logits_ith(self._ptr, int(i))
        if not ptr:
            raise RuntimeError(f"llama_get_logits_ith({i}) 返回 NULL（该位置没有 logits）")
        # copy：下一次 decode 会覆盖底层缓冲区
        return np.ctypeslib.as_array(
            ptr, shape=(self.model.n_vocab,)
        ).copy()

    def clear_kv(self) -> None:
        """清空 KV cache，为下一段音频复用上下文"""
        self._ensure_alive()
        memory = llama_get_memory(self._ptr)
        if memory:
            llama_memory_clear(memory, True)

    def free(self) -> None:
        if self._ptr:
            llama_free(self._ptr)
            self._ptr = None

    def __del__(self):  # pragma: no cover - 解释器退出路径
        try:
            self.free()
        except Exception:
            pass
