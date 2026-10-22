# coding: utf-8
"""
CTC 字级时间戳 → LLM 二遍文本对齐

两遍引擎里两遍输出的**文本并不相同**：CTC 首遍给出的是逐字 tokens（每个 token 通常
就是一个汉字/字母/数字/标点）加上与之 1:1 的**精确**起始时间；LLM 二遍会把错字改掉、
补上标点、偶尔增删字，产出一段自由文本。字幕需要的却是「LLM 文本里每个字符从什么时候
开始说」，于是要把 CTC 的时间戳搬到 LLM 的字符上。

做法是 Needleman-Wunsch 全局比对（`gap -1.0 / match +1.0 / mismatch -1.0`），
比较前做 `NFKC + casefold` 归一（全角 `Ａ` / 半角 `a` 都能和 `A` 对上）：

1. 回溯得到每个 LLM 字符对应的 CTC 下标（对角线 = 锚点，含「错位但仍算对齐」的
   不匹配对 —— 分值相同即视为同一位置，这样整段都被 LLM 改写时仍有时间可用）；
2. 两侧都有锚点的缺口，在两个锚点之间**线性插值**；
3. LLM 在前面多出来的字符，从第一个锚点按平均字距**向前外推**；末尾多出来的字符
   向后外推，并夹到 CTC 的最大起始时间（首尾都落在 CTC 时间范围内）；
4. 整段没有任何锚点（CTC 为空）时按 `i * duration / len(text)` 均分；
5. 最后统一夹到 `[0, max(ctc_starts)]` 并做一次「单调不减」修正 —— 任何输入形态
   （空文本 / 空 CTC / 长度悬殊 / 全不匹配 / 中英混排）都返回长度严格等于
   `len(text)`、单调不减的列表，不抛异常。

为什么不用 `util/fun_asr_gguf/nano_ctc.py::align_timestamps`：那里拿到的 CTC 结果是
**每个 token 一段文本**，只能按固定 0.08 s 硬展开成字；而这里上游已经是逐字 tokens +
真实时间戳，硬展开会凭空引入误差。本模块不 import 那个包的任何东西。
"""

import unicodedata
from typing import List, Sequence

__all__ = ["align_ctc_to_llm"]

# Needleman-Wunsch 分值（brief 固定取值，不要随手调）
MATCH_SCORE = 1.0
MISMATCH_SCORE = -1.0
GAP_SCORE = -1.0

# 前缀/后缀只能单侧外推时，字距不可得的兜底值（秒）
DEFAULT_CHAR_SEC = 0.08

# 回溯矩阵取值：1=对角线（CTC 与 LLM 各消耗一个字符）、2=上（CTC 多一个字符）、
# 3=左（LLM 多一个字符，没有锚点）
_DIAG, _UP, _LEFT = 1, 2, 3


def _norm(ch: str) -> str:
    """比较用的归一化：全角转半角 + 大小写折叠"""
    return unicodedata.normalize("NFKC", ch).casefold()


def _mean_step(starts: Sequence[float]) -> float:
    """CTC 字与字之间的平均间隔，用作单侧外推的步长"""
    if len(starts) < 2:
        return DEFAULT_CHAR_SEC
    step = (float(starts[-1]) - float(starts[0])) / (len(starts) - 1)
    return step if step > 0 else DEFAULT_CHAR_SEC


