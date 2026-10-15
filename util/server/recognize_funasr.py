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
from typing import List, Optional, Tuple

import numpy as np
from loguru import logger as default_logger
from loguru._logger import Logger

from util.config import ServerConfig as Config
from util.constants import Punctuation, TextMerge
from util.server.chinese_itn import chinese_to_num
from util.server.classes import Result, Task
from util.server.cosmic import console
from util.server.format_tools import adjust_space


def _fuzzy_match(s1: str, s2: str, max_errors: int) -> bool:
    """
    模糊匹配：允许最多 max_errors 个字符不同

    使用简单的字符比较，允许一定数量的错误。

    Args:
        s1: 字符串1
        s2: 字符串2
        max_errors: 允许的最大错误数

    Returns:
        是否匹配（错误数 <= max_errors）
    """
    if len(s1) != len(s2):
        return False

    errors = sum(1 for c1, c2 in zip(s1, s2) if c1 != c2)
    return errors <= max_errors


def _find_fuzzy_overlap(tail: str, new_text: str, max_errors: int) -> int:
    """
    在 tail 末尾和 new_text 开头寻找模糊重叠

    从长到短尝试匹配，允许 max_errors 个字符错误。

    重要约束：匹配长度必须 > max_errors，否则错误率会超过 50%，
    导致几乎任何内容都能匹配。

    Args:
        tail: prev_text 的末尾部分
        new_text: 新文本
        max_errors: 允许的最大错误数

    Returns:
        匹配长度（0 表示未找到匹配）
    """
    # 最小匹配长度：必须大于容错数，确保正确字符多于错误字符
    min_match_len = max_errors + 2  # 至少比容错多2个字符

    for match_len in range(min(len(tail), len(new_text)), min_match_len - 1, -1):
        tail_part = tail[-match_len:]
        new_part = new_text[:match_len]

        if _fuzzy_match(tail_part, new_part, max_errors):
            return match_len

    return 0


def merge_by_text(
    prev_text: str,
    new_text: str,
    overlap_chars: int = TextMerge.OVERLAP_CHARS,
    error_tolerance: int = TextMerge.ERROR_TOLERANCE,
    logger: Optional[Logger] = None,
) -> str:
    """
    基于文本重叠进行鲁棒拼接

    算法优化：
    不再要求重叠必须在 prev_text 的绝对末尾。
    而是在 prev_text 的末尾窗口内寻找 new_text 的最长匹配前缀。
    如果发现匹配，则以匹配点为界进行拼接，丢弃 prev_text 匹配点之后的“尾部噪音”。

    Args:
        prev_text: 之前累积的文本
        new_text: 新识别的文本
        overlap_chars: 查找重叠的后端窗口大小
        error_tolerance: 容错字符数
    """
    _logger = default_logger if logger is None else logger
    if not prev_text:
        return new_text
    if not new_text:
        return prev_text

    # 1. 预处理：提取用于匹配的纯文本（去掉两端标点）
    prev_clean = prev_text.rstrip(Punctuation.ALL)

    # 记录 new_text 开头被去掉的标点数量，用于最终拼接
    new_match_start = 0
    while (
        new_match_start < len(new_text) and new_text[new_match_start] in Punctuation.ALL
    ):
        new_match_start += 1
    new_clean = new_text[new_match_start:]

    if not prev_clean or not new_clean:
        return prev_text + new_text

    # 2. 确定搜索窗口（prev_text 的末尾部分）
    search_window = prev_clean[-overlap_chars:]
    window_offset = len(prev_clean) - len(search_window)

    # 3. 寻找最长匹配重叠
    # 策略：不仅搜 new_clean 的绝对开头，还允许跳过 new_clean 开头的几个字（处理开头截断不准）
    max_skip_new = 10  # 允许跳过新片段开头的字数
    max_to_check = min(len(search_window), len(new_clean))
    min_exact_len = 2
    min_fuzzy_len = error_tolerance + 2

    best_match_skip_new = -1
    best_match_pos_in_window = -1
    best_match_len = 0

    # 3.1 尝试【精确匹配】
    # 优先级：匹配越长越好 > 跳过越少越好 > 越靠近 prev 尾部越好
    for match_len in range(max_to_check, min_exact_len - 1, -1):
        for skip_new in range(min(max_skip_new, len(new_clean) - match_len + 1)):
            target_prefix = new_clean[skip_new : skip_new + match_len]
            idx = search_window.rfind(target_prefix)
            if idx != -1:
                best_match_skip_new = skip_new
                best_match_pos_in_window = idx
                best_match_len = match_len
                break
        if best_match_len > 0:
            break

    # 3.2 如果没找到精确匹配，且开启了容错，则尝试【模糊匹配】
    if best_match_len == 0 and error_tolerance > 0:
        for match_len in range(max_to_check, min_fuzzy_len - 1, -1):
            for skip_new in range(min(max_skip_new, len(new_clean) - match_len + 1)):
                target_prefix = new_clean[skip_new : skip_new + match_len]
                found_idx = -1
                for i in range(len(search_window) - match_len, -1, -1):
                    if _fuzzy_match(
                        search_window[i : i + match_len], target_prefix, error_tolerance
                    ):
                        found_idx = i
                        break
                if found_idx != -1:
                    best_match_skip_new = skip_new
                    best_match_pos_in_window = found_idx
                    best_match_len = match_len
                    break
            if best_match_len > 0:
                break

    # 4. 执行拼接
    if best_match_len > 0:
        # prev_text 保留到匹配开始的地方
        keep_prev_len = window_offset + best_match_pos_in_window

        # 衔接点：跳过 new_text 开头的标点以及我们认为多余的 skip_new 个噪音字
        res_prev = prev_clean[:keep_prev_len]
        res_new = new_text[new_match_start + best_match_skip_new :]

        discard_prev = len(prev_clean) - keep_prev_len - best_match_len
        _logger.debug(
            f"文本拼接成功: 匹配长度 {best_match_len}, "
            f"丢弃 prev 尾部噪音 {discard_prev} 字, "
            f"跳过 new 开头噪音 {best_match_skip_new} 字"
        )
        return res_prev + res_new

    # 5. 未找到匹配，兜底逻辑
    _logger.debug("文本拼接: 未找到重叠，直接拼接")
    return prev_text + new_text


