import re
import time
from typing import Optional

import numpy as np
from loguru import logger as default_logger  # 备用 logger
from loguru._logger import Logger

from util.config import ServerConfig as Config
from util.server.chinese_itn import chinese_to_num
from util.server.classes import Result, Task
from util.server.format_tools import adjust_space

results = {}


def clear_results_by_socket_id(socket_id: str) -> int:
    """
    清理指定 socket 关联的所有任务结果缓存。

    当客户端连接断开时调用，防止中途断开遗留的结果缓存泄漏/陈旧（backport bc74275）。
    """
    stale = [task_id for task_id, r in results.items() if r.socket_id == socket_id]
    for task_id in stale:
        results.pop(task_id, None)
    return len(stale)


def format_text(text, punc_model):
    if Config.format_spell:
        text = adjust_space(text)  # 调空格
    if Config.format_punc and punc_model and text:
        text = punc_model.add_punctuation(text)  # 加标点
    if Config.format_num:
        text = chinese_to_num(text)  # 转数字
    if Config.format_spell:
        text = adjust_space(text)  # 调空格
    return text


def recognize(recognizer, punc_model, task: Task, logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    _logger.trace(f"开始识别任务: {task.task_id}")
    # inspect({key:value for key, value in task.__dict__.items() if not key.startswith('_') and key != 'data'})
    # todo 清空遗存的任务结果

    # 确保结果容器存在
    if task.task_id not in results:
        results[task.task_id] = Result(task.task_id, task.socket_id, task.source)

    # 取出结果容器
    result = results[task.task_id]

    # 片段预处理
    samples = np.frombuffer(task.data, dtype=np.float32)
    duration = len(samples) / task.samplerate
    result.duration += duration - task.overlap
    if task.is_final:
        result.duration += task.overlap

    # 识别片段
    stream = recognizer.create_stream()
    stream.accept_waveform(task.samplerate, samples)
    try:
        recognizer.decode_stream(stream)
    except Exception:  # What's the Fuck? 😵 ValueError('string too long')
        # print(f"识别出错，任务ID：{task.task_id}，错误信息：{e}")
        task.is_final = True  # This can fix 'string too long', I don't know why. 🤣
        return result

    # 记录识别时间
    result.time_start = task.time_start
    result.time_submit = task.time_submit
    result.time_complete = time.time()

    # 先粗去重，依据：字级时间戳
    m = n = len(stream.result.timestamps)
    for i, timestamp in enumerate(stream.result.timestamps, start=0):
        if timestamp > task.overlap / 2:
            m = i
            break
    for i, timestamp in enumerate(stream.result.timestamps, start=1):
        n = i
        if timestamp > duration - task.overlap / 2:
            break
    if not result.timestamps:
        m = 0
    if task.is_final:
        n = len(stream.result.timestamps)

    # 安全处理 tokens，过滤可能的无效 UTF-8 编码
    new_tokens = []
    new_timestamps = []
    try:
        # 先获取切片的 tokens 和 timestamps
        sliced_tokens = stream.result.tokens[m:n]
        sliced_timestamps = stream.result.timestamps[m:n]

        # 再细去重，依据：在端点是否有重复的字
        if result.tokens and result.tokens[-2:] == sliced_tokens[:2]:
            sliced_tokens = sliced_tokens[2:]
            sliced_timestamps = sliced_timestamps[2:]
        elif result.tokens and result.tokens[-1:] == sliced_tokens[:1]:
            sliced_tokens = sliced_tokens[1:]
            sliced_timestamps = sliced_timestamps[1:]

        # 处理 tokens：bytes 统一按 utf-8 解码
        for token in sliced_tokens:
            if isinstance(token, bytes):
                token = token.decode("utf-8", errors="ignore")
            new_tokens.append(token)

        # 处理 timestamps
        new_timestamps = [t + task.offset for t in sliced_timestamps]
    except (UnicodeDecodeError, UnicodeError) as e:
        # 出错时使用空列表，避免程序崩溃
        _logger.error(f"编码错误: {e}")
        new_tokens = []
        new_timestamps = []

    # 最后与先前的结果合并
    result.timestamps += new_timestamps
    result.tokens += new_tokens

    # token 合并为文本
    text = " ".join(result.tokens).replace("@@ ", "")
    text = re.sub("([^a-zA-Z0-9]) (?![a-zA-Z0-9])", r"\1", text)

    result.text = text

    if not task.is_final:
        return result

    # 调整文本格式
    result.text = format_text(text, punc_model)

    # 若最后一个片段完成识别，从字典摘取任务
    result = results.pop(task.task_id)
    result.is_final = True

    return result