def align_ctc_to_llm(
    ctc_chars: Sequence[str],
    ctc_starts: Sequence[float],
    llm_text: str,
    duration: float,
) -> List[float]:
    """
    把 CTC 字级起始时间对齐到 LLM 文本的每个字符上。

    Args:
        ctc_chars: CTC 首遍的逐字 tokens（通常每项一个汉字/字母/数字/标点）。
        ctc_starts: 与 ``ctc_chars`` 一一对应的起始时间（秒，单调不减）。
        llm_text: LLM 二遍输出的自由文本（含空格与标点）。
        duration: 音频时长（秒）。只在 CTC 为空、需要均分时用到。

    Returns:
        长度严格等于 ``len(llm_text)`` 的起始时间（秒），单调不减。
    """
    llm_chars = list(llm_text)
    n_llm = len(llm_chars)
    if n_llm == 0:
        return []

    # 上游契约是 1:1；真拿到长度不一致时按较短的一侧截断，绝不抛异常
    ctc = [str(c) for c in ctc_chars]
    starts = [float(s) for s in ctc_starts]
    n_ctc = min(len(ctc), len(starts))
    ctc, starts = ctc[:n_ctc], starts[:n_ctc]

    dur = float(duration) if duration else 0.0

    # CTC 为空：没有任何时间信息，按 i * duration / len(text) 均分
    if n_ctc == 0:
        if dur > 0:
            return [i * dur / n_llm for i in range(n_llm)]
        return [0.0] * n_llm

    ctc_norm = [_norm(c) for c in ctc]
    llm_norm = [_norm(c) for c in llm_chars]

    # ---- Needleman-Wunsch：两行滚动分数 + 逐行 bytearray 回溯矩阵 ----
    # 只留两行分数（省内存），回溯矩阵每格 1 字节（1000x1000 也只有 1 MB）。
    # 平局优先对角线，其次「CTC 多字」，最后「LLM 多字」，保证锚点尽量多。
    trace: List[bytearray] = [bytearray(n_llm) for _ in range(n_ctc)]
    prev = [j * GAP_SCORE for j in range(n_llm + 1)]
    for i in range(1, n_ctc + 1):
        cur = [0.0] * (n_llm + 1)
        cur[0] = i * GAP_SCORE
        row = trace[i - 1]
        c_norm = ctc_norm[i - 1]
        for j in range(1, n_llm + 1):
            diag = prev[j - 1] + (
                MATCH_SCORE if c_norm == llm_norm[j - 1] else MISMATCH_SCORE
            )
            best, tb = diag, _DIAG
            up = prev[j] + GAP_SCORE
            if up > best:
                best, tb = up, _UP
            left = cur[j - 1] + GAP_SCORE
            if left > best:
                best, tb = left, _LEFT
            cur[j] = best
            row[j - 1] = tb
        prev = cur

    # ---- 回溯：每个 LLM 字符对应的 CTC 下标（-1 = 没锚点）----
    ctc_index = [-1] * n_llm
    i, j = n_ctc, n_llm
    while i > 0 or j > 0:
        if i > 0 and j > 0 and trace[i - 1][j - 1] == _DIAG:
            ctc_index[j - 1] = i - 1
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or trace[i - 1][j - 1] == _UP):
            i -= 1
        else:
            j -= 1

    anchors = [(j, starts[k]) for j, k in enumerate(ctc_index) if k >= 0]

    if not anchors:
        # 理论上只有 CTC 为空才会走到这里，兜底与空 CTC 同策略，不抛异常
        if dur > 0:
            return [i * dur / n_llm for i in range(n_llm)]
        return [0.0] * n_llm

    step = _mean_step(starts)
    hi = max(starts)
    out = [0.0] * n_llm

    # 锚点本身：原样保留 CTC 的精确起始时间
    for j, t in anchors:
        out[j] = t

    # 相邻锚点之间：线性插值（LLM 补的标点、空格都落在这里）
    for (pj, pt), (nj, nt) in zip(anchors, anchors[1:]):
        span_j = nj - pj
        if span_j <= 1:
            continue
        span_t = nt - pt
        for j in range(pj + 1, nj):
            out[j] = pt + span_t * (j - pj) / span_j

    # 前缀：按平均字距从第一个锚点向前外推；若外推会越过 0，说明 LLM 在前面多出来的
    # 字符比 CTC 能覆盖的还长，退化成「在 [0, 第一个锚点] 里均分」——
    # 否则一连串字会被夹成同一个 0.0，字幕会挤在一起。
    first_j, first_t = anchors[0]
    if first_j > 0:
        if first_t - first_j * step >= 0.0:
            for j in range(first_j):
                out[j] = first_t - (first_j - j) * step
        else:
            for j in range(first_j):
                out[j] = first_t * j / first_j

    # 后缀：同理向后外推；越过 CTC 最大起始时间时退化成「在 [最后一个锚点, 最大值]
    # 里均分」，保证首尾都落在 CTC 时间范围内。
    last_j, last_t = anchors[-1]
    tail = n_llm - 1 - last_j
    if tail > 0:
        if last_t + tail * step <= hi:
            for j in range(last_j + 1, n_llm):
                out[j] = last_t + (j - last_j) * step
        else:
            span = hi - last_t
            for j in range(last_j + 1, n_llm):
                out[j] = last_t + span * (j - last_j) / (n_llm - last_j)

    # 收口：夹到 [0, max(ctc_starts)]，并强制单调不减。
    # 上游虽然承诺单调，但外推/插值再叠加浮点误差仍可能倒挂，这里一次性兜住。
    prev_t = 0.0
    for j in range(n_llm):
        t = out[j]
        if t < 0.0:
            t = 0.0
        elif t > hi:
            t = hi
        if t < prev_t:
            t = prev_t
        out[j] = t
        prev_t = t

    return out