def _find_best_token_overlap(
    prev_tail: str, new_head: str
) -> Optional[Tuple[int, int, int]]:
    """
    在 prev_tail 和 new_head 之间找最佳对齐（与上游 17706f9 token_merger 相同策略）。

    位置约束：匹配终点在 prev_tail 后半段，匹配起点在 new_head 前半段。
    用 get_matching_blocks 枚举所有公共子串，再加位置约束过滤、按分值取最优，
    避免 find_longest_match 在重叠区长度估算错误时匹配点塌缩到开头。

    Args:
        prev_tail: prev 末尾文本
        new_head: new 开头文本

    Returns:
        (match_pos_prev, match_pos_new, match_len)，找不到则返回 None
    """
    import difflib

    min_match = 2
    sm = difflib.SequenceMatcher(
        None, prev_tail, new_head, autojunk=False
    )
    matches = sm.get_matching_blocks()

    tail_end_threshold = len(prev_tail) // 4 * 3
    head_start_threshold = len(new_head) // 4

    candidates = [
        (a, b, size)
        for a, b, size in matches
        if size >= min_match
        and a + size > tail_end_threshold
        and b <= head_start_threshold
    ]
    if not candidates:
        return None

    def score(item):
        a, b, size = item
        return size * size + a - b

    return max(candidates, key=score)


def _char_pos_to_token_idx(
    tokens: List[str], base_offset: int, char_pos: int
) -> int:
    """
    将字符位置映射回 token 索引（全局，绝对索引）。

    从 base_offset 开始累计字符数，找到第一个 >= char_pos 的 token 边界。
    返回的是原列表的全局索引，可直接用于 prev_tokens[:idx] 切片，保留 idx 之前所有 token。
    """
    char_count = 0
    for i in range(base_offset, len(tokens)):
        if char_count >= char_pos:
            return i
        char_count += len(tokens[i])
    return len(tokens)


