# coding: utf-8
"""
Qwen3-ASR + CTC 头 的数据类

与服务端其它识别器保持 sherpa-onnx 风格的接口（create_stream /
accept_waveform / decode_stream / stream.result），这样可以复用
util/server/recognize_*.py 里的片段去重与拼接逻辑。

与 util/fun_asr_gguf/nano_dataclass.py 的区别：这里不引入 numpy 之外的
任何依赖，也不与 llama.cpp 耦合——Qwen3-CTC 只有 ONNX 前向，没有 LLM 二遍。
"""

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class RecognitionResult:
    """识别结果：文本 + 字级 token + 字级时间戳"""

    text: str = ""
    timestamps: List[float] = field(default_factory=list)
    tokens: List[str] = field(default_factory=list)


@dataclass
class RecognitionStream:
    """识别流：承载音频样本，识别结果由 decode_stream 写入"""

    sample_rate: int = 16000
    audio_data: Optional[np.ndarray] = None
    _result: Optional[RecognitionResult] = None

    def accept_waveform(self, sample_rate: int, audio: np.ndarray) -> None:
        """接收音频（float32, 单声道）"""
        self.sample_rate = sample_rate
        self.audio_data = np.asarray(audio, dtype=np.float32).reshape(-1)

    @property
    def result(self) -> RecognitionResult:
        if self._result is None:
            self._result = RecognitionResult()
        return self._result

    def set_result(
        self,
        text: str,
        timestamps: Optional[List[float]] = None,
        tokens: Optional[List[str]] = None,
    ) -> None:
        self._result = RecognitionResult(
            text=text,
            timestamps=list(timestamps or []),
            tokens=list(tokens or []),
        )
