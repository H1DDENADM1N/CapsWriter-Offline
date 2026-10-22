# coding: utf-8
"""
Qwen3-ASR 编码器（ONNX）的两种形态

- **融合形态**（1.7B，`Qwen3-ASR-Encoder.q4.onnx`）：整段音频一次前向
  `input_features [128, 3000]` + `feature_length [1]` → `enc_output [390, 2048]`。
- **拆分形态**（0.6B，frontend + backend 两个 ONNX）：mel 按 100 帧切块逐块过
  frontend（`chunk_mel [1, 128, 100]` → `chunk_out [1, 13, 896]`），沿时间轴拼起来
  截断到有效帧数，再配 `attention_mask [1, 1, T, T]` 全 1 过 backend
  （`hidden_states [1, T, 896]` → `last_hidden_state [1, T, 1024]`）。

把「静默出错」的坑固化在这里：

1. **帧率是 13 fps**：有效输出帧数 = `full*13 + ceil(leave/8)`，其中
   `full, leave = divmod(mel_len, 100)`（见 `valid_frames`）。
2. **特征不补到 30 秒再取长度**：`padding=False` 取真实 mel 长度，再自己零填到
   导出桶，并把真实帧数作为 `feature_length` 传进去。
3. **拆分形态的 mask 是四维的**：backend 要 `[b, 1, t, t]` 的 float mask，不是
   `[b, t]`；传错维度不会报错，只会算错注意力。
4. **拆分形态末块必须补零到 100 帧**：frontend 只接受固定 100 帧的块。

`from transformers import WhisperFeatureExtractor` 必须留在 `__init__` 内部惰性
导入：模块顶层导入会在 llama.cpp 初始化之前把 torch 拉起来，破坏加载顺序约束。
"""

from pathlib import Path
from typing import List, Optional

import numpy as np
from loguru import logger as default_logger
from loguru._logger import Logger

# Qwen3-ASR 编码器的帧率（13 fps），不是 50 fps
FRAME_RATE_HZ = 13.0

# 融合 encoder 导出时用的 30 秒桶
MEL_FRAMES = 3000

# 拆分 encoder 的 frontend 块大小与每块输出帧数
CHUNK_MEL_FRAMES = 100
CHUNK_OUT_FRAMES = 13


def valid_frames(mel_len: int) -> int:
    """
    真实 mel 帧数 -> 编码器有效输出帧数

    Qwen3 每 100 帧 mel 出一帧（13 fps），不是每 8 帧出一帧。
    """
    full, leave = divmod(mel_len, 100)
    return full * CHUNK_OUT_FRAMES + (
        0 if leave == 0 else (leave - 1) // 8 + 1
    )


def resolve_providers(ort, provider: str) -> List[str]:
    """按配置选择推理后端；DML 不可用时静默回退 CPU"""
    available = ort.get_available_providers()
    if provider == "dml" and "DmlExecutionProvider" in available:
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def _session_options(ort, num_threads: int):
    """统一的 SessionOptions：线程数 + 全量图优化"""
    so = ort.SessionOptions()
    so.intra_op_num_threads = num_threads or 0
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return so


class _EncoderBase:
    """两种形态共用的加载 / 关闭 / 特征提取骨架"""

    output_dim: int = 0

    def __init__(
        self,
        preprocessor_path: str,
        num_threads: int = 6,
        provider: str = "cpu",
        logger: Optional[Logger] = None,
    ):
        import onnxruntime as ort
        from transformers import WhisperFeatureExtractor

        self.logger = logger if logger is not None else default_logger
        self.providers = resolve_providers(ort, provider)
        self._num_threads = num_threads
        self._ort = ort
        self._fe = WhisperFeatureExtractor.from_pretrained(preprocessor_path)
        # 特征提取器自带的窗口长度（样本数）；超长音频会被它静默截断
        self.n_samples = int(getattr(self._fe, "n_samples", MEL_FRAMES * 160))

    def _new_session(self, path: str):
        return self._ort.InferenceSession(
            path,
            sess_options=_session_options(self._ort, self._num_threads),
            providers=self.providers,
        )

    def _mel(self, audio: np.ndarray) -> np.ndarray:
        """音频 -> [128, 真实 mel 帧数]（不补到 30 秒桶）"""
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        return self._fe(
            audio, sampling_rate=16000, padding=False, return_tensors="np"
        ).input_features[0]

    def _ensure_open(self) -> None:
        if self._fe is None:
            raise RuntimeError("encoder 已关闭，不能再调用 encode()")

    def close(self) -> None:
        """释放 ONNX 会话与特征提取器（幂等）"""
        self._sess = None
        self._front = None
        self._back = None
        self._fe = None


