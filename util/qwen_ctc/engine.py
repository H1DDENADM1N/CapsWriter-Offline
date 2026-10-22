# coding: utf-8
"""
Qwen3-ASR + CTC 头 推理引擎

流程：音频 → Whisper 特征 → Qwen3-ASR 编码器（ONNX）→ CTC 头（ONNX）
      → 贪心折叠 → 字节级反解 → 文本 + 字级时间戳

本模块直接对应 Qwen3-ASR-CTC-GGUF 的 `Qwen3CtcEngine`，但去掉了 llama.cpp
二遍部分（纯 CTC 首遍），并把三个「静默出错」的坑固化在实现里：

1. **帧率是 13 fps，不是 50**：有效输出帧数 = `full*13 + ceil(leave/8)`，
   其中 `full, leave = divmod(mel_frames, 100)`。写成 T/8 会得到完全错误的
   时间轴（不报错，只是时间戳对不上）。
2. **特征不补到 30 秒**：特征提取用 `padding=False` 取真实长度，再自己
   零填到导出时的 3000 帧桶，并把真实帧数作为 `feature_length` 传进去。
   直接让特征提取器补齐会丢掉「真实长度」这个信号。
3. **反解走字节**：`tokens.txt` 存的是 base64 原始字节，一个中文字符可能
   横跨多个 token，必须先拼字节再整体 decode。

另外：**编码器是按 30 秒桶导出的**，超过 30 秒的音频必须按 30 秒切段，
否则 WhisperFeatureExtractor 会静默截断（特征提取器的 padding 行为）。
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger as default_logger
from loguru._logger import Logger

from .encoder import (
    FRAME_RATE_HZ,
    MEL_FRAMES,
    FusedEncoder,
    resolve_providers,
    valid_frames,
)
from .schema import RecognitionResult, RecognitionStream
from .tokens import decode_bytes, load_tokens

# Qwen3-ASR 编码器的帧率（13 fps）与 30 秒桶在 encoder.py 里定义，这里 re-export
FRAME_SEC = 1.0 / FRAME_RATE_HZ

SEGMENT_SEC = 30.0

# CTC 尖峰式发射的系统性偏置（对 MFA 词级真值实测：起点晚 100ms、终点早 78.5ms）
DEFAULT_START_BIAS = 0.100
DEFAULT_END_BIAS = 0.0785


@dataclass
class QwenCTCConfig:
    """Qwen3-CTC 引擎配置"""

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


class QwenCTCEngine:
    """
    Qwen3-ASR + CTC 头 推理引擎

    对外接口与 sherpa-onnx 兼容：
        engine.create_stream() -> stream
        stream.accept_waveform(sample_rate, audio)
        engine.decode_stream(stream)
        stream.result.text / .tokens / .timestamps
    """

    FRAME_SEC = FRAME_SEC

    def __init__(self, config: QwenCTCConfig, logger: Optional[Logger] = None):
        self.config = config
        self.logger = logger if logger is not None else default_logger
        self._enc = None
        self._ctc = None
        self.id2bytes: Dict[int, bytes] = {}

    # ── 初始化 ────────────────────────────────────────────────────────
    def initialize(self) -> "QwenCTCEngine":
        """加载 ONNX 会话、特征提取器与紧凑词表"""
        import onnxruntime as ort

        providers = resolve_providers(ort, self.config.provider)

        so = ort.SessionOptions()
        so.intra_op_num_threads = self.config.num_threads or 0
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._ctc = ort.InferenceSession(
            self.config.ctc_onnx_path,
            sess_options=so,
            providers=providers,
        )
        # 编码器（含 WhisperFeatureExtractor 的惰性 import）统一走 encoder.py
        self._enc = FusedEncoder(
            self.config.encoder_onnx_path,
            self.config.preprocessor_path,
            num_threads=self.config.num_threads,
            provider=self.config.provider,
            mel_frames=self.config.mel_frames,
            logger=self.logger,
        )
        self.id2bytes = load_tokens(self.config.tokens_path)

        self.logger.info(
            f"Qwen3-CTC 引擎载入完成: encoder={Path(self.config.encoder_onnx_path).name}, "
            f"ctc={Path(self.config.ctc_onnx_path).name}, "
            f"vocab={len(self.id2bytes)}, encoder_dim={self._enc.output_dim}, "
            f"providers={providers}"
        )
        return self

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

    # ── 公开 API ──────────────────────────────────────────────────────
    def decode(self, audio: np.ndarray) -> RecognitionResult:
        """
        识别一段音频（任意长度，内部按 30 秒切段）

        Args:
            audio: float32 单声道 16kHz 波形

        Returns:
            RecognitionResult（text / tokens / timestamps）
        """
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        seg_len = int(SEGMENT_SEC * 16000)

        all_tokens: List[str] = []
        all_timestamps: List[float] = []
        text_parts: List[str] = []

        for i, start in enumerate(range(0, max(len(audio), 1), seg_len)):
            chunk = audio[start : start + seg_len]
            if chunk.size == 0:
                break
            offset = i * SEGMENT_SEC
            enc = self._encode(chunk)
            kept = self._collapse(self._ctc_ids(enc))
            chunk_text, tokens, timestamps = self._decode_kept(kept, offset)
            text_parts.append(chunk_text)
            all_tokens += tokens
            all_timestamps += timestamps

        return RecognitionResult(
            text="".join(text_parts), tokens=all_tokens, timestamps=all_timestamps
        )

    def create_stream(self) -> RecognitionStream:
        """创建识别流（兼容 sherpa-onnx API）"""
        return RecognitionStream(sample_rate=16000)

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
                f"Qwen3-CTC 解码耗时 {elapsed:.3f}s, "
                f"{len(result.tokens)} tokens, 文本 {result.text[:50]!r}"
            )
        return stream.result

    def transcribe(self, audio: np.ndarray) -> RecognitionResult:
        """识别音频（便捷接口）"""
        return self.decode(audio)

    def cleanup(self) -> None:
        """释放资源"""
        if self._enc is not None:
            self._enc.close()
        self._enc = None
        self._ctc = None
        self.id2bytes = {}


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
) -> QwenCTCEngine:
    """便捷构造：返回已初始化的引擎"""
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
        ),
        logger=logger,
    )
    return engine.initialize()
