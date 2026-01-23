import re
import time

import numpy as np
from loguru import logger

from util.config import ServerConfig as Config
from util.server.chinese_itn import chinese_to_num
from util.server.classes import Result, Task
from util.server.format_tools import adjust_space
from util.server.text_merge import (
    calculate_timestamp_boundaries,
    deduplicate_at_boundary,
    merge_by_text,
    process_tokens_safely,
    remove_trailing_punctuation,
    tokens_to_text,
)

results = {}


def format_text(text):
    if Config.format_spell:
        text = adjust_space(text)  # 调空格
    if Config.format_num:
        text = chinese_to_num(text)  # 转数字
    if Config.format_spell:
        text = adjust_space(text)  # 调空格
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
        is_first_segment = task.task_id not in results
        if is_first_segment:
            results[task.task_id] = Result(task.task_id, task.socket_id, task.source)
            logger.debug(f"新任务: {task.task_id[:8]}...")

        result = results[task.task_id]

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

        # 3. 执行识别
        stream = recognizer.create_stream()
        stream.accept_waveform(task.samplerate, samples)
        recognizer.decode_stream(stream)

        # 更新时间戳
        result.time_start = task.time_start
        result.time_submit = task.time_submit
        result.time_complete = time.time()

        # 4. 简单文本拼接
        _process_simple_merge(result, stream.result.text)

        # 5. 时间戳拼接
        try:
            # 计算边界
            start_idx, end_idx = calculate_timestamp_boundaries(
                stream.result.timestamps,
                task.overlap,
                duration,
                is_first_segment,
                task.is_final,
            )

            # 切片
            sliced_tokens = stream.result.tokens[start_idx:end_idx]
            sliced_timestamps = stream.result.timestamps[start_idx:end_idx]

            # 边界去重
            sliced_tokens, sliced_timestamps = deduplicate_at_boundary(
                result.tokens, sliced_tokens, sliced_timestamps
            )

            # 安全处理 tokens
            new_tokens = process_tokens_safely(sliced_tokens)
            new_timestamps = [t + task.offset for t in sliced_timestamps]

            logger.debug(f"时间戳拼接: +{len(new_tokens)} tokens")

        except (UnicodeDecodeError, UnicodeError) as e:
            # save_error_audio(samples, task.task_id, task.samplerate)
            console.print(f"\n[red]编码错误: {e}")
            # console.print('\n[yellow]完整 stream.result:')
            # inspect(stream.result)
            new_tokens = []
            new_timestamps = []

        # 6. 合并 tokens（先移除旧末尾标点）
        result.tokens, result.timestamps = remove_trailing_punctuation(
            result.tokens, result.timestamps
        )
        result.tokens += new_tokens
        result.timestamps += new_timestamps

        # 7. 生成 text_accu
        result.text_accu = tokens_to_text(result.tokens)

        # 如果不是最终结果，直接返回
        if not task.is_final:
            logger.debug(f"中间结果: {result.text[:30]}...")
            return result

        # 8. 最终处理
        result.text = format_text(result.text)
        result.text_accu = format_text(result.text_accu)

        result = results.pop(task.task_id)
        result.is_final = True

        process_time = result.time_complete - task.time_submit
        logger.info(
            f"识别完成: task={task.task_id[:8]}, "
            f"duration={result.duration:.2f}s, "
            f"process_time={process_time:.3f}s"
        )
        logger.debug(f"最终文本: {result.text[:100]}...")

        return result

    except Exception as e:
        logger.error(f"识别错误: {e}", exc_info=True)
        raise