class FusedEncoder(_EncoderBase):
    """
    融合单段 encoder（1.7B）

    `encode(audio)` -> `[valid_frames(t), output_dim]`，`t` 是真实 mel 帧数。
    输入音频必须 <= 30 秒（导出桶是 3000 帧 mel）。
    """

    def __init__(
        self,
        encoder_path: str,
        preprocessor_path: str,
        num_threads: int = 6,
        provider: str = "cpu",
        mel_frames: int = MEL_FRAMES,
        logger: Optional[Logger] = None,
    ):
        super().__init__(
            preprocessor_path,
            num_threads=num_threads,
            provider=provider,
            logger=logger,
        )
        self.encoder_path = encoder_path
        self.mel_frames = int(mel_frames)
        self._sess = self._new_session(encoder_path)
        self.output_dim = int(self._sess.get_outputs()[0].shape[-1])

        self.logger.info(
            f"Qwen3-ASR 融合 encoder 载入完成: {Path(encoder_path).name}, "
            f"dim={self.output_dim}, providers={self.providers}"
        )

    def encode(self, audio: np.ndarray) -> np.ndarray:
        """
        音频 -> 音频 embedding `[valid_frames(t), output_dim]`

        Args:
            audio: float32 单声道 16kHz 波形（<= 30 秒）

        Raises:
            RuntimeError: encoder 已关闭
            ValueError: 音频超过 30 秒导出桶
        """
        self._ensure_open()
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        # WhisperFeatureExtractor 会把超过窗口的音频静默截断到 3000 帧 mel，
        # 所以必须在特征提取**之前**按样本数拦截。
        max_samples = min(self.mel_frames * 160, self.n_samples)
        if audio.size > max_samples:
            raise ValueError(
                f"音频超过 {self.mel_frames // 100} 秒导出桶"
                f"（{audio.size} 样本 > {max_samples}），调用方必须先切段"
            )

        mel = self._mel(audio)
        t = mel.shape[1]
        if t > self.mel_frames:
            raise ValueError(
                f"音频超过 {self.mel_frames / 100:.0f} 秒导出桶"
                f"（{t} 帧 mel > {self.mel_frames}），调用方必须先切段"
            )
        if t == 0:
            return np.zeros((0, self.output_dim), dtype=np.float32)

        padded = np.zeros((mel.shape[0], self.mel_frames), dtype=np.float32)
        padded[:, :t] = mel
        enc = self._sess.run(
            None,
            {
                "input_features": padded,
                "feature_length": np.array([t], np.int64),
            },
        )[0]
        return enc[: valid_frames(t)].astype(np.float32)


class SplitEncoder(_EncoderBase):
    """
    前后端拆分 encoder（0.6B）

    `encode(audio)` -> `[valid_frames(t), output_dim]`。mel 按 100 帧切块，
    末块补零，逐块过 frontend 后沿时间轴拼接，截断到有效帧数，再配四维全 1
    的 `attention_mask` 过 backend。

    预处理器复用 1.7B 的 30 秒配置，所以输入音频同样必须 <= 30 秒；超长音频
    必须在调用方切段（WhisperFeatureExtractor 会静默截断）。
    """

    def __init__(
        self,
        frontend_path: str,
        backend_path: str,
        preprocessor_path: str,
        num_threads: int = 6,
        provider: str = "cpu",
        logger: Optional[Logger] = None,
    ):
        super().__init__(
            preprocessor_path,
            num_threads=num_threads,
            provider=provider,
            logger=logger,
        )
        self.frontend_path = frontend_path
        self.backend_path = backend_path
        self._front = self._new_session(frontend_path)
        self._back = self._new_session(backend_path)
        self.output_dim = int(self._back.get_outputs()[0].shape[-1])

        self.logger.info(
            f"Qwen3-ASR 拆分 encoder 载入完成: "
            f"{Path(frontend_path).name} + {Path(backend_path).name}, "
            f"dim={self.output_dim}, providers={self.providers}"
        )

    def encode(self, audio: np.ndarray) -> np.ndarray:
        """
        音频 -> 音频 embedding `[valid_frames(t), output_dim]`

        Args:
            audio: float32 单声道 16kHz 波形（<= 30 秒）

        Raises:
            RuntimeError: encoder 已关闭
            ValueError: 音频超过 30 秒导出桶
        """
        self._ensure_open()
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        max_samples = min(MEL_FRAMES * 160, self.n_samples)
        if audio.size > max_samples:
            raise ValueError(
                f"音频超过 30 秒导出桶"
                f"（{audio.size} 样本 > {max_samples}），调用方必须先切段"
            )

        mel = self._mel(audio)
        t = mel.shape[1]
        if t == 0:
            return np.zeros((0, self.output_dim), dtype=np.float32)

        n_chunks = (t + CHUNK_MEL_FRAMES - 1) // CHUNK_MEL_FRAMES
        padded = np.zeros(
            (mel.shape[0], n_chunks * CHUNK_MEL_FRAMES), dtype=np.float32
        )
        padded[:, :t] = mel

        chunks = []
        for i in range(n_chunks):
            block = padded[:, i * CHUNK_MEL_FRAMES : (i + 1) * CHUNK_MEL_FRAMES]
            chunks.append(self._front.run(None, {"chunk_mel": block[None]})[0][0])
        hidden = np.concatenate(chunks, axis=0)  # [n_chunks * 13, 896]

        n = valid_frames(t)
        hidden = hidden[:n]
        attention_mask = np.ones((1, 1, n, n), dtype=np.float32)
        enc = self._back.run(
            None,
            {
                "hidden_states": hidden[None].astype(np.float32),
                "attention_mask": attention_mask,
            },
        )[0]
        return enc[0].astype(np.float32)
