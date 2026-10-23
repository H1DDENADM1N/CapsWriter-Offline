# coding: utf-8
"""
Qwen3-ASR + CTC 头 语音识别处理模块

与 util/server/recognize_funasr.py 一样，遵循 sherpa-onnx 的接口约定：
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, samples)
    recognizer.decode_stream(stream)
    stream.result.text / .tokens / .timestamps

差异点（前 3 条按 `recognizer.mode` / `has_timestamps` 区分三种引擎模式，后 2 条是三模式共有的约束）：
1. 纯 CTC（`ctc`）：CTC 头**没有标点**，输出纯文本 + 字级时间戳。标点由服务端
   复用的 sherpa-onnx 标点模型补齐（与 Paraformer 共用 ModelPaths.punc_model_dir，
   仅在 Config.format_punc 打开时加载）。
2. 两遍（`two_pass`）：文本来自 LLM 二遍（自带标点），tokens 是 LLM 文本的逐
   字符、timestamps 是 NW 对齐结果，两者天然等长，所以仍走 token 级拼接；
   但最终格式化**不能**再过标点模型（否则出现 `。。`）。
3. 纯 LLM（`llm`）：引擎只给文本、**没有** token / 时间戳，拼接改用
   util.server.recognize_funasr.merge_by_text，同样绝不过标点模型，也不伪造
   时间戳。
4. Qwen3 的 token 是**单字符**粒度（与 util/fun_asr_gguf 的 CTC 对齐结果
   一致），所以 `"".join(tokens) == text` 恒成立。
5. 缓存（`_results`）有两套语义：token 模式缓存 tokens/timestamps/text，
   text 模式只缓存 text。切模式时不能让 `"".join(空 tokens)` 把已有 text
   抹成空串。
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
from util.qwen_ctc.engine import MODE_CTC
from util.server.chinese_itn import chinese_to_num
from util.server.classes import Result, Task
from util.server.format_tools import adjust_space
from util.server.recognize_funasr import (
    merge_by_text,
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


def format_text(text: str, punc_model=None, use_punc: bool = True) -> str:
    """
    格式化识别文本（加标点、数字归一化与中英文间距调整）

    Args:
        text: 原始识别文本
        punc_model: sherpa-onnx 标点模型（Qwen3 的 CTC 头本身不产标点）
        use_punc: 是否允许调用标点模型。两遍 / 纯 LLM 的文本由 LLM 生成、
            自带标点，传 False 只跳过 `add_punctuation`，前后两个
            `adjust_space` 与 `chinese_to_num` 照旧；纯 CTC 传 True
            （最终是否真的调用还取决于 Config.format_punc）

    Returns:
        格式化后的文本
    """
    if text and Config.format_spell:
        text = adjust_space(text)
    if text and use_punc and Config.format_punc and punc_model:
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
    2. 拼接：有 token 的引擎（纯 CTC / 两遍）走 token 级拼接，
       无 token 的引擎（纯 LLM）走 merge_by_text 文本拼接
    3. 最终格式化（最后一个片段；两遍 / 纯 LLM 跳过标点模型）

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

        # 4. 拼接（按引擎能力分两支）
        #
        # 有 token（纯 CTC / 两遍）：Qwen3 的 token 是**单字符**，
        # `"".join(tokens) == text` 恒成立。以 token 级拼接
        # （merge_tokens_by_sequence_matcher，SequenceMatcher 全序列对齐）
        # 的结果为准，text 直接由合并后的 token 拼出来。
        # 两遍模式里 tokens 是 LLM 文本的逐字符、timestamps 是 NW 对齐结果，
        # 长度天然相等，照同一套逻辑走即可。
        #
        # 无 token（纯 LLM）：只能用 merge_by_text 做文本重叠拼接，且**不**伪造
        # token / 时间戳。
        if recognizer.has_timestamps:
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

            # 缓存可能来自 text 模式（tokens 空、text 有内容）：`"".join([])`
            # 会把已有文本抹成空串，切模式时绝不能这样丢字。
            joined = "".join(result.tokens)
            if joined or not result.text:
                result.text = joined
        else:
            # 已知限制（纯 LLM 模式的取舍）：merge_by_text 的重叠搜索窗口只有
            # TextMerge.OVERLAP_CHARS(=5) 个字符。中文短重叠（3-4 字）与英文
            # ≤16 字符的重叠都能正确合并；但英文长句的片段重叠往往超过 5 个
            # 字符，此时找不到重叠、整段会重复一遍（实测：
            # "the transcription was accurate and fast" +
            # "accurate and fast in most cases" →
            # "…accurate and fastaccurate and fast in most cases"）。
            # 纯 LLM 模式既没有 token 也没有时间戳，没有更可靠的拼接依据，
            # 这里宁可重复也不丢字 —— 这是刻意接受的退化，不是 bug。
            result.text = merge_by_text(
                result.text, stream.result.text, logger=_logger
            )
            result.tokens = []
            result.timestamps = []

        # 5. 生成 text_accu（两种模式都与 text 保持一致）
        result.text_accu = result.text

        if not task.is_final:
            _logger.debug(f"中间结果: {result.text[:30]}...")
            return result

        # 6. 最终处理
        #
        # 两遍 / 纯 LLM 的文本由 LLM 生成、自带标点，再过标点模型会出 `。。`，
        # 所以只有纯 CTC 才允许加标点（是否真加仍由 Config.format_punc 决定）。
        use_punc = recognizer.mode == MODE_CTC
        result.text = format_text(result.text, punc_model, use_punc=use_punc)
        result.text_accu = format_text(result.text_accu, punc_model, use_punc=use_punc)
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