def _fallback_merge(
    prev_tokens: List[str],
    prev_timestamps: List[float],
    new_tokens: List[str],
    new_global_timestamps: List[float],
    offset: float,
    logger: Optional[Logger] = None,
) -> Tuple[List[str], List[float]]:
    """
    兜底：基于时间戳硬拼接。

    只在 prev 末尾时间戳之后的 new token 才接入，避免重复追加。
    """
    _logger = logger if logger is not None else default_logger
    last_time = prev_timestamps[-1] if prev_timestamps else offset
    new_start_idx = 0
    for i, t in enumerate(new_global_timestamps):
        if t > last_time + 0.1:
            new_start_idx = i
            break
    else:
        new_start_idx = len(new_tokens)

    result_tokens = prev_tokens + new_tokens[new_start_idx:]
    result_timestamps = prev_timestamps + new_global_timestamps[new_start_idx:]

    _logger.debug(f"时间戳兜底拼接: 从 new[{new_start_idx}] 开始")
    return result_tokens, result_timestamps


def _clean_repeated_punct(
    tokens: List[str], timestamps: List[float]
) -> Tuple[List[str], List[float]]:
    """清理连续重复标点"""
    from util.constants import Punctuation

    puncs = set(Punctuation.ALL + " ")
    clean_tokens = []
    clean_timestamps = []
    for token, ts in zip(tokens, timestamps):
        if clean_tokens and token in puncs and clean_tokens[-1] == token:
            continue
        clean_tokens.append(token)
        clean_timestamps.append(ts)
    return clean_tokens, clean_timestamps


def merge_tokens_by_sequence_matcher(
    prev_tokens: List[str],
    prev_timestamps: List[float],
    new_tokens: List[str],
    new_timestamps: List[float],
    offset: float,
    overlap: float,
    is_first_segment: bool = False,
    logger: Optional[Logger] = None,
) -> Tuple[List[str], List[float]]:
    """
    使用 SequenceMatcher 进行精确的 token 级别拼接

    算法（移植上游 17706f9 token_merger 修复）：
    1. 基于 overlap 秒数估算重叠区字符数（overlap * 约5字/秒），
       取 prev 尾部、new 头部文本，不再用时间戳过滤重叠区。
       （旧实现混用 prev 全局时间戳与 new 相对时间戳，导致重叠区
       提取错误：prev 被切、new 几乎全留 → 重复文本 + 塌缩时间戳）
    2. 用 get_matching_blocks + 位置约束选最佳对齐
    3. 用字符位置→全局 token 索引的映射，在匹配终点处切 prev / new。
       关键：prev 用绝对索引切片 prev_tokens[:prev_cut]，
       完整保留匹配点之前的所有已累积 token（修复多段累积丢文本回归）。

    Args:
        prev_tokens: 之前累积的 tokens
        prev_timestamps: 之前累积的时间戳（全局时间）
        new_tokens: 新片段的 tokens
        new_timestamps: 新片段的时间戳（片段内相对时间）
        offset: 当前片段的全局起始偏移
        overlap: 重叠时间（秒）
        is_first_segment: 是否为第一个片段

    Returns:
        (合并后的 tokens, 合并后的时间戳)
    """
    _logger = logger if logger is not None else default_logger

    # 转换新片段时间戳为全局时间
    new_global_timestamps = [t + offset for t in new_timestamps]

    # 如果是第一个片段，直接返回
    if is_first_segment or not prev_tokens:
        return new_tokens, new_global_timestamps

    if not new_tokens:
        return prev_tokens, prev_timestamps

    # 1. 提取 prev 尾部和 new 头部的文本（基于 overlap 动态确定范围）
    #    重叠区域的字符数估计：overlap 秒 × 约 5 字/秒
    overlap_char_estimate = max(int(overlap * 5), 20)
    prev_tail_len = min(len(prev_tokens), overlap_char_estimate * 3)
    new_head_len = min(len(new_tokens), overlap_char_estimate * 3)

    prev_tail_text = "".join(prev_tokens[-prev_tail_len:])
    new_head_text = "".join(new_tokens[:new_head_len])

    # 2. 寻找最佳对齐（带位置约束）
    best = _find_best_token_overlap(prev_tail_text, new_head_text)

    if best is None:
        _logger.debug("Token 拼接: 未找到重叠，直接拼接")
        return _fallback_merge(
            prev_tokens,
            prev_timestamps,
            new_tokens,
            new_global_timestamps,
            offset,
            logger,
        )

    match_pos_prev, match_pos_new, match_len = best

    # 3. 将字符位置映射回【全局 token 索引】，执行拼接
    #    prev 保留到匹配终点（match_pos_prev + match_len）
    #    new 从匹配终点（match_pos_new + match_len）之后开始
    #    prev_cut / new_start 是原列表的绝对索引：
    #    prev_tokens[:prev_cut] 保留包括匹配终点在内的全部前缀，
    #    不会丢弃匹配之前的累积文本。
    prev_cut = _char_pos_to_token_idx(
        prev_tokens,
        len(prev_tokens) - prev_tail_len,
        match_pos_prev + match_len,
    )
    new_start = _char_pos_to_token_idx(
        new_tokens, 0, match_pos_new + match_len
    )

    result_tokens = prev_tokens[:prev_cut] + new_tokens[new_start:]
    result_timestamps = prev_timestamps[:prev_cut] + new_global_timestamps[new_start:]

    _logger.debug(
        f"Token 拼接: 匹配长度 {match_len}, "
        f"prev 截断 token[{prev_cut}], new 起始 token[{new_start}]"
    )

    # 4. 后处理：清理连续重复标点
    return _clean_repeated_punct(result_tokens, result_timestamps)


