# coding: utf-8
"""
Qwen3-ASR + CTC 头 识别引擎包

对外只暴露三样东西：
    - QwenCTCEngine / create_qwen_ctc_engine：推理引擎
    - RecognitionStream / RecognitionResult：sherpa-onnx 风格的数据类
    - FRAME_SEC / MEL_FRAMES：帧率与桶大小常量
"""

from .encoder import (
    FusedEncoder,
    SplitEncoder,
    resolve_providers,
    valid_frames,
)
from .engine import (
    DEFAULT_END_BIAS,
    DEFAULT_START_BIAS,
    FRAME_RATE_HZ,
    FRAME_SEC,
    MEL_FRAMES,
    SEGMENT_SEC,
    QwenCTCConfig,
    QwenCTCEngine,
    create_qwen_ctc_engine,
)
from .schema import RecognitionResult, RecognitionStream
from .tokens import decode_bytes, load_tokens

__all__ = [
    "DEFAULT_END_BIAS",
    "DEFAULT_START_BIAS",
    "FRAME_RATE_HZ",
    "FRAME_SEC",
    "MEL_FRAMES",
    "SEGMENT_SEC",
    "FusedEncoder",
    "QwenCTCConfig",
    "QwenCTCEngine",
    "RecognitionResult",
    "RecognitionStream",
    "SplitEncoder",
    "create_qwen_ctc_engine",
    "decode_bytes",
    "load_tokens",
    "resolve_providers",
    "valid_frames",
]
