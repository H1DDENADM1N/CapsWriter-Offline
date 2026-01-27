# coding: utf-8
"""
语音识别处理模块

处理音频片段的识别、去重和拼接。支持两种拼接策略：
1. text (简单拼接): 基于文本重叠匹配，不依赖时间戳
2. text_accu (精确拼接): 基于时间戳去重，用于字幕生成
"""

import os

# 设置环境变量以解决 OpenMP 冲突
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import re
import time

import numpy as np
from loguru import logger

from util.config import ServerConfig as Config
from util.safe_logger import init_logging
from util.server.chinese_itn import chinese_to_num
from util.server.classes import Result, Task
from util.server.cosmic import console
from util.server.format_tools import adjust_space

# 导入拆分出去的模块
from util.server.text_merge import (
    merge_by_text,
    merge_tokens_by_sequence_matcher,
    process_tokens_safely,
    tokens_to_text,
)

init_logging()

# 任务结果缓存（按 task_id 索引）
_results = {}


def format_text(text: str) -> str:
    """
    格式化识别文本

    Args:
        text: 原始识别文本

    Returns:
        格式化后的文本
    """
    if text and Config.format_spell:
        text = adjust_space(text)
    if text and Config.format_num:
        text = chinese_to_num(text)
    return text


def _process_simple_merge(result: Result, stream_result_text: str) -> None:
    """
    处理简单文本拼接（主要输出，用于语音输入）

    Args:
        result: 当前结果对象
        stream_result_text: 当前片段的识别文本
    """
    try:
        # 清理文本：去除 @@ 标记和多余空格
        segment_text = stream_result_text.replace("@@", "").strip()
        segment_text = re.sub(r"\s+", " ", segment_text)

        prev_len = len(result.text)
        result.text = merge_by_text(result.text, segment_text)
        added_chars = len(result.text) - prev_len

        logger.debug(
            f"简单拼接: +{added_chars} 字符, "
            f"片段={len(segment_text)}, 总={len(result.text)}"
        )

    except Exception as e:
        logger.warning(f"简单文本拼接失败: {e}")


def validate_audio_samples(samples, task):
    """
    验证音频样本的有效性，防止传入无效数据给识别器

    Args:
        samples: 音频样本数组
        task: 任务对象

    Returns:
        tuple: (is_valid, processed_samples) 或 (False, None)
    """
    # 检查样本是否为空
    if samples is None or len(samples) == 0:
        # console.print(f"任务 {task.task_id[:8]} 音频样本为空，跳过识别")
        # logger.warning(f"任务 {task.task_id[:8]} 音频样本为空，跳过识别")
        return False, None

    # # 检查样本类型
    # if samples.dtype != np.float32:
    #     console.print(f"任务 {task.task_id[:8]} 音频样本类型不是 float32，将进行转换")
    #     logger.debug(f"任务 {task.task_id[:8]} 音频样本类型不是 float32，将进行转换")
    #     samples = samples.astype(np.float32)

    # # 检查特殊值
    # if np.any(np.isnan(samples)) or np.any(np.isinf(samples)):
    #     console.print(f"任务 {task.task_id[:8]} 音频样本包含特殊值，将进行清理")
    #     logger.debug(f"任务 {task.task_id[:8]} 音频样本包含特殊值，将进行清理")
    #     samples = np.nan_to_num(samples, nan=0.0, posinf=1e-6, neginf=-1e-6)

    # # 检查音频长度
    # min_samples = 160  # 至少10ms @ 16kHz
    # if len(samples) < min_samples:
    #     console.print(
    #         f"任务 {task.task_id[:8]} 音频样本过短 (len={len(samples)})，将进行填充"
    #     )
    #     logger.debug(
    #         f"任务 {task.task_id[:8]} 音频样本过短 (len={len(samples)})，将进行填充"
    #     )
    #     # 填充到最小长度
    #     padding_needed = min_samples - len(samples)
    #     samples = np.pad(
    #         samples, (0, padding_needed), mode="constant", constant_values=0
    #     )

    return True, samples


