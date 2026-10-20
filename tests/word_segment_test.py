"""中文分词模块（util/client/word_segment.py）行为测试。

不依赖 pytest：直接 `python tests/word_segment_test.py` 运行。

这个模块的职责单一：**在文本里定位「光标所在的那个词」**。
文本框的 Ctrl+D / Ctrl+Shift+L / 双击选词都靠它。

为什么需要它（而不是沿用 Qt 自带的 ``StartOfWord``/``EndOfWord``）：
Qt 把一整段连续汉字当作**一个**词——

    StartOfWord..EndOfWord 在「语音输入测试字符串」上选中 9 个字

而用户期望的是按词典分词后的「语音输入」。于是引入 jieba。

但 jieba 不能全盘接管：**ASCII 词必须保持原样**。jieba 会把
``foo_bar`` 切成 ``foo`` / ``_`` / ``bar``，而文本框里下划线词是一个整体。
所以分工是：

- 光标落在 **ASCII 词**（字母/数字/下划线）上 → 走本模块自己的字符规则
- 光标落在 **汉字**上 → 走 jieba 词典分词

**位置约定**（沿用文本框既有的 ``_word_range_at`` 语义，不另立规矩）：

1. 光标位置上的字符是词字符 → 选**它**所在的词；
2. 光标位置上是分隔符（空白/标点）→ 回退到光标**左边**那个字符，
   若左边也是分隔符则没有词（返回 None）。

这条约定让「刚打完一个词，光标停在词尾」时能选到刚写的那个词。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from util.client.word_segment import (  # noqa: E402
    is_cjk,
    word_end_at,
    word_range_at,
    word_start_at,
)

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# ---------------------------------------------------------------- CJK 判定


@test
def test_is_cjk_true_for_hanzi() -> None:
    """常用汉字属于 CJK。"""
    assert is_cjk("中") is True
    assert is_cjk("文") is True
    assert is_cjk("龥") is True


@test
def test_is_cjk_false_for_ascii() -> None:
    """ASCII 字母数字不是 CJK。"""
    assert is_cjk("a") is False
    assert is_cjk("Z") is False
    assert is_cjk("1") is False
    assert is_cjk(" ") is False


@test
def test_is_cjk_false_for_cjk_punctuation() -> None:
    """全角标点是**分隔符**，不是词字符。

    标点不参与组词：jieba 也会把它单独切成一个 token，
    而词边界应当停在标点上。
    """
    assert is_cjk("，") is False
    assert is_cjk("。") is False


# ------------------------------------------------------------ ASCII 词规则


@test
def test_ascii_word_is_whole_run() -> None:
    """ASCII 字母数字构成一个词。"""
    assert word_range_at("hello world", 0) == (0, 5)
    assert word_range_at("hello world", 4) == (0, 5)
    assert word_range_at("hello world", 6) == (6, 11)


@test
def test_ascii_word_keeps_underscore_inside() -> None:
    """下划线是词内字符：foo_bar 是一个词。

    这是**不能**把 ASCII 路径交给 jieba 的原因——jieba 会把它切成
    ``foo`` / ``_`` / ``bar`` 三段。
    """
    assert word_range_at("foo_bar baz", 0) == (0, 7)
    assert word_range_at("foo_bar baz", 3) == (0, 7)
    assert word_range_at("foo_bar baz", 6) == (0, 7)


@test
def test_ascii_digits_are_word_chars() -> None:
    """数字也是词内字符。"""
    assert word_range_at("test123 ok", 0) == (0, 7)
    assert word_range_at("test123 ok", 6) == (0, 7)


# ---------------------------------------------------------------- CJK 分词


@test
def test_cjk_run_is_split_into_dictionary_words() -> None:
    """整段汉字按词典分词，而不是当成一个词。

    这是本次改造的核心：旧实现把「语音输入测试字符串」整个当成一个词，
    Ctrl+D 一次选中 9 个字；分词后应当只选中「语音输入」。
    """
    text = "语音输入测试字符串"
    assert word_range_at(text, 0) == (0, 4)
    assert word_range_at(text, 3) == (0, 4)
    # 「测试」在 [4, 6)
    assert word_range_at(text, 4) == (4, 6)
    assert word_range_at(text, 5) == (4, 6)
    # 「字符串」在 [6, 9)
    assert word_range_at(text, 6) == (6, 9)
    assert word_range_at(text, 8) == (6, 9)


@test
def test_cjk_position_on_a_word_start_selects_that_word() -> None:
    """光标正好落在某个词的**首字**上时，选中该词。

    约定是「位置上的字符优先」：位置 4 上是「测」，于是选「测试」
    而不是前一个词「语音输入」。
    """
    text = "语音输入测试字符串"
    assert word_range_at(text, 4) == (4, 6)


@test
def test_cjk_word_in_middle_of_text_is_located_correctly() -> None:
    """文本中间的词也能定位（偏移必须相对整篇文本，不能相对词本身）。"""
    text = "欢迎使用CapsWriter离线语音输入"
    # jieba: 欢迎 / 使用 / CapsWriter / 离线 / 语音输入
    assert word_range_at(text, 0) == (0, 2)
    assert word_range_at(text, 2) == (2, 4)
    assert word_range_at(text, 4) == (4, 14)
    assert word_range_at(text, 14) == (14, 16)
    assert word_range_at(text, 16) == (16, 20)


@test
def test_cjk_punctuation_separates_words() -> None:
    """标点是词边界：不能跨标点选词。

    位置 2 落在逗号上，按约定回退到左边的「别」，
    于是选中「识别」——与文本框既有行为一致。
    """
    text = "识别，完成"
    assert word_range_at(text, 0) == (0, 2)
    assert word_range_at(text, 1) == (0, 2)
    assert word_range_at(text, 2) == (0, 2)
    assert word_range_at(text, 3) == (3, 5)
    assert word_range_at(text, 4) == (3, 5)


@test
def test_single_char_cjk_word_is_selectable() -> None:
    """单字词也要能选中（「我」「想」这种）。"""
    text = "我想去北京大学学习人工智能"
    assert word_range_at(text, 0) == (0, 1)
    assert word_range_at(text, 1) == (1, 2)


# ------------------------------------------------------------ 边界与异常


@test
def test_returns_none_on_empty_text() -> None:
    """空文本没有词。"""
    assert word_range_at("", 0) is None


@test
def test_returns_none_on_whitespace_only() -> None:
    """纯空白没有词。"""
    assert word_range_at("   ", 1) is None


@test
def test_returns_none_on_punctuation_only() -> None:
    """纯标点没有词（左右都不是词字符）。"""
    assert word_range_at("，、。", 1) is None


@test
def test_position_is_clamped_into_text() -> None:
    """越界位置夹回文本范围内，不抛异常。"""
    text = "hello"
    assert word_range_at(text, 99) == (0, 5)
    assert word_range_at(text, -5) == (0, 5)


@test
def test_mixed_cjk_and_ascii_each_segmented_by_own_rule() -> None:
    """中英混排：汉字段走 jieba，ASCII 段走字符规则。"""
    text = "中文abc混合"
    assert word_range_at(text, 0) == (0, 2)
    assert word_range_at(text, 2) == (2, 5)
    assert word_range_at(text, 5) == (5, 7)


# ------------------------------------------------------- 按词跳（Ctrl+←/→）
#
# Qt 自带的 ``PreviousWord``/``NextWord`` 对中文是「整段连续汉字算一个词」：
#
#     在「语音输入测试字符串」上从 pos 2 跳 PreviousWord -> 0（跳了 2 个字）
#     从 pos 2 跳 NextWord -> 10（跳过整段 9 个字）
#
# 要按词典词粒度跳（语音输入 / 测试 / 字符串），必须自己算词边界。
#
# 语义与 VS Code 一致：
# - ``Ctrl+←``：光标在词中间 → 跳到**当前词开头**；已在词开头 → 跳到**上一个词开头**
# - ``Ctrl+→``：光标在词中间 → 跳到**当前词末尾**；已在词末尾 → 跳到**下一个词开头**


@test
def test_word_start_at_jumps_to_current_word_start() -> None:
    """光标在词中间时，Ctrl+← 跳到当前词的**开头**。"""
    text = "语音输入测试字符串"
    assert word_start_at(text, 1) == 0
    assert word_start_at(text, 3) == 0
    assert word_start_at(text, 5) == 4
    assert word_start_at(text, 7) == 6


@test
def test_word_start_at_jumps_to_previous_word_when_already_at_start() -> None:
    """光标已在词开头时，Ctrl+← 跳到**上一个词**的开头。"""
    text = "语音输入测试字符串"
    assert word_start_at(text, 4) == 0
    assert word_start_at(text, 6) == 4


@test
def test_word_start_at_stops_at_document_beginning() -> None:
    """已在第一个词开头时，Ctrl+← 不再往回跳。"""
    text = "语音输入测试字符串"
    assert word_start_at(text, 0) == 0


@test
def test_word_end_at_jumps_to_current_word_end() -> None:
    """光标在词中间时，Ctrl+→ 跳到当前词的**末尾**。"""
    text = "语音输入测试字符串"
    assert word_end_at(text, 0) == 4
    assert word_end_at(text, 1) == 4
    assert word_end_at(text, 5) == 6
    assert word_end_at(text, 7) == 9


@test
def test_word_end_at_jumps_to_next_word_when_already_at_end() -> None:
    """光标已在词末尾时，Ctrl+→ 跳到**下一个词的末尾**。

    与 VS Code 的 ``cursorWordEnd`` 一致：跳的是下一个词的**末尾**，
    不是它的开头。中文的「词末尾」是最后一个字之后那一格。
    """
    text = "语音输入测试字符串"
    assert word_end_at(text, 4) == 6
    assert word_end_at(text, 6) == 9


@test
def test_word_end_at_stops_at_document_end() -> None:
    """已在最后一个词末尾时，Ctrl+→ 不再往后跳。"""
    text = "语音输入测试字符串"
    assert word_end_at(text, 9) == 9


@test
def test_word_navigation_handles_ascii_words() -> None:
    """ASCII 词同样按词跳。"""
    text = "hello world"
    assert word_start_at(text, 3) == 0
    assert word_start_at(text, 5) == 0
    assert word_start_at(text, 8) == 6
    assert word_end_at(text, 0) == 5
    assert word_end_at(text, 8) == 11


@test
def test_word_navigation_crosses_whitespace() -> None:
    """词与词之间的空白不是词，跳过时直接落到相邻的词边界。

    「语音输入 测试」中 pos 4 是空白：
    - Ctrl+← 从 4 退到「语音输入」的开头 0；
    - Ctrl+→ 从 4 前进到「测试」的末尾 7。
    """
    text = "语音输入 测试"
    assert word_start_at(text, 4) == 0
    assert word_end_at(text, 4) == 7


@test
def test_word_navigation_keeps_underscore_word_whole() -> None:
    """下划线词整体跳（不被切成三段）。"""
    text = "foo_bar baz"
    assert word_start_at(text, 3) == 0
    assert word_end_at(text, 0) == 7
    assert word_end_at(text, 9) == 11


@test
def test_word_navigation_on_empty_text_is_safe() -> None:
    """空文本不抛异常。"""
    assert word_start_at("", 0) == 0
    assert word_end_at("", 0) == 0


@test
def test_word_navigation_clamps_out_of_range_position() -> None:
    """越界位置夹回文本范围内。"""
    text = "hello world"
    assert word_start_at(text, 99) == 6
    assert word_end_at(text, -5) == 5


def main() -> int:
    failed = []
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed.append(fn.__name__)
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