def process_tokens_safely(tokens: List) -> List[str]:
    """
    安全处理 tokens，过滤无效 UTF-8 编码

    Args:
        tokens: 原始 token 列表

    Returns:
        清理后的字符串 token 列表
    """
    clean_tokens = []
    for token in tokens:
        if isinstance(token, bytes):
            token = token.decode("utf-8", errors="ignore")
        clean_tokens.append(token)
    return clean_tokens


# 任务结果缓存（按 task_id 索引）
_results = {}


def clear_results_by_socket_id(socket_id: str) -> int:
    """
    清理指定 socket 关联的所有任务结果缓存。

    当客户端连接断开时调用，防止中途断开遗留的结果缓存泄漏/陈旧（backport bc74275）。
    """
    stale = [task_id for task_id, r in _results.items() if r.socket_id == socket_id]
    for task_id in stale:
        _results.pop(task_id, None)
    return len(stale)


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


def _process_simple_merge(
    result: Result, stream_result_text: str, logger: Optional[Logger] = None
) -> None:
    """
    处理简单文本拼接（主要输出，用于语音输入）

    Args:
        result: 当前结果对象
        stream_result_text: 当前片段的识别文本
    """
    _logger = logger if logger is not None else default_logger
    try:
        # 清理文本：去除多余空格
        segment_text = stream_result_text.strip()
        segment_text = re.sub(r"\s+", " ", segment_text)

        prev_len = len(result.text)
        result.text = merge_by_text(result.text, segment_text, logger=_logger)
        added_chars = len(result.text) - prev_len

        _logger.debug(
            f"简单拼接: +{added_chars} 字符, "
            f"片段={len(segment_text)}, 总={len(result.text)}"
        )

    except Exception as e:
        _logger.warning(f"简单文本拼接失败: {e}")


def recognize(recognizer, task: Task, logger: Optional[Logger] = None) -> Result:
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

        # 更新时间戳
        result.time_start = task.time_start
        result.time_submit = task.time_submit
        result.time_complete = time.time()

        # 4. 简单文本拼接
        _process_simple_merge(result, stream.result.text, logger=_logger)

        # 5. 时间戳拼接（使用 SequenceMatcher 策略）
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
                logger=_logger,
            )

            _logger.debug(f"时间戳拼接完成: 总 {len(result.tokens)} tokens")

        except (UnicodeDecodeError, UnicodeError) as e:
            console.print(f"\n[red]编码错误: {e}")

        # 6. 生成 text_accu
        result.text_accu = "".join(result.tokens)

        # 如果不是最终结果，直接返回
        if not task.is_final:
            _logger.debug(f"中间结果: {result.text[:30]}...")
            return result

        # 7. 最终处理
        result.text = format_text(result.text)
        result.text_accu = format_text(result.text_accu)
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