def recognize(recognizer, task: Task) -> Result:
    """
    识别单个音频片段并更新结果

    这是识别流程的主入口，处理以下步骤：
    1. 解码音频并运行识别
    2. 简单文本拼接（text 字段）
    3. 时间戳拼接（text_accu 字段）
    4. 最终格式化（如果是最后一个片段）

    Args:
        recognizer: sherpa-onnx 识别器实例
        task: 识别任务

    Returns:
        识别结果
    """
    try:
        # 1. 初始化/获取结果容器
        is_first_segment = task.task_id not in _results
        if is_first_segment:
            _results[task.task_id] = Result(task.task_id, task.socket_id, task.source)
            logger.debug(f"新任务: {task.task_id[:8]}...")

        result = _results[task.task_id]

        # 2. 解码音频
        samples = np.frombuffer(task.data, dtype=np.float32)
        duration = len(samples) / task.samplerate
        result.duration += duration - task.overlap
        if task.is_final:
            result.duration += task.overlap

        logger.debug(
            f"识别片段: task={task.task_id[:8]}, duration={duration:.2f}s, "
            f"offset={task.offset:.2f}s, is_final={task.is_final}"
        )

        # 3. 音频样本验证 - 在传递给识别器之前
        is_valid, processed_samples = validate_audio_samples(samples, task)
        if not is_valid:
            # 如果验证失败，返回空结果
            logger.debug(f"任务 {task.task_id[:8]} 音频验证失败，返回空结果")
            # 返回一个带有基本信息的结果对象
            result.text = ""
            result.text_accu = ""
            result.tokens = []
            result.timestamps = []
            return result
        else:
            samples = processed_samples  # 获取可能经过处理的samples

        # 4. 执行识别
        stream = recognizer.create_stream()
        stream.accept_waveform(task.samplerate, samples)

        # 在 decode_stream 之前添加额外的防御措施
        try:
            recognizer.decode_stream(stream)
        except Exception as decode_error:
            logger.error(f"解码流时发生错误: {decode_error}")
            # 返回空结果而不是让程序崩溃
            result.text = ""
            result.text_accu = ""
            result.tokens = []
            result.timestamps = []
            return result

        # 更新时间戳
        result.time_start = task.time_start
        result.time_submit = task.time_submit
        result.time_complete = time.time()

        # 5. 简单文本拼接
        _process_simple_merge(result, stream.result.text)

        # 6. 时间戳拼接（使用 SequenceMatcher 策略）
        try:
            # 安全处理当前片段的 tokens
            new_tokens = process_tokens_safely(stream.result.tokens)
            new_timestamps = list(stream.result.timestamps)

            # 使用 SequenceMatcher 进行精确拼接
            result.tokens, result.timestamps = merge_tokens_by_sequence_matcher(
                prev_tokens=result.tokens,
                prev_timestamps=result.timestamps,
                new_tokens=new_tokens,
                new_timestamps=new_timestamps,
                offset=task.offset,
                overlap=task.overlap,
                is_first_segment=is_first_segment,
            )

            logger.debug(f"时间戳拼接完成: 总 {len(result.tokens)} tokens")

        except (UnicodeDecodeError, UnicodeError) as e:
            console.print(f"\n[red]编码错误: {e}")

        # 7. 生成 text_accu
        result.text_accu = tokens_to_text(result.tokens)

        # 如果不是最终结果，直接返回
        if not task.is_final:
            logger.debug(f"中间结果: {result.text[:30]}...")
            return result

        # 8. 最终处理
        result.text = format_text(result.text)
        result.text_accu = format_text(result.text_accu)

        # 如果模型不支持时间戳，用简单拼接结果回退
        if not result.tokens and result.text:
            result.text_accu = result.text
            # 生成粗略的字级时间戳（均匀分布）
            chars = list(result.text_accu.replace(" ", ""))
            if chars and result.duration > 0:
                time_per_char = result.duration / len(chars)
                result.tokens = chars
                result.timestamps = [i * time_per_char for i in range(len(chars))]
                logger.warning(
                    f"模型无时间戳，使用粗略估计: {len(chars)} 字符, {result.duration:.2f}s"
                )

        result = _results.pop(task.task_id)
        result.is_final = True

        process_time = result.time_complete - task.time_submit
        rtf_value = process_time / result.duration if result.duration > 0 else 0
        logger.info(
            f"识别完成: task={task.task_id[:8]}, "
            f"duration={result.duration:.2f}(s), "
            f"process_time={process_time:.3f}(s), "
            f"RTF={rtf_value:.3f}"
        )
        logger.debug(f"最终文本: {result.text[:100]}...")

        return result

    except Exception as e:
        logger.error(f"识别错误: {e}", exc_info=True)
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
