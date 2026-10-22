# coding: utf-8
"""
Qwen3-ASR + CTC 头 语音识别处理模块

与 util/server/recognize_funasr.py 一样，遵循 sherpa-onnx 的接口约定：
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, samples)
    recognizer.decode_stream(stream)
    stream.result.text / .tokens / .timestamps

差异点：
1. Qwen3-ASR 的 CTC 头**没有标点**，也不做 LLM 二遍，输出就是纯文本 +
   字级时间戳。标点由服务端复用的 sherpa-onnx 标点模型补齐
   （与 Paraformer 共用 ModelPaths.punc_model_dir，仅在 Config.format_punc
   打开时加载）。
2. Qwen3 的 token 是**单字符**粒度（与 util/fun_asr_gguf 的 CTC 对齐结果
   一致），所以 `"".join(tokens) == text` 恒成立。
3. 拼接用 recognize_funasr 的 token 级 SequenceMatcher 策略（多段长语音
   不会重复或丢字）。因为 token 已经是单字符，text 直接由合并后的 token
   拼出来，两者永远一致。
"""

import os

# 设置环境变量以解决 OpenMP 冲突
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import time
from typing import Optional

import numpy as np
from loguru import logger as default_logger
from loguru._logger import Logger

from util.config import ServerConfig as Config
from util.server.chinese_itn import chinese_to_num
from util.server.classes import Result, Task
from util.server.format_tools import adjust_space
from util.server.recognize_funasr import (
    merge_tokens_by_sequence_matcher,
    process_tokens_safely,
)

# 每个 task_id 对应一个累积中的 Result
_results: dict = {}


def clear_results_by_socket_id(socket_id: str) -> int:
    """
    清理指定连接的所有中间结果

    Args:
        socket_id: 连接标识

    Returns:
        清理的结果数量
    """
    count = 0
    for task_id in list(_results.keys()):
        if _results[task_id].socket_id == socket_id:
            del _results[task_id]
            count += 1
    return count


def format_text(text: str, punc_model=None) -> str:
    """
    格式化识别文本（加标点、数字归一化与中英文间距调整）

    Args:
        text: 原始识别文本
        punc_model: sherpa-onnx 标点模型（Qwen3 的 CTC 头本身不产标点）

    Returns:
        格式化后的文本
    """
    if text and Config.format_spell:
        text = adjust_space(text)
    if text and Config.format_punc and punc_model:
        text = punc_model.add_punctuation(text)
    if text and Config.format_num:
        text = chinese_to_num(text)
    if text and Config.format_spell:
        text = adjust_space(text)
    return text


def recognize(
    recognizer, punc_model=None, task: Task = None, logger: Optional[Logger] = None
) -> Result:
    """
    识别单个音频片段并更新结果

    流程：
    1. 解码音频（引擎内部按 30 秒切段）
    2. 文本拼接（text 字段，主要用于语音输入）
    3. 字级时间戳拼接（text_accu 字段，用于字幕生成）
    4. 最终格式化（最后一个片段）

    Args:
        recognizer: QwenCTCEngine 实例
        punc_model: 标点模型（可为 None，此时不加点）
        task: 识别任务

    Returns:
        识别结果
    """
    _logger = logger if logger is not None else default_logger
    try:
        # 1. 初始化/获取结果容器
        is_first_segment = task.task_id not in _results
        if is_first_segment:
            _results[task.task_id] = Result(task.task_id, task.socket_id, task.source)
            _logger.debug(f"新任务: {task.task_id[:8]}...")

        result = _results[task.task_id]

        # 2. 解码音频
        samples = np.frombuffer(task.data, dtype=np.float32)
        duration = len(samples) / task.samplerate
        result.duration += duration - task.overlap
        if task.is_final:
            result.duration += task.overlap

        _logger.debug(
            f"识别片段: task={task.task_id[:8]}, duration={duration:.2f}s, "
            f"offset={task.offset:.2f}s, is_final={task.is_final}"
        )

        # 3. 执行识别
        stream = recognizer.create_stream()
        stream.accept_waveform(task.samplerate, samples)
        recognizer.decode_stream(stream)

        result.time_start = task.time_start
        result.time_submit = task.time_submit
        result.time_complete = time.time()

        # 4. 文本拼接
        #
        # Qwen3 的 CTC 头输出的是**单字符** token，所以
        # `"".join(tokens) == text` 恒成立。服务端最终以 token 级拼接
        # （merge_tokens_by_sequence_matcher）的结果为准，text 直接由
        # 合并后的 token 拼出来。
        #
        # 这里不再用 merge_by_text：它的重叠搜索窗口只有
        # TextMerge.OVERLAP_CHARS(=5) 个字符，英文长句的片段重叠远大于
        # 5 个字符，会找不到重叠而整段重复（实测 "…we also looked at the
        # difference" 被重复了一遍）。token 级拼接用的是
        # SequenceMatcher 全序列匹配，英文同样正确。

        # 5. 字级时间戳拼接
        try:
            new_tokens = process_tokens_safely(stream.result.tokens)
            new_timestamps = list(stream.result.timestamps)

            result.tokens, result.timestamps = merge_tokens_by_sequence_matcher(
                prev_tokens=result.tokens,
                prev_timestamps=result.timestamps,
                new_tokens=new_tokens,
                new_timestamps=new_timestamps,
                offset=task.offset,
                overlap=task.overlap,
                is_first_segment=is_first_segment,
                logger=_logger,
            )
            _logger.debug(f"时间戳拼接完成: 总 {len(result.tokens)} tokens")
        except (UnicodeDecodeError, UnicodeError) as e:
            _logger.error(f"编码错误: {e}")

        # 6. 生成 text / text_accu
        result.text = "".join(result.tokens)
        result.text_accu = result.text

        if not task.is_final:
            _logger.debug(f"中间结果: {result.text[:30]}...")
            return result

        # 7. 最终处理
        result.text = format_text(result.text, punc_model)
        result.text_accu = format_text(result.text_accu, punc_model)
        result = _results.pop(task.task_id)
        result.is_final = True

        process_time = result.time_complete - task.time_submit
        rtf_value = process_time / result.duration if result.duration > 0 else 0
        _logger.info(
            f"识别完成: task={task.task_id[:8]}, "
            f"duration={result.duration:.2f}(s), "
            f"process_time={process_time:.3f}(s), "
            f"RTF={rtf_value:.3f}"
        )
        _logger.debug(f"最终文本: {result.text[:100]}...")

        return result

    except Exception as e:
        _logger.error(f"识别错误: {e}", exc_info=True)
        # 返回一个空结果而不是让程序崩溃
        if task.task_id in _results:
            empty_result = _results.pop(task.task_id)
        else:
            empty_result = Result(task.task_id, task.socket_id, task.source)
        empty_result.text = ""
        empty_result.text_accu = ""
        empty_result.tokens = []
        empty_result.timestamps = []
        empty_result.is_final = True
        return empty_result
