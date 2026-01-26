"""
FunASR-GGUF: 混合 ASR 推理引擎

使用 ONNX Runtime (encoder/CTC) + llama.cpp (GGUF decoder) 进行语音识别

API 兼容 sherpa-onnx，可直接替换使用。
"""

import sys

# ==================== 导入主要组件 ====================
from .asr_engine import (
    FunASREngine,
    create_asr_engine,
)
from .nano_dataclass import (
    ASREngineConfig,
    DecodeResult,
    RecognitionResult,
    RecognitionStream,
    Statistics,
    Timings,
    TranscriptionResult,
)

__all__ = [
    # 日志配置
    "logger",
    "setup_logging",
    # 引擎
    "FunASREngine",
    "create_asr_engine",
    # 结果类型
    "RecognitionResult",
    "RecognitionStream",
    "TranscriptionResult",
    "DecodeResult",
    # 配置和统计
    "Timings",
    "ASREngineConfig",
    "Statistics",
]
