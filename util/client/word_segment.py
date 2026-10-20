"""中文分词：在文本里定位「光标所在的那个词」。

文本框的 Ctrl+D（选中光标下的词）、Ctrl+Shift+L（选中所有相同内容）
与双击选词都依赖它。

为什么不用 Qt 自带的 ``StartOfWord``/``EndOfWord``：
Qt 把**一整段连续汉字当作一个词**——

    StartOfWord..EndOfWord 在「语音输入测试字符串」上选中 9 个字

用户期望的却是按词典分词后的「语音输入」。于是这里用 jieba 做中文分词。

为什么不能把整件事都交给 jieba：
jieba 是通用分词器，它会把 ``foo_bar`` 切成 ``foo`` / ``_`` / ``bar``
三段，而文本框里 ``foo_bar`` 是一个完整的标识符。所以分工是：

- **ASCII**（字母/数字/下划线）→ 走本模块自己的字符规则，与 Qt 的
  词边界语义一致；
- **汉字** → 走 jieba 词典分词。

位置约定（沿用文本框既有的 ``_word_range_at`` 语义，不另立规矩）：

1. 光标位置上的字符是词字符 → 选**它**所在的词；
2. 光标位置上是分隔符（空白/标点）→ 回退到光标**左边**那个字符，
   若左边也是分隔符则没有词（返回 None）。

第 2 条让「刚打完一个词，光标停在词尾」时仍能选到刚写的那个词。
"""

from __future__ import annotations

import warnings
from typing import Optional

__all__ = ["is_cjk", "word_range_at"]


# 汉字区段（CJK Unified Ideographs 及扩展 A）。
#
# 只覆盖**汉字**而不含全角标点：标点是词边界，不参与组词。
# 全角标点（U+FF01-FF65）与中文标点（U+3000-303F）都在标点区段，
# 天然落在区段之外。
_CJK_START = 0x4E00
_CJK_END = 0x9FFF
_CJK_EXT_A_START = 0x3400
_CJK_EXT_A_END = 0x4DBF


def is_cjk(ch: str) -> bool:
    """该字符是否为汉字。

    汉字区段之外的字符（ASCII、全角标点、中文标点、假名、韩文等）
    一律返回 False——它们要么走 ASCII 词规则，要么是分隔符。
    """
    if not ch:
        return False
    code = ord(ch)
    return (
        _CJK_START <= code <= _CJK_END
        or _CJK_EXT_A_START <= code <= _CJK_EXT_A_END
    )


def _is_ascii_word_char(ch: str) -> bool:
    """ASCII 词内字符：字母、数字、下划线。

    与文本框既有的 ``_is_word_char`` 语义一致（用 ``str.isalnum()``
    覆盖各种语言），但这里**只**认 ASCII——汉字另有分词规则。
    """
    return ch.isascii() and (ch.isalnum() or ch == "_")


# --------------------------------------------------------------- jieba 接入
#
# jieba 首次使用要加载词典（约 0.5 秒），且它会往 stderr 打
# ``pkg_resources is deprecated`` 警告。文本框是常驻界面，不能让这些
# 噪声出现在用户的控制台里，所以：
#
# - 懒加载：只有真的遇到汉字才初始化；
# - 静音：加载期的警告就地抑制，不影响全局警告设置。

_jieba_module = None


def _get_jieba():  # noqa: ANN202
    """惰性获取 jieba 模块；不可用时返回 None。"""
    global _jieba_module
    if _jieba_module is not None:
        return _jieba_module
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import jieba  # noqa: PLC0415 - 惰性导入，启动时不付这个代价

        jieba.setLogLevel("ERROR")
        _jieba_module = jieba
    except Exception:
        # jieba 不可用时退化成「整段汉字算一个词」——与改造前的行为
        # 一致，好过让整个文本框的选词功能失效。
        _jieba_module = False
    return _jieba_module or None


def _segment_cjk(text: str) -> list[tuple[int, int]]:
    """把一段汉字切成词，返回 [(起始, 结束), ...]。

    用 ``jieba.tokenize`` 而不是 ``cut``：它给出的是**偏移**，直接就能
    定位，省得再把词拼回去反查位置。
    """
    jieba = _get_jieba()
    if jieba is None:
        # 退化：整段算一个词
        return [(0, len(text))] if text else []
    try:
        return [(start, end) for _word, start, end in jieba.tokenize(text)]
    except Exception:
        return [(0, len(text))] if text else []


def _is_word_char(ch: str) -> bool:
    """该字符是否参与组词（汉字或 ASCII 词字符）。"""
    return is_cjk(ch) or _is_ascii_word_char(ch)


# --------------------------------------------------------------- 词边界定位


def _ascii_word_range(text: str, anchor: int) -> Optional[tuple[int, int]]:
    """ASCII 词的 [start, end)；``anchor`` 必须是词字符的位置。"""
    start = anchor
    while start > 0 and _is_ascii_word_char(text[start - 1]):
        start -= 1
    end = anchor
    while end < len(text) and _is_ascii_word_char(text[end]):
        end += 1
    if start == end:
        return None
    return start, end


def _cjk_word_range(text: str, anchor: int) -> Optional[tuple[int, int]]:
    """汉字词的 [start, end)；``anchor`` 必须是汉字的位置。

    先找出 anchor 落在哪一段连续汉字里，再对**那一段**分词——只切这一段
    而不是整篇文本，既快又更准（上下文越少，误切越少）。
    """
    length = len(text)
    run_start = anchor
    while run_start > 0 and is_cjk(text[run_start - 1]):
        run_start -= 1
    run_end = anchor
    while run_end < length and is_cjk(text[run_end]):
        run_end += 1

    run = text[run_start:run_end]
    offset = anchor - run_start
    for start, end in _segment_cjk(run):
        if start <= offset < end:
            return run_start + start, run_start + end
    return None


def word_range_at(text: str, position: int) -> Optional[tuple[int, int]]:
    """返回 ``position`` 所在单词的 [start, end)；不在词内返回 None。

    定位规则（沿用文本框既有的 ``_word_range_at`` 语义，不另立规矩）：

    1. 光标位置上的字符是词字符 → 选**它**所在的词；
    2. 光标位置上是分隔符（空白/标点）→ 回退到光标**左边**那个字符，
       若左边也不是词字符则没有词（返回 None）。

    第 2 条让「刚打完一个词，光标停在词尾」时仍能选到刚写的那个词。
    """
    if not text:
        return None
    position = max(0, min(position, len(text)))

    # 先定「锚点」：优先光标正上方的字符，其次光标左边的那个。
    # 顺序不能反——「中文abc」里光标落在 'a' 上时必须归 ASCII 词，
    # 不能因为左边是汉字就跑去按汉字分词。
    anchor: Optional[int] = None
    if position < len(text) and _is_word_char(text[position]):
        anchor = position
    elif position > 0 and _is_word_char(text[position - 1]):
        anchor = position - 1
    if anchor is None:
        return None

    if is_cjk(text[anchor]):
        return _cjk_word_range(text, anchor)
    return _ascii_word_range(text, anchor)
