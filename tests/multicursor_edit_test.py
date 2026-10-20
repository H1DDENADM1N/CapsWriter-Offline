"""多光标文本编辑器（util/client/multicursor_edit.py）行为测试。

不依赖 pytest：直接 `python tests/multicursor_edit_test.py` 运行，
离屏（QT_QPA_PLATFORM=offscreen）执行，不弹窗、不占用麦克风。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import PySide6  # noqa: E402

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPalette,
    QTextCursor,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from util.client.multicursor_edit import MultiCursorTextEdit  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def make_edit(text: str = "") -> MultiCursorTextEdit:
    """造一个已显示、已获得焦点的编辑器。

    必须显式给焦点：测试会建很多顶层窗口且不关闭，活动窗口不定，
    ``hasFocus()`` 随机为假，而光标只在有焦点时绘制，会造成偶发假失败。
    """
    edit = MultiCursorTextEdit()
    edit.resize(420, 320)
    edit.setPlainText(text)
    edit.show()
    edit.raise_()
    edit.activateWindow()
    edit.setFocus(Qt.FocusReason.OtherFocusReason)
    APP.processEvents()
    return edit


def caret(edit: MultiCursorTextEdit, position: int) -> None:
    cur = edit.textCursor()
    cur.setPosition(position)
    edit.setTextCursor(cur)


# ---------------------------------------------------------------- 光标跟随开关


@test
def test_default_follow_caret_is_enabled() -> None:
    """默认监听中：follow_caret 为 True，行为与旧版一致。"""
    edit = make_edit("line1")
    assert edit.follow_caret is True, edit.follow_caret


@test
def test_append_line_moves_caret_to_end_when_following() -> None:
    """监听中追加日志后，光标跟到末尾。"""
    edit = make_edit("line1")
    caret(edit, 0)
    edit.append_line("line2")
    assert edit.toPlainText() == "line1\nline2", repr(edit.toPlainText())
    assert edit.textCursor().position() == len(edit.toPlainText())


@test
def test_append_line_keeps_caret_when_not_following() -> None:
    """取消监听后追加日志，光标停在用户原处，不被抢走。"""
    edit = make_edit("line1\nline2")
    caret(edit, 2)
    edit.set_follow_caret(False)
    edit.append_line("line3")
    assert "line3" in edit.toPlainText(), repr(edit.toPlainText())
    assert edit.textCursor().position() == 2, edit.textCursor().position()


@test
def test_append_line_keeps_selection_when_not_following() -> None:
    """取消监听后追加日志，用户的选区保持原样。"""
    edit = make_edit("alpha beta gamma")
    cur = edit.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, cur.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    edit.set_follow_caret(False)
    edit.append_line("tail")
    assert edit.textCursor().selectedText() == "alpha", edit.textCursor().selectedText()


@test
def test_scroll_to_bottom_respects_follow_flag() -> None:
    """滚动到底的方法在未跟随时不动光标与滚动条。"""
    body = "\n".join(f"log {i}" for i in range(200))
    edit = make_edit(body)
    edit.set_follow_caret(False)
    scroll = edit.verticalScrollBar()
    scroll.setValue(0)
    caret(edit, 5)
    edit.scroll_to_bottom_if_follow()
    assert edit.textCursor().position() == 5, edit.textCursor().position()
    assert scroll.value() == 0, scroll.value()

    edit.set_follow_caret(True)
    edit.scroll_to_bottom_if_follow()
    assert edit.textCursor().position() == len(edit.toPlainText())
    assert scroll.value() == scroll.maximum(), (scroll.value(), scroll.maximum())


@test
def test_append_line_keeps_selection_when_following() -> None:
    """监听中追加日志不能清掉用户的选区。

    监听模式下 ``append_line`` 会把光标拉到末尾；``moveCursor(End)`` 顺手
    就会把选区清掉。用户右键菜单「全选」后，下一条日志一到达选区就消失，
    表现为「全选状态极短时间自动失效」。
    """
    edit = make_edit("alpha beta gamma")
    edit.selectAll()
    assert edit.textCursor().hasSelection()
    edit.append_line("tail")
    assert edit.textCursor().hasSelection(), "追加日志后选区被清掉了"
    cur = edit.textCursor()
    assert cur.anchor() == 0, cur.anchor()
    assert cur.selectedText().startswith("alpha beta gamma"), cur.selectedText()


@test
def test_scroll_to_bottom_keeps_selection_when_following() -> None:
    """滚动到底时若已有选区，不能顺手把光标拉到末尾。

    右键菜单关闭后窗口会补发 enterEvent，enterEvent 会调本方法。
    """
    edit = make_edit("alpha beta gamma")
    edit.selectAll()
    edit.scroll_to_bottom_if_follow()
    assert edit.textCursor().hasSelection(), "滚动到底把选区清掉了"
    assert edit.textCursor().selectedText() == "alpha beta gamma", (
        edit.textCursor().selectedText()
    )


# ------------------------------------------------------------------ 光标叠加层


def render_overlay(edit: MultiCursorTextEdit) -> QImage:
    """把编辑器视口渲染成图片，用于统计实际画出的副光标像素。

    先停掉闪烁定时器：否则 ``processEvents`` 若恰好跨过一次 530ms 的
    定时器触发，相位会从「亮」翻成「灭」，图片里自然没光标——
    这是环境速度决定的偶发失败，不是实现问题。
    相位由调用方用 ``_caret_blink_tick`` 显式控制。
    """
    edit._caret_timer.stop()
    edit.viewport().update()
    APP.processEvents()
    img = edit.viewport().grab().toImage()
    return img


def count_caret_pixels(img: QImage, edit: MultiCursorTextEdit) -> int:
    """统计副光标矩形内与主光标同色（palette Text）的不透明像素。

    只扫光标矩形而不是全图：全图会把字形像素（也是 palette Text 颜色）
    一起算进去，区分不了「画了竖线」和「画了字」。
    """
    target = edit.palette().color(QPalette.ColorRole.Text)
    _color, width = edit.caret_metrics()
    hits = 0
    for cur in edit.extra_cursors:
        rect = edit.cursorRect(cur)
        for dy in range(rect.height()):
            for dx in range(width):
                x, y = rect.left() + dx, rect.top() + dy
                if not (0 <= x < img.width() and 0 <= y < img.height()):
                    continue
                c = img.pixelColor(x, y)
                if (
                    c.alpha() > 32
                    and abs(c.red() - target.red()) < 24
                    and abs(c.green() - target.green()) < 24
                    and abs(c.blue() - target.blue()) < 24
                ):
                    hits += 1
    return hits


@test
def test_caret_overlay_paints_extra_cursors() -> None:
    """副光标必须真的被画出来（不能只有几何正确）。"""
    edit = make_edit("aaa")
    caret(edit, 0)  # 主光标固定在行首，避开去重
    edit.add_cursor_at(2)
    assert extra_positions(edit) == [2], extra_positions(edit)
    img = render_overlay(edit)
    assert count_caret_pixels(img, edit) > 0, "overlay 没有画出任何副光标像素"


@test
def test_extra_caret_uses_same_color_as_primary() -> None:
    """副光标颜色必须跟随 palette(Text)，与 Qt 主光标一致。"""
    edit = make_edit("aaa")
    edit.setPalette(_palette_with_text("#ff8800"))
    color, _width = edit.caret_metrics()
    assert color.name() == "#ff8800", color.name()
    edit.setPalette(_palette_with_text("#112233"))
    color, _width = edit.caret_metrics()
    assert color.name() == "#112233", color.name()


@test
def test_extra_caret_uses_same_width_as_primary() -> None:
    """副光标粗细必须跟随 cursorWidth()，与 Qt 主光标一致。"""
    edit = make_edit("aaa")
    assert edit.cursorWidth() == 1
    assert edit.caret_metrics()[1] == 1
    edit.setCursorWidth(3)
    assert edit.caret_metrics()[1] == 3, edit.caret_metrics()[1]


@test
def test_extra_caret_width_never_zero() -> None:
    """cursorWidth 为 0 时不画竖线，但副光标仍不能取 0 宽把选区一起吞掉。"""
    edit = make_edit("aaa")
    edit.setCursorWidth(0)
    assert edit.caret_metrics()[1] >= 1, edit.caret_metrics()[1]


def _palette_with_text(name: str) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Text, QColor(name))
    return pal


@test
def test_caret_blinks_when_extra_cursors_exist() -> None:
    """有副光标时闪烁定时器必须跑起来（原先副光标是常亮的）。"""
    edit = make_edit("aaa\nbbb")
    edit.add_cursor_at(4)
    assert edit.caret_blinking is True, "副光标闪烁定时器没有启动"


@test
def test_caret_blink_stops_without_extra_cursors() -> None:
    """没有副光标时不应空转定时器。"""
    edit = make_edit("aaa")
    assert edit.caret_blinking is False


@test
def test_caret_blink_toggles_phase() -> None:
    """闪烁必须真的在「亮/灭」之间切换，而不是常亮。"""
    edit = make_edit("aaa\nbbb")
    edit.add_cursor_at(4)
    assert edit.caret_phase is True
    edit._caret_blink_tick()
    assert edit.caret_phase is False, "tick 后相位没有翻转"
    edit._caret_blink_tick()
    assert edit.caret_phase is True


@test
def test_extra_caret_disappears_on_dark_phase() -> None:
    """相位为「灭」时副光标像素应消失，否则就是不闪。

    光标位置选在行尾空白处：贴着字母的位置，光标矩形会与字形重叠，
    那时统计到的像素是文字本身而不是副光标。
    """
    edit = make_edit("aaa\nbbb")
    caret(edit, 0)
    edit.add_cursor_at(3)  # 第一行行尾，右侧无字形
    lit = count_caret_pixels(render_overlay(edit), edit)
    assert lit > 0, lit
    edit._caret_blink_tick()  # true -> false
    assert edit.caret_phase is False
    dark = count_caret_pixels(render_overlay(edit), edit)
    assert dark == 0, f"灭相位仍画了 {dark} 个像素"


@test
def test_extra_caret_keeps_color_in_dark_phase_after_restore() -> None:
    """相位切回「亮」时副光标颜色不变（不能因闪烁改色调）。"""
    edit = make_edit("aaa")
    caret(edit, 0)
    edit.add_cursor_at(2)
    before = count_caret_pixels(render_overlay(edit), edit)
    edit._caret_blink_tick()
    edit._caret_blink_tick()
    after = count_caret_pixels(render_overlay(edit), edit)
    assert before == after, (before, after)


@test
def test_blink_interval_follows_system_setting() -> None:
    """闪烁半周期取自 QApplication.cursorFlashTime()/2。"""
    edit = make_edit("aaa\nbbb")
    edit.add_cursor_at(4)
    expected = max(1, int(QApplication.cursorFlashTime()) // 2)
    assert edit.caret_blink_interval == expected, (
        edit.caret_blink_interval,
        expected,
    )


# -------------------------------------------------- 主光标与副光标同相位绘制


def paint_carets_at_phase(edit: MultiCursorTextEdit, on: bool) -> QImage:
    """按给定相位把「全部光标」（主 + 副）画到一张图上。"""
    from PySide6.QtGui import QPainter

    img = QImage(edit.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    try:
        edit._paint_all_carets(painter, on)
    finally:
        painter.end()
    return img


def primary_caret_pixels(img: QImage, edit: MultiCursorTextEdit) -> int:
    """统计主光标矩形内的光标色像素。"""
    target = edit.palette().color(QPalette.ColorRole.Text)
    _c, width = edit.caret_metrics()
    rect = edit.cursorRect(edit.textCursor())
    hits = 0
    for dy in range(rect.height()):
        for dx in range(width):
            x, y = rect.left() + dx, rect.top() + dy
            if not (0 <= x < img.width() and 0 <= y < img.height()):
                continue
            c = img.pixelColor(x, y)
            if c.alpha() > 32 and abs(c.red() - target.red()) < 24:
                hits += 1
    return hits


@test
def test_primary_and_extra_carets_share_one_phase() -> None:
    """主光标与副光标必须由同一个相位控制（这是闪烁不同步的根因）。

    原来副光标用自己的 QTimer，而 Qt 主光标有自己的内部计时器，
    两者起点不同就会逆相（一个亮一个灭），永远无法真正同步。
    现在两者在同一段代码里、按同一相位绘制。
    """
    edit = make_edit("aaa\nbbb")
    caret(edit, 0)
    edit.add_cursor_at(4)
    edit.setFocus()
    APP.processEvents()

    lit = paint_carets_at_phase(edit, True)
    assert primary_caret_pixels(lit, edit) > 0, "亮相位主光标没画"
    assert count_caret_pixels(lit, edit) > 0, "亮相位副光标没画"

    dark = paint_carets_at_phase(edit, False)
    assert primary_caret_pixels(dark, edit) == 0, "灭相位主光标仍在画"
    assert count_caret_pixels(dark, edit) == 0, "灭相位副光标仍在画"


@test
def test_qt_primary_caret_hidden_while_extra_cursors_exist() -> None:
    """有副光标时把 Qt 自带光标宽度置 0，避免它另画一根不同步的线。"""
    edit = make_edit("aaa\nbbb")
    assert edit.cursorWidth() == 1, edit.cursorWidth()
    edit.add_cursor_at(4)
    assert edit.cursorWidth() == 0, "有副光标时 Qt 光标应隐藏"
    edit.clear_extra_cursors()
    assert edit.cursorWidth() == 1, "回归单光标后应恢复 Qt 光标"


@test
def test_user_cursor_width_preserved_across_multicursor_mode() -> None:
    """用户设的粗细不能因开关多光标而丢失，caret_metrics 仍报告它。"""
    edit = make_edit("aaa\nbbb")
    edit.setCursorWidth(3)
    assert edit.caret_metrics()[1] == 3, edit.caret_metrics()[1]
    edit.add_cursor_at(4)
    assert edit.cursorWidth() == 0, "多光标时 Qt 光标应隐藏"
    assert edit.caret_metrics()[1] == 3, "用户粗细应被保留"
    edit.clear_extra_cursors()
    assert edit.cursorWidth() == 3, edit.cursorWidth()


@test
def test_caret_overlay_paints_nothing_without_extra_cursors() -> None:
    """没有副光标时不应伪画任何光标色像素。"""
    edit = make_edit("aaa\nbbb")
    assert edit.extra_cursor_count() == 0
    img = render_overlay(edit)
    assert count_caret_pixels(img, edit) == 0, count_caret_pixels(img, edit)


@test
def test_extra_caret_hidden_when_editor_loses_focus() -> None:
    """失焦时副光标也要隐去，与 Qt 主光标行为一致。"""
    edit = make_edit("aaa\nbbb")
    caret(edit, 0)
    edit.add_cursor_at(3)
    edit.setFocus()
    APP.processEvents()
    assert count_caret_pixels(render_overlay(edit), edit) > 0
    edit.clearFocus()
    edit.focusOutEvent(_focus_event())
    APP.processEvents()
    assert count_caret_pixels(render_overlay(edit), edit) == 0, "失焦后副光标仍在绘制"


def _focus_event():
    from PySide6.QtGui import QFocusEvent

    return QFocusEvent(QEvent.Type.FocusOut)


@test
def test_caret_overlay_covers_viewport() -> None:
    """视口尺寸随编辑器变化，副光标始终画在可见区域内。"""
    edit = make_edit("abc")
    edit.resize(500, 400)
    APP.processEvents()
    assert edit.viewport().width() > 0
    assert edit.viewport().height() > 0


# ------------------------------------------------------------------ 多光标集合


def extra_positions(edit: MultiCursorTextEdit) -> list[int]:
    return sorted(min(c.position(), c.anchor()) for c in edit.extra_cursors)


@test
def test_add_cursor_at_position_creates_extra_cursor() -> None:
    """在指定字符位置加一个副光标。"""
    edit = make_edit("hello world")
    edit.add_cursor_at(6)
    assert extra_positions(edit) == [6], extra_positions(edit)
    assert edit.extra_cursor_count() == 1


@test
def test_add_cursor_at_existing_position_is_idempotent() -> None:
    """在同一位置重复加光标不会产生重复项。"""
    edit = make_edit("hello world")
    edit.add_cursor_at(6)
    edit.add_cursor_at(6)
    assert extra_positions(edit) == [6], extra_positions(edit)


@test
def test_add_cursor_at_primary_position_is_ignored() -> None:
    """在主光标位置加光标无效。"""
    edit = make_edit("hello world")
    caret(edit, 3)
    edit.add_cursor_at(3)
    assert edit.extra_cursor_count() == 0


@test
def test_toggle_cursor_at_removes_existing_extra_cursor() -> None:
    """Alt+点击 已存在的副光标位置时移除它。"""
    edit = make_edit("hello world")
    edit.add_cursor_at(6)
    edit.toggle_cursor_at(6)
    assert edit.extra_cursor_count() == 0


@test
def test_clear_extra_cursors_keeps_primary() -> None:
    """收敛后只剩主光标，且主光标位置不变。"""
    edit = make_edit("hello world")
    caret(edit, 2)
    edit.add_cursor_at(6)
    edit.add_cursor_at(8)
    edit.clear_extra_cursors()
    assert edit.extra_cursor_count() == 0
    assert edit.textCursor().position() == 2


@test
def test_extra_cursors_emit_count_change() -> None:
    """副光标数量变化时发出信号，方便界面更新提示。"""
    edit = make_edit("hello world")
    seen: list[int] = []
    edit.extra_cursor_count_changed.connect(seen.append)
    edit.add_cursor_at(6)
    edit.add_cursor_at(8)
    edit.clear_extra_cursors()
    assert seen == [1, 2, 0], seen


# -------------------------------------------------------------- 同步编辑动作


@test
def test_insert_text_at_all_cursors() -> None:
    """多光标下输入的文字同时插入所有光标处。"""
    edit = make_edit("ab\nab")
    caret(edit, 1)
    edit.add_cursor_at(4)
    edit.insert_text_at_cursors("X")
    assert edit.toPlainText() == "aXb\naXb", repr(edit.toPlainText())


@test
def test_backspace_deletes_before_every_cursor() -> None:
    """多光标退格删除每个光标前的字符。"""
    edit = make_edit("ab\nab")
    caret(edit, 1)
    edit.add_cursor_at(4)
    edit.delete_at_cursors(backward=True)
    assert edit.toPlainText() == "b\nb", repr(edit.toPlainText())


@test
def test_delete_removes_after_every_cursor() -> None:
    """多光标 Delete 删除每个光标后的字符。"""
    edit = make_edit("ab\nab")
    caret(edit, 0)
    edit.add_cursor_at(3)
    edit.delete_at_cursors(backward=False)
    assert edit.toPlainText() == "b\nb", repr(edit.toPlainText())


@test
def test_newline_inserted_at_all_cursors() -> None:
    """多光标回车在各光标处断行。"""
    edit = make_edit("ab\ncd")
    caret(edit, 1)
    edit.add_cursor_at(4)
    edit.insert_text_at_cursors("\n")
    assert edit.toPlainText() == "a\nb\nc\nd", repr(edit.toPlainText())


@test
def test_multi_cursor_edit_is_single_undo_step() -> None:
    """一次多光标输入只占一步撤销。"""
    edit = make_edit("ab\nab")
    caret(edit, 1)
    edit.add_cursor_at(4)
    edit.insert_text_at_cursors("XY")
    assert edit.toPlainText() == "aXYb\naXYb", repr(edit.toPlainText())
    edit.undo()
    assert edit.toPlainText() == "ab\nab", repr(edit.toPlainText())


@test
def test_insert_at_cursors_survives_earlier_position_edits() -> None:
    """靠后的光标先应用，靠前的不发生位置漂移。"""
    edit = make_edit("1111\n2222\n3333")
    caret(edit, 0)
    edit.add_cursor_at(5)
    edit.add_cursor_at(10)
    edit.insert_text_at_cursors("_")
    assert edit.toPlainText() == "_1111\n_2222\n_3333", repr(edit.toPlainText())


@test
def test_extra_cursor_positions_shift_after_earlier_insert() -> None:
    """在更靠前的位置插字后，靠后的副光标位置必须跟着顺延。

    原缺陷：位置在「编辑当时」就被固定成绝对值，随后前面又插入了字符，
    导致副光标落在错的行上（三行文本输入一次就跨行错位）。
    """
    edit = make_edit("aaa\nbbb\nccc")
    caret(edit, 0)
    edit.add_cursor_at(4)
    edit.add_cursor_at(8)
    edit.insert_text_at_cursors("X")
    assert edit.toPlainText() == "Xaaa\nXbbb\nXccc", repr(edit.toPlainText())
    assert edit.textCursor().position() == 1, edit.textCursor().position()
    # 三个光标下输入 X 后应各停在行首 X 之后，不能因为前面插了字而错位
    assert sorted(extra_positions(edit)) == [6, 11], extra_positions(edit)


@test
def test_extra_cursor_positions_stay_stable_across_repeated_typing() -> None:
    """连续输入时副光标不能逐渐漂移。"""
    edit = make_edit("aaa\nbbb\nccc")
    caret(edit, 0)
    edit.add_cursor_at(4)
    edit.add_cursor_at(8)
    for ch in "XY":
        edit.insert_text_at_cursors(ch)
    assert edit.toPlainText() == "XYaaa\nXYbbb\nXYccc", repr(edit.toPlainText())
    assert edit.textCursor().position() == 2, edit.textCursor().position()
    assert sorted(extra_positions(edit)) == [8, 14], extra_positions(edit)


@test
def test_extra_cursor_positions_shift_after_earlier_delete() -> None:
    """在更靠前的位置删字后，靠后的副光标位置必须跟着前移。"""
    edit = make_edit("xa\nxb")
    caret(edit, 0)
    edit.add_cursor_at(3)
    edit.delete_at_cursors(backward=False)
    assert edit.toPlainText() == "a\nb", repr(edit.toPlainText())
    # 靠前的光标删除后，靠后的副光标必须从 3 前移到 2
    assert extra_positions(edit) == [2], extra_positions(edit)
    assert edit.textCursor().position() == 0, edit.textCursor().position()


@test
def test_extra_cursor_positions_after_mixed_length_insert() -> None:
    """不同位置插入不同长度文本时位置仍然正确。"""
    edit = make_edit("a\nb\nc")
    caret(edit, 0)
    edit.add_cursor_at(2)
    edit.add_cursor_at(4)
    edit.insert_text_at_cursors("LONG")
    assert edit.toPlainText() == "LONGa\nLONGb\nLONGc", repr(edit.toPlainText())
    assert edit.textCursor().position() == 4, edit.textCursor().position()
    assert sorted(extra_positions(edit)) == [10, 16], extra_positions(edit)


# -------------------------------------------------------- 选中下一个相同内容


def select_word_at(edit: MultiCursorTextEdit, start: int, end: int) -> None:
    cur = edit.textCursor()
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)


def selected_texts(edit: MultiCursorTextEdit) -> list[str]:
    texts = [edit.textCursor().selectedText()] if edit.textCursor().hasSelection() else []
    texts.extend(c.selectedText() for c in edit.extra_cursors if c.hasSelection())
    return texts


@test
def test_select_next_occurrence_without_selection_selects_word_under_caret() -> None:
    """无选区时 Ctrl+D 先选中光标所在的词。"""
    edit = make_edit("foo bar foo")
    caret(edit, 1)
    edit.select_next_occurrence()
    assert edit.textCursor().selectedText() == "foo", selected_texts(edit)
    assert edit.extra_cursor_count() == 0


@test
def test_select_next_occurrence_adds_second_match() -> None:
    """再次 Ctrl+D 选中下一个相同内容作为副光标。"""
    edit = make_edit("foo bar foo baz")
    select_word_at(edit, 0, 3)
    edit.select_next_occurrence()
    assert selected_texts(edit) == ["foo", "foo"], selected_texts(edit)
    assert extra_positions(edit) == [8], extra_positions(edit)


@test
def test_select_next_occurrence_chains_until_no_match() -> None:
    """连续 Ctrl+D 一路选中全部匹配，越界后不再增加。"""
    edit = make_edit("ab cd ab ef ab")
    select_word_at(edit, 0, 2)
    edit.select_next_occurrence()
    edit.select_next_occurrence()
    assert edit.extra_cursor_count() == 2, extra_positions(edit)
    edit.select_next_occurrence()
    assert edit.extra_cursor_count() == 2, extra_positions(edit)


@test
def test_select_all_occurrences_selects_every_match() -> None:
    """Ctrl+Shift+L 选中全文所有相同内容。"""
    edit = make_edit("x y x z x")
    select_word_at(edit, 0, 1)
    edit.select_all_occurrences()
    assert edit.extra_cursor_count() == 2, extra_positions(edit)
    assert selected_texts(edit) == ["x", "x", "x"], selected_texts(edit)


@test
def test_select_all_occurrences_without_word_under_caret_is_noop() -> None:
    """光标在空白处、无选区时 Ctrl+Shift+L 不做任何事。"""
    edit = make_edit("abc   def")
    caret(edit, 4)
    edit.select_all_occurrences()
    assert edit.extra_cursor_count() == 0
    assert not edit.textCursor().hasSelection()


@test
def test_select_next_occurrence_picks_following_match_not_first() -> None:
    """Ctrl+D 必须从当前选中项**往后**找下一个匹配，而不是从文档开头找。

    旧实现每次都取「第一个还没被选中的匹配」，于是用户在第 2 项上按
    Ctrl+D，选中的却是文档里排在最前面的第 1 项——表现为「从头递增」。
    """
    edit = make_edit("foo bar foo baz foo")
    select_word_at(edit, 8, 11)  # 第二个 foo
    edit.select_next_occurrence()
    assert extra_positions(edit) == [16], extra_positions(edit)


@test
def test_select_next_occurrence_wraps_around_to_earliest_unselected() -> None:
    """走到文档末尾后回绕到最前面的未选中项（VS Code 同款循环）。"""
    edit = make_edit("foo bar foo")
    select_word_at(edit, 8, 11)  # 第二个 foo
    edit.select_next_occurrence()
    # 末尾之后没有匹配，回绕到第一个 foo
    assert extra_positions(edit) == [0], extra_positions(edit)


@test
def test_select_next_occurrence_stops_when_all_occurrences_selected() -> None:
    """所有匹配都选中之后，再按 Ctrl+D 不再增加新项。"""
    edit = make_edit("foo bar foo baz foo")
    select_word_at(edit, 8, 11)
    edit.select_next_occurrence()
    edit.select_next_occurrence()  # 回绕到第一个 foo
    assert extra_positions(edit) == [0, 16], extra_positions(edit)
    edit.select_next_occurrence()
    assert extra_positions(edit) == [0, 16], extra_positions(edit)


@test
def test_select_next_occurrence_in_chinese_selects_word_under_caret() -> None:
    """中文光标下的字也能被 Ctrl+D 选中。

    旧实现的词字符集合写死为 ASCII 字母数字，中文里一个都不算，
    于是 `_word_range_at` 恒返回 None，Ctrl+D 在中文日志上完全无效。
    """
    edit = make_edit("识别,完成")
    caret(edit, 0)
    assert edit.select_next_occurrence() is True
    assert edit.textCursor().selectedText() == "识别", selected_texts(edit)
    assert edit.extra_cursor_count() == 0


@test
def test_select_next_occurrence_in_chinese_picks_next_occurrence() -> None:
    """中文里连续 Ctrl+D 也能逐个选中后面的相同内容。"""
    edit = make_edit("中文,中文")
    caret(edit, 0)
    edit.select_next_occurrence()
    assert edit.textCursor().selectedText() == "中文", selected_texts(edit)
    edit.select_next_occurrence()
    assert extra_positions(edit) == [3], extra_positions(edit)


@test
def test_word_range_at_stops_at_chinese_punctuation() -> None:
    """中文标点是词分隔符，选词不能跨越标点。"""
    edit = make_edit("你好，世界")
    assert edit._word_range_at(0) == (0, 2)
    assert edit._word_range_at(1) == (0, 2)
    assert edit._word_range_at(3) == (3, 5)
    assert edit._word_range_at(4) == (3, 5)


@test
def test_word_range_at_handles_mixed_chinese_and_ascii() -> None:
    """中英混排时各自的词边界正确。"""
    edit = make_edit("中文 abc 混合")
    assert edit._word_range_at(0) == (0, 2)
    assert edit._word_range_at(3) == (3, 6)
    assert edit._word_range_at(7) == (7, 9)


@test
def test_word_range_at_returns_none_outside_any_word() -> None:
    """光标落在空白/标点上（且前后都不是词字符）时返回 None。"""
    edit = make_edit("   ")
    assert edit._word_range_at(1) is None


@test
def test_selection_seed_uses_document_text_not_selected_text() -> None:
    """跨行选区的 needle 必须取文档原文，不能取带 U+2029 的 selectedText。

    `QTextCursor.selectedText()` 在跨行时用 U+2029 作换行符，而文档里
    是 "\\n"，拿它去 `toPlainText().find()` 永远找不到匹配。
    """
    edit = make_edit("aa\nbb")
    cur = edit.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    seeded = edit._selection_seed()
    assert seeded is not None
    needle, start, end, had_selection = seeded
    assert needle == "aa\nbb", repr(needle)
    assert (start, end) == (0, 5)
    assert had_selection is True


@test
def test_select_all_occurrences_keeps_primary_on_current_selection() -> None:
    """Ctrl+Shift+L 之后主光标应留在当前选中的那一项上。"""
    edit = make_edit("x y x z x")
    select_word_at(edit, 8, 9)  # 最后一个 x
    edit.select_all_occurrences()
    assert edit.extra_cursor_count() == 2, extra_positions(edit)
    assert selected_texts(edit) == ["x", "x", "x"], selected_texts(edit)
    assert edit.textCursor().selectedText() == "x"


@test
def test_undo_last_cursor_removes_most_recent_extra() -> None:
    """Ctrl+U 撤销最后添加的那个副光标。"""
    edit = make_edit("ab cd ab ef ab")
    select_word_at(edit, 0, 2)
    edit.select_next_occurrence()
    edit.select_next_occurrence()
    assert edit.extra_cursor_count() == 2
    edit.undo_last_cursor()
    assert edit.extra_cursor_count() == 1, extra_positions(edit)
    edit.undo_last_cursor()
    assert edit.extra_cursor_count() == 0, extra_positions(edit)


@test
def test_undo_last_cursor_without_extras_is_noop() -> None:
    """没有副光标时 Ctrl+U 不动主光标。"""
    edit = make_edit("abc")
    caret(edit, 2)
    edit.undo_last_cursor()
    assert edit.textCursor().position() == 2


# ------------------------------------------------------------------ 按键分发


def key(edit: MultiCursorTextEdit, *, key_code, modifiers=Qt.KeyboardModifier.NoModifier, text=""):
    event = QKeyEvent(QEvent.Type.KeyPress, key_code, modifiers, text)
    edit.keyPressEvent(event)
    return event


@test
def test_escape_collapses_extras_and_is_accepted() -> None:
    """有副光标时 Esc 收敛为单光标，并吞掉该按键（不隐藏窗口）。"""
    edit = make_edit("abcabc")
    caret(edit, 0)
    edit.add_cursor_at(3)
    event = key(edit, key_code=Qt.Key.Key_Escape)
    assert edit.extra_cursor_count() == 0
    assert event.isAccepted(), "Esc 有副光标时应被吞掉"


@test
def test_escape_without_extras_is_ignored() -> None:
    """无副光标时 Esc 不被 accept，交给主窗口隐藏窗口。"""
    edit = make_edit("abc")
    event = key(edit, key_code=Qt.Key.Key_Escape)
    assert not event.isAccepted(), "无副光标时 Esc 必须冒泡给主窗口"


@test
def test_typing_routes_to_all_cursors() -> None:
    """多光标下敲字符按位置同步插入。"""
    edit = make_edit("ab\nab")
    caret(edit, 1)
    edit.add_cursor_at(4)
    key(edit, key_code=Qt.Key.Key_Z, text="Z")
    assert edit.toPlainText() == "aZb\naZb", repr(edit.toPlainText())


@test
def test_typing_without_extras_keeps_normal_behavior() -> None:
    """无副光标时走原生插入，行为不变。"""
    edit = make_edit("ab")
    caret(edit, 1)
    key(edit, key_code=Qt.Key.Key_Z, text="Z")
    assert edit.toPlainText() == "aZb", repr(edit.toPlainText())


# ---------------------------------------------------------- 垂直加光标与列选


@test
def test_down_moves_every_cursor() -> None:
    """有副光标时，方向键要移动所有光标，而不只是主光标。"""
    edit = make_edit("aaaa\nbbbb\ncccc\ndddd")
    caret(edit, 1)
    edit.add_cursor_at(6)
    edit.add_cursor_at(11)
    key(edit, key_code=Qt.Key.Key_Down)
    # 三个光标各下行一行，均保持第 1 列
    assert edit.textCursor().position() == 6, edit.textCursor().position()
    assert extra_positions(edit) == [11, 16], extra_positions(edit)


@test
def test_up_moves_every_cursor() -> None:
    """有副光标时，向上方向键同样移动所有光标。"""
    edit = make_edit("aaaa\nbbbb\ncccc\ndddd")
    caret(edit, 6)
    edit.add_cursor_at(11)
    key(edit, key_code=Qt.Key.Key_Up)
    assert edit.textCursor().position() == 1, edit.textCursor().position()
    assert extra_positions(edit) == [6], extra_positions(edit)


@test
def test_left_right_move_every_cursor() -> None:
    """左右方向键也要同时移动所有光标。"""
    edit = make_edit("abc\ndef")
    caret(edit, 1)
    edit.add_cursor_at(5)
    key(edit, key_code=Qt.Key.Key_Right)
    assert edit.textCursor().position() == 2, edit.textCursor().position()
    assert extra_positions(edit) == [6], extra_positions(edit)
    key(edit, key_code=Qt.Key.Key_Left)
    assert edit.textCursor().position() == 1, edit.textCursor().position()
    assert extra_positions(edit) == [5], extra_positions(edit)


@test
def test_down_keeps_cursor_column_across_uneven_lines() -> None:
    """下行长短不一时，各光标被夹到本行行尾，不会跑到别的行。"""
    edit = make_edit("long line\nab\nx")
    caret(edit, 6)
    edit.add_cursor_at(10)
    key(edit, key_code=Qt.Key.Key_Down)
    # 第二行只有 "ab"（位置 10、11，换行符在 12），第 6 列放不下，夹到行尾 12
    assert edit.textCursor().position() == 12, edit.textCursor().position()
    # 副光标本来在第二行行首（第 0 列），下行到第三行行首 13
    assert extra_positions(edit) == [13], extra_positions(edit)


@test
def test_home_end_move_every_cursor() -> None:
    """Home/End 也要同时作用于所有光标。"""
    edit = make_edit("aaaa\nbbbb")
    caret(edit, 2)
    edit.add_cursor_at(7)
    key(edit, key_code=Qt.Key.Key_End)
    assert edit.textCursor().position() == 4, edit.textCursor().position()
    assert extra_positions(edit) == [9], extra_positions(edit)


@test
def test_shift_down_extends_every_selection() -> None:
    """Shift+方向键要扩展所有选区的终点，而不只主光标。"""
    edit = make_edit("aaaa\nbbbb\ncccc")
    caret(edit, 1)
    edit.add_cursor_at(6)
    key(edit, key_code=Qt.Key.Key_Down, modifiers=Qt.KeyboardModifier.ShiftModifier)
    cur = edit.textCursor()
    assert (cur.anchor(), cur.position()) == (1, 6), (cur.anchor(), cur.position())
    ext = edit.extra_cursors[0]
    assert (ext.anchor(), ext.position()) == (6, 11), (ext.anchor(), ext.position())


@test
def test_add_cursor_above_and_below_keeps_column() -> None:
    """Ctrl+Alt+↑/↓ 在上一行/下一行同列加光标。"""
    edit = make_edit("alpha\nbravo\ncharlie")
    caret(edit, 2)
    edit.add_cursor_vertical(1)
    assert extra_positions(edit) == [8], extra_positions(edit)


@test
def test_add_cursor_vertical_up_works() -> None:
    """Ctrl+Alt+↑ 在上一行同列加光标。"""
    edit = make_edit("alpha\nbravo\ncharlie")
    caret(edit, 8)
    edit.add_cursor_vertical(-1)
    assert extra_positions(edit) == [2], extra_positions(edit)


@test
def test_add_cursor_vertical_clamps_to_short_line() -> None:
    """目标行比当前列短时，光标落在该行行尾。"""
    edit = make_edit("long line here\nab")
    caret(edit, 10)
    edit.add_cursor_vertical(1)
    # 第 1 行只有 "ab"，行尾位置是 17
    assert extra_positions(edit) == [17], extra_positions(edit)


@test
def test_add_cursor_vertical_at_first_line_is_noop() -> None:
    """第一行再往上加光标无效。"""
    edit = make_edit("alpha\nbravo")
    caret(edit, 2)
    edit.add_cursor_vertical(-1)
    assert edit.extra_cursor_count() == 0


@test
def test_column_selection_spans_each_line() -> None:
    """矩形列选在每一行产生一段等宽选区。"""
    edit = make_edit("abcd\nabcd\nabcd")
    edit.select_column(start_line=0, start_col=1, end_line=2, end_col=3)
    primary = edit.textCursor()
    assert primary.selectedText() == "bc", repr(primary.selectedText())
    extras = [(min(c.position(), c.anchor()), max(c.position(), c.anchor())) for c in edit.extra_cursors]
    assert extras == [(6, 8), (11, 13)], extras


@test
def test_column_selection_skips_short_lines_gracefully() -> None:
    """短行上的列选区被裁剪到行尾，不越界。"""
    edit = make_edit("abcd\nab\nabcd")
    edit.select_column(start_line=0, start_col=1, end_line=2, end_col=3)
    primary = edit.textCursor()
    assert primary.selectedText() == "bc", repr(primary.selectedText())
    extras = [c.selectedText() for c in edit.extra_cursors]
    assert extras == ["b", "bc"], extras


# ------------------------------------------------------- 行操作与快捷键分发


CTRL = Qt.KeyboardModifier.ControlModifier
CTRL_SHIFT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
CTRL_ALT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier


@test
def test_ctrl_d_adds_next_match_through_key_event() -> None:
    """Ctrl+D 经按键分发选中下一个相同内容。"""
    edit = make_edit("ab cd ab")
    select_word_at(edit, 0, 2)
    key(edit, key_code=Qt.Key.Key_D, modifiers=CTRL, text="\x04")
    assert edit.extra_cursor_count() == 1, extra_positions(edit)


@test
def test_ctrl_shift_l_selects_all_matches_through_key_event() -> None:
    """Ctrl+Shift+L 经按键分发全选相同内容。"""
    edit = make_edit("ab cd ab ab")
    select_word_at(edit, 0, 2)
    key(edit, key_code=Qt.Key.Key_L, modifiers=CTRL_SHIFT, text="\x0c")
    assert edit.extra_cursor_count() == 2, extra_positions(edit)


@test
def test_ctrl_u_undoes_last_cursor_through_key_event() -> None:
    """Ctrl+U 经按键分发撤销最后一个副光标。"""
    edit = make_edit("ab cd ab ab")
    select_word_at(edit, 0, 2)
    edit.select_all_occurrences()
    assert edit.extra_cursor_count() == 2
    key(edit, key_code=Qt.Key.Key_U, modifiers=CTRL, text="\x15")
    assert edit.extra_cursor_count() == 1, extra_positions(edit)


@test
def test_ctrl_alt_down_adds_cursor_below_through_key_event() -> None:
    """Ctrl+Alt+↓ 经按键分发在下一行同列加光标。"""
    edit = make_edit("alpha\nbravo\ncharlie")
    caret(edit, 2)
    key(edit, key_code=Qt.Key.Key_Down, modifiers=CTRL_ALT)
    assert extra_positions(edit) == [8], extra_positions(edit)


@test
def test_delete_line_keeps_column() -> None:
    """Ctrl+Shift+K 删除整行后，光标落到「替代行的同一列」。

    VS Code 语义：光标保持列位置，而不是跳到行首。
    根因：旧实现 ``cur.setPosition(min(start, ...))`` 直接落到被删区域
    起点，也就是第 0 列——用户看到的就是「光标跑到了下一行行首」。
    """
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 5)  # 第 1 行第 1 列
    edit.delete_line()
    assert edit.toPlainText() == "one\nthree", repr(edit.toPlainText())
    cur = edit.textCursor()
    block = edit.document().findBlock(cur.position())
    assert block.blockNumber() == 1, block.blockNumber()
    assert cur.position() - block.position() == 1, (
        cur.position() - block.position(),
    )


@test
def test_delete_line_keeps_column_when_it_is_not_zero() -> None:
    """列位置为 2 时也要保留，不能只对第 0 列碰巧正确。"""
    edit = make_edit("one\ntwo\nthreefour")
    caret(edit, 6)  # 第 1 行第 2 列
    edit.delete_line()
    assert edit.toPlainText() == "one\nthreefour", repr(edit.toPlainText())
    cur = edit.textCursor()
    block = edit.document().findBlock(cur.position())
    assert block.blockNumber() == 1, block.blockNumber()
    assert cur.position() - block.position() == 2, (
        cur.position() - block.position(),
    )


@test
def test_delete_line_column_clamped_on_last_line() -> None:
    """删掉最后一行时列位置要夹到剩余行长度内，不能越界。"""
    edit = make_edit("one\ntwo")
    caret(edit, 5)  # 第 1 行第 1 列
    edit.delete_line()
    assert edit.toPlainText() == "one", repr(edit.toPlainText())
    cur = edit.textCursor()
    block = edit.document().findBlock(cur.position())
    assert block.blockNumber() == 0, block.blockNumber()
    assert cur.position() - block.position() == 1, (
        cur.position() - block.position(),
    )


@test
def test_duplicate_line_down_keeps_column() -> None:
    """Shift+Alt+↓ 复制到下方后，光标落在副本的同一列。

    根因：旧实现插完固定 ``movePosition(NextCharacter)``，于是永远停在
    第 1 列——用户看到的就是「跳到了第一个字符后面」。
    """
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 6)  # 第 1 行第 2 列
    edit.duplicate_line(1)
    assert edit.toPlainText() == "one\ntwo\ntwo\nthree", repr(edit.toPlainText())
    cur = edit.textCursor()
    block = edit.document().findBlock(cur.position())
    assert block.blockNumber() == 2, block.blockNumber()
    assert cur.position() - block.position() == 2, (
        cur.position() - block.position(),
    )


@test
def test_duplicate_line_up_keeps_column() -> None:
    """Shift+Alt+↑ 复制到上方后，光标落在副本的同一列。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 6)  # 第 1 行第 2 列
    edit.duplicate_line(-1)
    assert edit.toPlainText() == "one\ntwo\ntwo\nthree", repr(edit.toPlainText())
    cur = edit.textCursor()
    block = edit.document().findBlock(cur.position())
    assert block.blockNumber() == 1, block.blockNumber()
    assert cur.position() - block.position() == 2, (
        cur.position() - block.position(),
    )


@test
def test_duplicate_line_column_zero_stays_zero() -> None:
    """第 0 列复制后仍停在副本行首（不能又被 NextCharacter 推一格）。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 4)  # 第 1 行第 0 列
    edit.duplicate_line(1)
    cur = edit.textCursor()
    block = edit.document().findBlock(cur.position())
    assert block.blockNumber() == 2, block.blockNumber()
    assert cur.position() - block.position() == 0, (
        cur.position() - block.position(),
    )


@test
def test_delete_line_removes_current_line_with_its_newline() -> None:
    """Ctrl+Shift+K 删除整行（含换行符）。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 5)
    edit.delete_line()
    assert edit.toPlainText() == "one\nthree", repr(edit.toPlainText())


@test
def test_delete_line_on_last_line_removes_preceding_newline() -> None:
    """删除最后一行时不会留下多余空行。"""
    edit = make_edit("one\ntwo")
    caret(edit, 5)
    edit.delete_line()
    assert edit.toPlainText() == "one", repr(edit.toPlainText())


@test
def test_duplicate_line_copies_line_below() -> None:
    """Shift+Alt+↓ 向下复制当前行，光标留在新行同列。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 5)
    edit.duplicate_line(1)
    assert edit.toPlainText() == "one\ntwo\ntwo\nthree", repr(edit.toPlainText())
    assert edit.textCursor().position() == 9, edit.textCursor().position()


@test
def test_move_line_down_swaps_with_next_line() -> None:
    """Alt+↓ 把当前行与下一行交换。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 1)
    edit.move_line(1)
    assert edit.toPlainText() == "two\none\nthree", repr(edit.toPlainText())


@test
def test_move_line_up_swaps_with_previous_line() -> None:
    """Alt+↑ 把当前行与上一行交换。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 5)
    edit.move_line(-1)
    assert edit.toPlainText() == "two\none\nthree", repr(edit.toPlainText())


@test
def test_toggle_line_comment_prefixes_every_selected_line() -> None:
    """Ctrl+/ 给选中的每一行加行注释前缀；再按一次取消。"""
    edit = make_edit("a\nb\nc")
    edit.select_column(0, 0, 2, 1)
    assert edit.toggle_line_comment("#") is True
    assert edit.toPlainText() == "#a\n#b\n#c", repr(edit.toPlainText())
    assert edit.toggle_line_comment("#") is False
    assert edit.toPlainText() == "a\nb\nc", repr(edit.toPlainText())


@test
def test_toggle_line_comment_skips_already_commented_lines() -> None:
    """混合状态下按一次是「全部加注释」，而不是逐行取反。"""
    edit = make_edit("#a\nb")
    edit.select_column(0, 0, 1, 1)
    assert edit.toggle_line_comment("#") is True
    assert edit.toPlainText() == "#a\n#b", repr(edit.toPlainText())


# -------------------------------------- 行操作：多光标各自成块（回归用例）


def spot(edit: MultiCursorTextEdit, position: int) -> tuple[int, str, int]:
    """把字符位置换算成 (行号, 该行文本, 列号)，便于断言「光标在哪一行」。"""
    block = edit.document().findBlock(position)
    return (block.blockNumber(), block.text(), position - block.position())


def primary_spot(edit: MultiCursorTextEdit) -> tuple[int, str, int]:
    return spot(edit, edit.textCursor().position())


def extra_spots(edit: MultiCursorTextEdit) -> list[tuple[int, str, int]]:
    return sorted(spot(edit, cur.position()) for cur in edit.extra_cursors)


def place_carets(edit: MultiCursorTextEdit, positions: list[int]) -> None:
    """主光标放第一个位置，其余加成副光标。"""
    caret(edit, positions[0])
    for position in positions[1:]:
        edit.add_cursor_at(position)


@test
def test_move_line_up_treats_each_cursor_line_as_its_own_block() -> None:
    """Alt+↑ 多光标：每个光标只移动自己那一行，中间的行必须原地不动。

    根因回归：``_selected_line_range()`` 把所有光标行压成 ``[min, max]``，
    于是光标在 line1 与 line4 时，line2 也被当成选区一部分一起重排。
    """
    edit = make_edit("aa1\nbb2\ncc3\ndd4\nee5\nff6\ngg7\n")
    place_carets(edit, [5, 17])  # line1 col1, line4 col1
    assert edit.move_line(-1) is True
    assert edit.toPlainText() == "bb2\naa1\ncc3\nee5\ndd4\nff6\ngg7\n", repr(
        edit.toPlainText()
    )
    assert primary_spot(edit) == (0, "bb2", 1), primary_spot(edit)
    assert extra_spots(edit) == [(3, "ee5", 1)], extra_spots(edit)


@test
def test_move_line_down_treats_each_cursor_line_as_its_own_block() -> None:
    """Alt+↓ 多光标：各自与下一行交换，互不干扰。"""
    edit = make_edit("aa1\nbb2\ncc3\ndd4\nee5\n")
    place_carets(edit, [5, 13])  # line1 col1, line3 col1
    assert edit.move_line(1) is True
    assert edit.toPlainText() == "aa1\ncc3\nbb2\nee5\ndd4\n", repr(edit.toPlainText())
    assert primary_spot(edit) == (2, "bb2", 1), primary_spot(edit)
    assert extra_spots(edit) == [(4, "dd4", 1)], extra_spots(edit)


@test
def test_move_line_up_skips_only_the_cursor_already_on_first_line() -> None:
    """最上面的光标已在第 0 行时只跳过它，其余光标照常上移。"""
    edit = make_edit("aa1\nbb2\ncc3\ndd4\n")
    place_carets(edit, [1, 9])  # line0 col1, line2 col1
    assert edit.move_line(-1) is True
    assert edit.toPlainText() == "aa1\ncc3\nbb2\ndd4\n", repr(edit.toPlainText())
    assert primary_spot(edit) == (0, "aa1", 1), primary_spot(edit)
    assert extra_spots(edit) == [(1, "cc3", 1)], extra_spots(edit)


@test
def test_move_line_up_returns_false_when_no_cursor_can_move() -> None:
    """全都在第 0 行（单行文档）时命令应报告未生效。"""
    edit = make_edit("only")
    caret(edit, 2)
    assert edit.move_line(-1) is False


@test
def test_delete_line_relocates_every_cursor_to_its_own_replacement_line() -> None:
    """Ctrl+Shift+K 多光标：每个光标落到自己那块的接替行，保留列位置。"""
    edit = make_edit("aa1\nbb2\ncc3\ndd4\nee5\n")
    place_carets(edit, [5, 13])  # line1 col1, line3 col1
    assert edit.delete_line() is True
    assert edit.toPlainText() == "aa1\ncc3\nee5\n", repr(edit.toPlainText())
    assert primary_spot(edit) == (1, "cc3", 1), primary_spot(edit)
    assert extra_spots(edit) == [(2, "ee5", 1)], extra_spots(edit)


@test
def test_duplicate_line_down_puts_each_cursor_into_its_own_copy() -> None:
    """Shift+Alt+↓ 多光标：每个光标进入自己那一行的副本。"""
    edit = make_edit("aa1\nbb2\ncc3\n")
    place_carets(edit, [1, 9])  # line0 col1, line2 col1
    assert edit.duplicate_line(1) is True
    assert edit.toPlainText() == "aa1\naa1\nbb2\ncc3\ncc3\n", repr(edit.toPlainText())
    assert primary_spot(edit) == (1, "aa1", 1), primary_spot(edit)
    assert extra_spots(edit) == [(4, "cc3", 1)], extra_spots(edit)


@test
def test_duplicate_line_up_puts_each_cursor_into_its_own_copy() -> None:
    """Shift+Alt+↑ 多光标：副本插在各自行之前，光标进入副本。"""
    edit = make_edit("aa1\nbb2\ncc3\n")
    place_carets(edit, [1, 9])  # line0 col1, line2 col1
    assert edit.duplicate_line(-1) is True
    assert edit.toPlainText() == "aa1\naa1\nbb2\ncc3\ncc3\n", repr(edit.toPlainText())
    assert primary_spot(edit) == (0, "aa1", 1), primary_spot(edit)
    assert extra_spots(edit) == [(3, "cc3", 1)], extra_spots(edit)


@test
def test_toggle_line_comment_leaves_lines_between_cursors_alone() -> None:
    """Ctrl+/ 多光标：只注释各光标所在行，中间行不被波及。"""
    edit = make_edit("aa1\nbb2\ncc3\n")
    place_carets(edit, [1, 9])  # line0 col1, line2 col1
    assert edit.toggle_line_comment("#") is True
    assert edit.toPlainText() == "#aa1\nbb2\n#cc3\n", repr(edit.toPlainText())
    # 加前缀后列位置跟着右移一格，与 VS Code 一致
    assert primary_spot(edit) == (0, "#aa1", 2), primary_spot(edit)
    assert extra_spots(edit) == [(2, "#cc3", 2)], extra_spots(edit)


@test
def test_line_operation_with_a_multiline_selection_still_covers_it_as_one_block(
) -> None:
    """单个光标跨行选中时，仍按一整块处理（不能被拆成逐行）。"""
    edit = make_edit("aa1\nbb2\ncc3\ndd4\n")
    cur = edit.textCursor()
    cur.setPosition(1)
    cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)  # 覆盖第 0..2 行
    edit.setTextCursor(cur)
    assert edit.toggle_line_comment("#") is True
    assert edit.toPlainText() == "#aa1\n#bb2\n#cc3\ndd4\n", repr(edit.toPlainText())


@test
def test_delete_line_with_a_multiline_selection_moves_caret_to_replacement() -> None:
    """跨行选中整块后删除：光标落到替身行的块首，不是逐行的偏移。"""
    edit = make_edit("aa1\nbb2\ncc3\ndd4\n")
    cur = edit.textCursor()
    cur.setPosition(1)
    cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)  # 覆盖第 0~2 行
    edit.setTextCursor(cur)
    assert edit.delete_line() is True
    assert "dd4\n" == edit.toPlainText(), repr(edit.toPlainText())
    # 光标是原先的 position（第 2 行第 3 列），删除后落回替身行同一列
    assert primary_spot(edit) == (0, "dd4", 3), primary_spot(edit)


@test
def test_move_line_down_with_a_multiline_selection_moves_whole_block() -> None:
    """跨行选中后 Alt+↓：整块下移一行，光标随块一起下移并保持位置。"""
    edit = make_edit("aa1\nbb2\ncc3\ndd4\n")
    cur = edit.textCursor()
    cur.setPosition(1)
    cur.setPosition(7, QTextCursor.MoveMode.KeepAnchor)  # 覆盖第 0~1 行
    edit.setTextCursor(cur)
    assert edit.move_line(1) is True
    assert "cc3\naa1\nbb2\ndd4\n" == edit.toPlainText(), repr(edit.toPlainText())
    # position 端（第 1 行第 3 列）随块下移一行
    assert primary_spot(edit) == (2, "bb2", 3), primary_spot(edit)


@test
def test_every_line_operation_is_undone_by_a_single_ctrl_z() -> None:
    """多光标下的行操作必须只占撤销栈的一步。

    实现用 ``beginEditBlock``/``endEditBlock`` 把每个光标的编辑包成一个
    块；若某个操作把光标编辑留在块外，用户就要连按好几次 Ctrl+Z 才能回到
    操作前，是典型的「撤销失灵」体验。
    """
    body = "aa1\nbb2\ncc3\ndd4\nee5\nff6\ngg7\n"
    operations = (
        ("move_line(-1)", lambda e: e.move_line(-1)),
        ("move_line(1)", lambda e: e.move_line(1)),
        ("delete_line", lambda e: e.delete_line()),
        ("duplicate_line(1)", lambda e: e.duplicate_line(1)),
        ("duplicate_line(-1)", lambda e: e.duplicate_line(-1)),
        ("toggle_line_comment", lambda e: e.toggle_line_comment("#")),
    )
    for name, operation in operations:
        edit = make_edit(body)
        place_carets(edit, [5, 13, 21])  # 第 1、3、5 行
        operation(edit)
        changed = edit.toPlainText()
        assert changed != body, (name, "操作没有生效")
        edit.undo()
        assert edit.toPlainText() == body, (name, repr(edit.toPlainText()))



# ------------------------------------------------------------- 查找（Ctrl+F）


@test
def test_find_next_jumps_to_next_match_after_cursor() -> None:
    """find_next 从光标处向后找下一个匹配。"""
    edit = make_edit("ab xx ab yy ab")
    caret(edit, 3)
    assert edit.find_next("ab") is True
    assert min(
        edit.textCursor().position(), edit.textCursor().anchor()
    ) == 6, edit.textCursor().position()


@test
def test_find_next_wraps_to_document_start() -> None:
    """搜索到文档末尾后回绕到开头。"""
    edit = make_edit("ab xx ab")
    caret(edit, 8)
    assert edit.find_next("ab") is True
    assert min(edit.textCursor().position(), edit.textCursor().anchor()) == 0


@test
def test_find_next_without_match_returns_false_and_keeps_cursor() -> None:
    """找不到匹配时返回 False，且不改动光标。"""
    edit = make_edit("abc")
    caret(edit, 1)
    assert edit.find_next("zzz") is False
    assert edit.textCursor().position() == 1


@test
def test_find_previous_works_backwards() -> None:
    """find_previous 从光标之前找上一个匹配。"""
    edit = make_edit("ab xx ab")
    caret(edit, 8)
    assert edit.find_next("ab", backward=True) is True
    assert min(edit.textCursor().position(), edit.textCursor().anchor()) == 6


@test
def test_find_next_selects_the_match_text() -> None:
    """命中后匹配文本被选中，便于直接替换。"""
    edit = make_edit("hello world")
    caret(edit, 0)
    edit.find_next("world")
    assert edit.textCursor().selectedText() == "world"


@test
def test_left_click_clears_extra_cursors() -> None:
    """普通左键单击应收敛回单光标（与 VS Code 一致）。

    左键是「我要在这里放一个光标」的语义：点完只应该剩下这一根，
    否则接下来输入会同时写进多个位置。
    """
    edit = make_edit("aaa\nbbb\nccc")
    stub_position_lookup(edit, {0: 0, 1: 4, 2: 8})
    caret(edit, 0)
    edit.add_cursor_at(4)
    edit.add_cursor_at(8)
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()

    mouse(edit, QEvent.Type.MouseButtonPress, 10, 1, Qt.KeyboardModifier.NoModifier)
    mouse(edit, QEvent.Type.MouseButtonRelease, 10, 1, Qt.KeyboardModifier.NoModifier)
    assert edit.extra_cursor_count() == 0, edit.extra_cursor_count()
    assert edit.cursorWidth() == 1, "收敛后 Qt 光标应恢复"


def point_for_position(edit: MultiCursorTextEdit, position: int) -> tuple[int, int]:
    """把文档位置换成视口内的真实像素点。

    不能用 ``stub_position_lookup`` 去验证主光标行为：
    ``QTextEdit.mousePressEvent`` 的基类内部是 C++ 直调
    ``cursorForPosition``，不经过 Python 覆写，桩完全不生效。
    涉及 Qt 默认处理的断言必须用真字体度量算出的坐标。
    """
    cur = QTextCursor(edit.document())
    cur.setPosition(position)
    rect = edit.cursorRect(cur)
    return rect.left() + 1, rect.top() + rect.height() // 2


@test
def test_left_click_moves_primary_caret_to_click_point() -> None:
    """清副光标的同时，主光标应落到点击位置（走 Qt 默认处理）。"""
    edit = make_edit("aaa\nbbb\nccc")
    caret(edit, 0)
    edit.add_cursor_at(8)

    x, y = point_for_position(edit, 5)
    mouse(edit, QEvent.Type.MouseButtonPress, x, y, Qt.KeyboardModifier.NoModifier)
    mouse(edit, QEvent.Type.MouseButtonRelease, x, y, Qt.KeyboardModifier.NoModifier)
    APP.processEvents()
    assert edit.extra_cursor_count() == 0
    assert edit.textCursor().position() == 5, edit.textCursor().position()


@test
def test_left_click_without_extra_cursors_keeps_selection() -> None:
    """没有副光标时左键拖选不受影响，不能因清理而丢掉选区。"""
    edit = make_edit("hello world")
    caret(edit, 0)

    x0, y0 = point_for_position(edit, 0)
    x1, y1 = point_for_position(edit, 5)
    mouse(edit, QEvent.Type.MouseButtonPress, x0, y0, Qt.KeyboardModifier.NoModifier)
    drag(edit, x1, y1)
    mouse(edit, QEvent.Type.MouseButtonRelease, x1, y1, Qt.KeyboardModifier.NoModifier)
    APP.processEvents()
    assert edit.extra_cursor_count() == 0
    assert edit.textCursor().hasSelection() is True
    assert edit.textCursor().selectedText() == "hello", edit.textCursor().selectedText()


@test
def test_alt_click_does_not_clear_existing_cursors() -> None:
    """Alt+点击是「加到已有光标集合里」，绝不能先清空。"""
    edit = make_edit("aaa\nbbb\nccc")
    stub_position_lookup(edit, {0: 0, 1: 4, 2: 8})
    caret(edit, 0)
    edit.add_cursor_at(4)
    assert edit.extra_cursor_count() == 1

    mouse(edit, QEvent.Type.MouseButtonPress, 10, 2, Qt.KeyboardModifier.AltModifier)
    mouse(edit, QEvent.Type.MouseButtonRelease, 10, 2, Qt.KeyboardModifier.AltModifier)
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()


@test
def test_middle_click_leaves_extra_cursors_alone() -> None:
    """中键（粘贴）不是选择语义，不应清副光标。"""
    edit = make_edit("aaa\nbbb")
    caret(edit, 0)
    edit.add_cursor_at(4)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    edit.mousePressEvent(ev)
    assert edit.extra_cursor_count() == 1, edit.extra_cursor_count()


@test
def test_ctrl_f_opens_find_bar_in_client_box() -> None:
    """Ctrl+F 打开查找栏并聚焦输入框。"""
    edit = make_edit("hello")
    key(edit, key_code=Qt.Key.Key_F, modifiers=CTRL, text="\x06")
    assert edit.find_bar.isVisible() is True
    assert edit.find_bar.line_edit.hasFocus() is True


def _open_find_bar(edit: MultiCursorTextEdit) -> None:
    key(edit, key_code=Qt.Key.Key_F, modifiers=CTRL, text="\x06")
    APP.processEvents()
    assert edit.find_bar.isVisible() is True


@test
def test_find_bar_does_not_cover_text() -> None:
    """查找栏不能盖住正文，否则底部/顶部几行被遮住读不到。

    实现用 ``setViewportMargins`` 给查找栏留出垂直空间，视口整体下移，
    正文从查找栏下方开始排。

    不以 0 为基准：QTextEdit 自带 2px 边框，未开查找栏时视口顶就是 2。
    只看「开了之后是否至少下移了查找栏的高度」。
    """
    edit = make_edit("\n".join(f"line{i}" for i in range(40)))
    baseline_top = edit.viewport().geometry().top()
    baseline_h = edit.viewport().height()

    _open_find_bar(edit)
    bar_h = edit.find_bar.height()
    assert bar_h > 0, bar_h
    top = edit.viewport().geometry().top()
    assert top >= baseline_top + bar_h, (top, baseline_top, bar_h)
    # 正文区被压矮，而不是被覆盖（覆盖时高度不变）
    assert edit.viewport().height() <= baseline_h - bar_h + 1, (
        edit.viewport().height(),
        baseline_h,
        bar_h,
    )
    # 查找栏与视口不重叠
    assert edit.find_bar.geometry().bottom() < top, (
        edit.find_bar.geometry(),
        edit.viewport().geometry(),
    )


@test
def test_closing_find_bar_restores_full_viewport() -> None:
    """关掉查找栏后必须把边距清零，不能永久留白。"""
    edit = make_edit("\n".join(f"line{i}" for i in range(40)))
    baseline_top = edit.viewport().geometry().top()
    baseline_h = edit.viewport().height()

    _open_find_bar(edit)
    assert edit.viewport().height() < baseline_h, "查找栏应压矮正文区"

    edit.find_bar.close()
    APP.processEvents()
    assert edit.find_bar.isVisible() is False
    assert edit.viewport().geometry().top() == baseline_top, edit.viewport().geometry()
    assert edit.viewport().height() == baseline_h, (
        edit.viewport().height(),
        baseline_h,
    )


@test
def test_find_bar_tracks_editor_resize() -> None:
    """编辑器改尺寸时查找栏要跟着变宽。

    宽度对齐「正文视口」而不是整个编辑器：编辑器右侧有垂直滚动条，
    全宽会把它顶部盖住导致拖不动。
    """
    edit = make_edit("hello")
    _open_find_bar(edit)
    assert edit.find_bar.width() == edit.viewport().width(), (
        edit.find_bar.width(),
        edit.viewport().width(),
    )
    edit.resize(700, 400)
    APP.processEvents()
    assert edit.find_bar.width() == edit.viewport().width(), (
        edit.find_bar.width(),
        edit.viewport().width(),
    )
    # 不能盖到右侧滚动条：宽度与正文视口对齐，而不是霸占整个编辑器
    assert edit.find_bar.width() <= edit.width(), (
        edit.find_bar.width(),
        edit.width(),
    )


# ------------------------------------------------- 鼠标：右击应退出多光标模式


def right_click(edit: MultiCursorTextEdit, x: int = 30, y: int = 0) -> None:
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(float(x), float(y)),
        QPointF(float(x), float(y)),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    edit.mousePressEvent(ev)


@test
def test_right_click_clears_extra_cursors() -> None:
    """右击弹出上下文菜单时应收敛回单光标。

    用户心智：右击 = 「回到常规操作」。若此时还留着一排副光标，
    接下来输入会同时写进多个位置，是很危险的意外。
    """
    edit = make_edit("aaa\nbbb\nccc")
    caret(edit, 0)
    edit.add_cursor_at(4)
    edit.add_cursor_at(8)
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()

    right_click(edit)
    assert edit.extra_cursor_count() == 0, edit.extra_cursor_count()
    assert edit.cursorWidth() == 1, "收敛后 Qt 光标应恢复"


@test
def test_right_click_without_extra_cursors_is_harmless() -> None:
    """没有副光标时右击不能出错，也不能改变主光标。"""
    edit = make_edit("aaa\nbbb")
    caret(edit, 4)
    right_click(edit)
    assert edit.extra_cursor_count() == 0
    assert edit.textCursor().position() == 4, edit.textCursor().position()


@test
def test_right_click_keeps_primary_caret_position() -> None:
    """清副光标不影响主光标位置——用户可能只是想弹个菜单。"""
    edit = make_edit("aaa\nbbb\nccc")
    caret(edit, 5)
    edit.add_cursor_at(9)
    right_click(edit)
    assert edit.extra_cursor_count() == 0
    assert edit.textCursor().position() == 5, edit.textCursor().position()


# --------------------------------------------------------- 鼠标：Alt 加光标与列选


def mouse(edit: MultiCursorTextEdit, kind, x: int, y: int, modifiers) -> None:
    ev = QMouseEvent(
        kind,
        QPointF(float(x), float(y)),
        QPointF(float(x), float(y)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        modifiers,
    )
    if kind == QEvent.Type.MouseButtonPress:
        edit.mousePressEvent(ev)
    elif kind == QEvent.Type.MouseButtonRelease:
        edit.mouseReleaseEvent(ev)
    else:
        edit.mouseMoveEvent(ev)


def drag(edit: MultiCursorTextEdit, x: int, y: int) -> None:
    """左键按住状态下的拖动，buttons 必须带 LeftButton 才算拖选。"""
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(float(x), float(y)),
        QPointF(float(x), float(y)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    edit.mouseMoveEvent(ev)


def stub_position_lookup(edit: MultiCursorTextEdit, line_starts: dict[int, int]) -> None:
    """离屏模式下字体度量不可靠，用行首位置表代替 cursorForPosition。

    像素坐标按 (行 y -> 行首位置, 每 10px 一列) 换算，保证断言确定。
    """

    def fake_cursor_for_position(point):  # noqa: ANN001 - QPoint
        base = line_starts.get(int(point.y()), line_starts[max(line_starts)])
        cur = QTextCursor(edit.document())
        cur.setPosition(min(base + int(point.x()) // 10, edit.document().characterCount() - 1))
        return cur

    edit.cursorForPosition = fake_cursor_for_position  # type: ignore[method-assign]


@test
def test_alt_click_adds_cursor() -> None:
    """Alt+点击在点击处加一个副光标。"""
    edit = make_edit("hello\nworld")
    stub_position_lookup(edit, {0: 0, 1: 6})
    mouse(edit, QEvent.Type.MouseButtonPress, 40, 0, Qt.KeyboardModifier.AltModifier)
    mouse(edit, QEvent.Type.MouseButtonRelease, 40, 0, Qt.KeyboardModifier.AltModifier)
    assert edit.extra_cursor_count() == 1, edit.extra_cursor_count()
    assert extra_positions(edit) == [4], extra_positions(edit)


@test
def test_alt_click_twice_at_same_spot_removes_cursor() -> None:
    """同一位置再次 Alt+点击会移除该副光标。"""
    edit = make_edit("hello\nworld")
    stub_position_lookup(edit, {0: 0, 1: 6})
    for _ in range(2):
        mouse(edit, QEvent.Type.MouseButtonPress, 40, 0, Qt.KeyboardModifier.AltModifier)
        mouse(edit, QEvent.Type.MouseButtonRelease, 40, 0, Qt.KeyboardModifier.AltModifier)
    assert edit.extra_cursor_count() == 0, edit.extra_cursor_count()


@test
def test_ctrl_alt_up_and_down_multi_line_keeps_column() -> None:
    """连续 Ctrl+Alt+↓ 在多行同列累积光标。"""
    edit = make_edit("abcd\nefgh\nijkl")
    caret(edit, 2)
    edit.add_cursor_vertical(1)
    edit.add_cursor_vertical(1)
    assert extra_positions(edit) == [7, 12], extra_positions(edit)


# ------------------------------------------------------- Alt 拖拽矩形列选


@test
def test_alt_drag_selects_rectangular_column() -> None:
    """按住 Alt 拖拽产生矩形列选区，每行等宽且非空。

    列选是**像素**概念，所以这里用真实字体度量算出字符边界对应的 x，
    再拖出 [x1, x2] 这段像素区间；断言每行选中的字符一样。
    """
    edit = make_edit("abcdef\nabcdef\nabcdef")
    line = edit.document().begin().layout().lineAt(0)
    margin = edit.document().documentMargin()
    x1 = int(line.cursorToX(1)[0] + margin)
    x2 = int(line.cursorToX(3)[0] + margin)
    y0 = int(margin + 2)
    y1 = int(margin + 16)
    mouse(edit, QEvent.Type.MouseButtonPress, x1, y0, Qt.KeyboardModifier.AltModifier)
    mouse(edit, QEvent.Type.MouseMove, x2, y1, Qt.KeyboardModifier.AltModifier)
    mouse(edit, QEvent.Type.MouseButtonRelease, x2, y1, Qt.KeyboardModifier.AltModifier)
    assert edit.extra_cursor_count() == 1, edit.extra_cursor_count()
    widths = {len(edit.textCursor().selectedText())}
    widths |= {len(c.selectedText()) for c in edit.extra_cursors}
    assert widths == {2}, widths
    assert edit.textCursor().selectedText() == "bc", edit.textCursor().selectedText()


def selection_pixel_rows(img: QImage) -> list[int]:
    """找出含有「选区色」像素的行号。

    ``SELECTION_COLOR`` 是 (38,79,120,160)，半透明叠在深色底上约为
    (35,60,86)：蓝分量明显高于红，而底色/白色文字/光标色都不是这种蓝，
    所以用 ``blue > red + 30`` 就能把它从背景里区分出来。
    """
    rows: list[int] = []
    for y in range(img.height()):
        hit = False
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 32 and c.blue() > c.red() + 30 and c.blue() > 45:
                hit = True
                break
        if hit:
            rows.append(y)
    return rows


def text_pixels_inside(
    img: QImage,
    edit: MultiCursorTextEdit,
    rect: QRect,
    margin: int = 1,
) -> int:
    """统计 ``rect`` 内部「字形色」像素数。

    用来判断选区高亮有没有把文字盖住。注意字形颜色在选区内是
    **HighlightedText**（Qt 原生选区会把选中文字换成它，本主题白色），
    不是常规的 ``Text``——两者在这个主题里可能相同也可能不同，
    所以两个都算，任何一个可见都说明文字没被盖住。
    """
    targets = [
        edit.palette().color(QPalette.ColorRole.HighlightedText),
        edit.palette().color(QPalette.ColorRole.Text),
    ]
    n = 0
    x0 = max(0, rect.left() + margin)
    x1 = min(img.width(), rect.left() + rect.width() - margin)
    y0 = max(0, rect.top())
    y1 = min(img.height(), rect.top() + rect.height())
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = img.pixelColor(x, y)
            if c.alpha() <= 32:
                continue
            for target in targets:
                if (
                    abs(c.red() - target.red()) < 40
                    and abs(c.green() - target.green()) < 40
                    and abs(c.blue() - target.blue()) < 40
                ):
                    n += 1
                    break
    return n


def line_bands(edit: MultiCursorTextEdit) -> list[tuple[int, int]]:
    """每行的垂直区间 [top, bottom)，**视口坐标**。

    必须用 ``cursorRect`` 而不是 ``blockBoundingRect``：后者是文档坐标，
    文档滚动后会变成几千，与截图里的像素行号根本对不上。
    """
    doc = edit.document()
    bands = []
    for i in range(doc.blockCount()):
        block = doc.findBlockByNumber(i)
        cur = QTextCursor(doc)
        cur.setPosition(block.position())
        rect = edit.cursorRect(cur)
        height = max(1, rect.height())
        bands.append((rect.top(), rect.top() + height))
    return bands


@test
def test_column_selection_highlights_every_line() -> None:
    """矩形列选必须每行都画出选区，而不是只高亮一行。

    根因复现：``cursorRect(带选区的光标)`` 返回的是零宽矩形
    （如 ``QRect(25, 4, 0, 15)``），``fillRect`` 宽度 0 等于什么都没画。
    用户看到的唯一一行高亮其实是 Qt 自己画的主光标原生选区。

    按「行带」而不是按「像素行聚类」断言：离屏渲染的像素行并非逐行都有
    命中（隔几行才命中一次是正常的抗锯齿/采样结果），但每一行带都必须
    至少命中一个像素。
    """
    edit = make_edit("aaaaa\nbbbbb\nccccc\nddddd")
    edit.select_column(0, 1, 3, 3)
    APP.processEvents()
    assert edit.extra_cursor_count() == 3, edit.extra_cursor_count()

    rows = selection_pixel_rows(render_overlay(edit))
    assert rows, "一行选区都没画出来"

    bands = line_bands(edit)
    assert len(bands) == 4, bands
    covered = [any(top <= y < bottom for y in rows) for top, bottom in bands]
    assert all(covered), f"只有 {sum(covered)}/4 行带被高亮: {covered} (bands={bands}, rows={rows})"


@test
def test_column_selection_rect_is_not_zero_width() -> None:
    """每个副光标的选区矩形必须有宽度，否则画了也看不见。"""
    edit = make_edit("aaaaa\nbbbbb\nccccc")
    edit.select_column(0, 1, 2, 3)
    APP.processEvents()
    cursors = [edit.textCursor(), *edit.extra_cursors]
    assert len(cursors) == 3, len(cursors)
    for i, cur in enumerate(cursors):
        assert cur.hasSelection(), f"cursor{i} 没有选区"
        rects = edit.selection_rects(cur)
        assert rects, f"cursor{i} 算不出选区矩形"
        total_width = sum(r.width() for r in rects)
        assert total_width > 0, f"cursor{i} 选区总宽为 0: {rects}"


@test
def test_selection_rects_multiline_spans_one_rect_per_line() -> None:
    """跨行选区要拆成每行一个矩形，这样才能画成阶梯状而不是一整块。"""
    edit = make_edit("aaaaa\nbbbbb\nccccc")
    cur = edit.textCursor()
    cur.setPosition(1)
    cur.setPosition(13, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    APP.processEvents()

    rects = edit.selection_rects(edit.textCursor())
    assert len(rects) == 3, [str(r) for r in rects]
    tops = sorted({r.top() for r in rects})
    assert len(tops) == 3, f"三行应该有 3 个不同 y: {tops}"
    assert all(r.width() > 0 for r in rects), [str(r) for r in rects]
    # 首行从第 1 列到行尾、中间行整行、末行到第 1 列
    assert rects[0].width() < rects[1].width(), (
        rects[0].width(),
        rects[1].width(),
    )


@test
def test_single_line_selection_has_one_rect() -> None:
    """同一行的选区只应产生一个矩形。"""
    edit = make_edit("hello world")
    cur = edit.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    APP.processEvents()
    rects = edit.selection_rects(edit.textCursor())
    assert len(rects) == 1, [str(r) for r in rects]
    assert rects[0].width() > 0


@test
def test_column_selection_uses_qt_highlight_color_on_every_line() -> None:
    """四行选区必须是同一个颜色，不能主光标一行一个色。

    根因：Qt 会自动给主光标画原生选区（``palette Highlight``，本主题是
    青绿 (0,178,148)）；我们如果再用一个半透明的 ``SELECTION_COLOR``
    叠上去，主光标那一行就会变成两者的混合色，与副光标行明显不同——
    用户看到的就是「只高亮了一行」。

    正确做法：副光标也用 ``palette Highlight``，两边的颜色就完全一致。
    """
    edit = make_edit("\n".join("x" * 20 for _ in range(4)))
    edit.select_column(0, 1, 3, 8)
    APP.processEvents()
    assert edit.extra_cursor_count() == 3, edit.extra_cursor_count()

    img = render_overlay(edit)
    hl = edit.palette().color(QPalette.ColorRole.Highlight)

    def count_highlight(y0: int, y1: int) -> int:
        n = 0
        for y in range(max(0, y0), min(img.height(), y1)):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if (
                    abs(c.red() - hl.red()) <= 10
                    and abs(c.green() - hl.green()) <= 10
                    and abs(c.blue() - hl.blue()) <= 10
                ):
                    n += 1
        return n

    bands = line_bands(edit)
    assert len(bands) == 4, bands
    counts = [count_highlight(top, bottom) for top, bottom in bands]
    assert all(n > 0 for n in counts), (
        f"有行没有画成 Highlight 色: {counts}（Highlight={hl.getRgb()}）",
    )
    # 主光标行与副光标行应该是同一量级的覆盖量
    expected = (8 - 1) * 7  # 7 字符宽 × 行高 15 的大致像素数下界
    assert min(counts) > expected // 4, counts


@test
def test_selection_color_matches_qt_native_highlight() -> None:
    """副光标选区色必须等于 Qt 原生选区色，否则两类行颜色不一致。"""
    edit = make_edit("hello")
    assert edit.selection_color().getRgb() == edit.palette().color(
        QPalette.ColorRole.Highlight
    ).getRgb(), edit.selection_color().getRgb()


def selection_count_per_line(img: QImage, edit: MultiCursorTextEdit) -> list[int]:
    """返回每一行带内命中「Qt 原生选区色」的像素数。"""
    hl = edit.palette().color(QPalette.ColorRole.Highlight)
    counts: list[int] = []
    for top, bottom in line_bands(edit):
        n = 0
        for y in range(max(0, top), min(img.height(), bottom)):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if (
                    abs(c.red() - hl.red()) <= 10
                    and abs(c.green() - hl.green()) <= 10
                    and abs(c.blue() - hl.blue()) <= 10
                ):
                    n += 1
        counts.append(n)
    return counts


@test
def test_selection_highlight_survives_dark_caret_phase() -> None:
    """闪烁只该管竖线，选区高亮必须常亮。

    根因：相位判断被套在整个绘制上，灭相位时副光标的选区也一起消失，
    只剩 Qt 自己画的主光标原生选区——用户看到的就是「只高亮了一行」，
    而且是间歇性的（它每 530ms 才出现一次）。
    """
    edit = make_edit("\n".join("abcdefghij" for _ in range(4)))
    edit.select_column(0, 1, 3, 5)
    APP.processEvents()
    assert edit.extra_cursor_count() == 3, edit.extra_cursor_count()

    edit._caret_timer.stop()
    edit._caret_phase = True
    lit = selection_count_per_line(render_overlay(edit), edit)
    edit._caret_phase = False
    dark = selection_count_per_line(render_overlay(edit), edit)

    assert all(n > 0 for n in lit), f"亮相位有行没高亮: {lit}"
    assert all(n > 0 for n in dark), (
        f"灭相位选区被一起灭掉了（这就是只高亮一行的原因）: {dark}",
    )
    assert lit == dark, f"选区高亮量不该随相位变化: lit={lit} dark={dark}"


@test
def test_caret_lines_hidden_in_dark_phase_but_selection_kept() -> None:
    """灭相位：竖线消失，但选区仍在。

    用 ``paint_carets_at_phase`` 画到空图上，而不是抓真实屏幕：
    屏幕上有字形本身（也是 palette Text 色），紧贴光标的字形边缘会被
    误统计成「竖线还在」，分不清是被画出来的还是本来就有的。

    选区本身已改由 ``setExtraSelections()`` 交给 Qt 排版层绘制（那样
    文字才不会被盖住），所以 ``paintEvent`` 里**不再**该画出任何选区像素。
    """
    edit = make_edit("abcdefghij")
    cur = edit.textCursor()
    cur.setPosition(1)
    cur.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    APP.processEvents()

    target = edit.palette().color(QPalette.ColorRole.Text)
    hl = edit.palette().color(QPalette.ColorRole.Highlight)

    def count(img: QImage, color) -> int:  # noqa: ANN001
        n = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if (
                    c.alpha() > 32
                    and abs(c.red() - color.red()) < 24
                    and abs(c.green() - color.green()) < 24
                    and abs(c.blue() - color.blue()) < 24
                ):
                    n += 1
        return n

    lit = paint_carets_at_phase(edit, True)
    dark = paint_carets_at_phase(edit, False)
    assert count(lit, target) > 0, "亮相位应该画出竖线"
    assert count(dark, target) == 0, f"灭相位不该再画竖线: {count(dark, target)}"
    # 选区归 Qt 管：paintEvent 自己不该涂任何选区色
    assert count(lit, hl) == 0, f"paintEvent 不该自己画选区: {count(lit, hl)}"
    assert count(dark, hl) == 0, f"paintEvent 不该自己画选区: {count(dark, hl)}"


@test
def test_selection_highlight_lives_in_extra_selections() -> None:
    """选区高亮必须挂在 Qt 的 ExtraSelection 上（背景在字形之下）。

    取代旧的「paintEvent 里 fillRect 画选区」：那种画法会把文字盖住。
    """
    edit = make_edit("\n".join("abcdefghij" for _ in range(4)))
    edit.select_column(0, 1, 3, 5)
    APP.processEvents()
    assert edit.extra_selections_count() == 3, edit.extra_selections_count()

    hl = edit.palette().color(QPalette.ColorRole.Highlight)
    ours = edit.extraSelections()
    assert len(ours) == 3, len(ours)
    for sel in ours:
        assert sel.format.background().color().getRgb() == hl.getRgb(), (
            sel.format.background().color().getRgb(),
            hl.getRgb(),
        )


@test
def test_column_selection_highlights_when_document_scrolled() -> None:
    """文档滚动后列选仍要每行高亮（日志框永远滚在底部）。

    根因：``cursorRect()`` 返回 **视口坐标**（已减滚动），而
    ``blockBoundingRect()`` 返回 **文档坐标**。旧代码用前者算 x、用后者算 y，
    两套坐标混用：不滚动时差值为0看不出问题，一滚动 y 就变成几千，
    全部画到视口外，效果就是「只有主光标那一行可见」（它是 Qt 自己画的）。
    """
    edit = make_edit("\n".join("abcdefghij" for _ in range(200)))
    bar = edit.verticalScrollBar()
    bar.setValue(bar.maximum())
    APP.processEvents()
    assert bar.value() > 0, "这个测试必须真的滚动起来"

    doc = edit.document()
    last = doc.blockCount() - 4
    edit.select_column(last, 1, last + 3, 5)
    APP.processEvents()
    assert edit.extra_cursor_count() == 3, edit.extra_cursor_count()

    vh = edit.viewport().height()
    for i, cur in enumerate([edit.textCursor(), *edit.extra_cursors]):
        rects = edit.selection_rects(cur)
        assert rects, f"cursor{i} 算不出选区矩形"
        for r in rects:
            assert 0 <= r.top() < vh, (
                f"cursor{i} 的选区 y={r.top()} 超出视口高度 {vh}（坐标系混用）"
            )
            assert r.width() > 0, (i, str(r))

    rows = selection_pixel_rows(render_overlay(edit))
    bands = line_bands(edit)
    covered = [
        any(top <= y < bottom for y in rows) for top, bottom in bands[-4:]
    ]
    assert all(covered), f"滚动后只有 {sum(covered)}/4 行被高亮: {covered}"


@test
def test_column_selection_keeps_text_readable() -> None:
    """列选高亮不能盖住文字——高亮必须是背景，文字必须压在上面。

    根因：早期用 ``QPainter.fillRect`` 直接往视口上涂不透明高亮，画在
    ``super().paintEvent()`` **之后**，于是把刚画好的字形整块覆盖掉，
    用户看到的就是一块实心色块。实测：主光标那行（Qt 原生选区）文字
    可见像素 24 个，副光标行只有 0 个。

    正确做法：选区交给 ``setExtraSelections()``，Qt 会把背景画在字形
    **下面**，文字自然可读（实测 44 个文字像素）。
    """
    edit = make_edit("\n".join("abcdefghij" for _ in range(4)))
    edit.select_column(0, 1, 3, 5)
    APP.processEvents()
    assert edit.extra_cursor_count() == 3, edit.extra_cursor_count()

    edit._caret_timer.stop()
    edit._caret_phase = False  # 灭相位：只剩选区，最容易看出文字是否被盖
    img = render_overlay(edit)

    counts = []
    for cur in [edit.textCursor(), *edit.extra_cursors]:
        rects = edit.selection_rects(cur)
        assert rects, "选区矩形为空，这个测试本身失效了"
        counts.append(sum(text_pixels_inside(img, edit, r) for r in rects))
    assert all(n > 0 for n in counts), (
        f"有行的高亮把文字盖住了（文字像素数={counts}）；"
        "主光标行是 Qt 原生选区，理应最多",
    )
    # 副光标行不能比主光标行差太多（同一量级的可读性）
    assert min(counts) * 2 >= max(counts), f"各行可读性差距过大: {counts}"


@test
def test_extra_cursor_selection_has_no_fillrect_paint() -> None:
    """副光标选区必须走 Qt 的 ExtraSelection，不能再用 fillRect 硬涂。

    只画竖线（2px 宽）是允许的；选区必须由 Qt 排版层绘制。
    """
    edit = make_edit("\n".join("abcdefghij" for _ in range(4)))
    edit.select_column(0, 1, 3, 5)
    APP.processEvents()

    from PySide6.QtGui import QPainter

    img = QImage(edit.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    try:
        edit._paint_all_carets(painter, False)  # 灭相位：只可能画出选区
    finally:
        painter.end()

    hl = edit.palette().color(QPalette.ColorRole.Highlight)
    painted = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 32 and abs(c.red() - hl.red()) < 24:
                painted += 1
    assert painted == 0, (
        f"灭相位下 paintEvent 自己画了 {painted} 个选区像素；"
        "选区应交给 setExtraSelections()，否则会盖住文字",
    )


@test
def test_extra_selections_mirror_extra_cursors() -> None:
    """带选区的副光标各对应一条 ExtraSelection；收敛后必须清空。

    纯光标（无选区）不产生 ExtraSelection——它只需要那根 2px 竖线，
    Qt 的选区高亮对它没有意义。
    """
    edit = make_edit("aaa\nbbb\nccc")
    assert edit.extra_selections_count() == 0

    edit.add_cursor_at(7, 4)  # 带选区
    APP.processEvents()
    assert edit.extra_selections_count() == 1, edit.extra_selections_count()

    edit.add_cursor_at(11)  # 纯光标：只画竖线
    APP.processEvents()
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()
    assert edit.extra_selections_count() == 1, edit.extra_selections_count()

    edit.clear_extra_cursors()
    APP.processEvents()
    assert edit.extra_selections_count() == 0, edit.extra_selections_count()


@test
def test_extra_cursor_selection_highlights_survive_edits() -> None:
    """经过编辑后，ExtraSelection 仍与「带选区的副光标」一一对应。

    这是防「幽灵选区」的回归测试：编辑会让副光标重新定位，如果
    ExtraSelection 不跟着重算，就会残留旧位置的高亮。
    """
    edit = make_edit("aaa\nbbb\nccc")
    edit.add_cursor_at(3, 0)  # 行内选区 aaa -> 全部替换
    edit.add_cursor_at(7, 4)  # 第二行选区 bbb
    APP.processEvents()
    assert edit.extra_selections_count() == 2, edit.extra_selections_count()

    edit.insert_text_at_cursors("XY")
    APP.processEvents()
    sel_cursors = [c for c in edit.extra_cursors if c.hasSelection()]
    assert edit.extra_selections_count() == len(sel_cursors), (
        edit.extra_selections_count(),
        edit.extra_cursor_count(),
    )


@test
def test_host_extra_selections_are_not_dropped() -> None:
    """宿主自己设的额外选区不能被多光标逻辑吞掉。

    主窗口以后若想加「当前搜索结果高亮」这类选区，会调
    ``setExtraSelections``；我们的副光标同步必须与它共存，而不是覆盖。
    """
    from PySide6.QtWidgets import QTextEdit

    edit = make_edit("aaa\nbbb")
    host = QTextEdit.ExtraSelection()
    cur = QTextCursor(edit.document())
    cur.setPosition(0)
    cur.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
    host.cursor = cur
    edit.setExtraSelections([host])
    APP.processEvents()
    assert len(edit.extraSelections()) == 1, len(edit.extraSelections())

    edit.select_column(0, 0, 1, 2)  # 建副光标 -> 触发同步
    APP.processEvents()
    # 1 条宿主 + 1 条副光标（主光标行由 Qt 原生选区负责，不进列表）
    assert len(edit.extraSelections()) == 2, len(edit.extraSelections())

    edit.setExtraSelections([])  # 宿主撤销
    APP.processEvents()
    assert len(edit.extraSelections()) == 1, len(edit.extraSelections())


@test
def test_selection_rects_use_viewport_coordinates() -> None:
    """选区矩形的 y 必须与 ``cursorRect`` 同一坐标系（视口），不是文档坐标。"""
    edit = make_edit("\n".join("abcdefghij" for _ in range(200)))
    bar = edit.verticalScrollBar()
    bar.setValue(bar.maximum())
    APP.processEvents()

    doc = edit.document()
    last = doc.blockCount() - 1
    block = doc.findBlockByNumber(last)
    cur = edit.textCursor()
    cur.setPosition(block.position() + 1)
    cur.setPosition(block.position() + 5, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    APP.processEvents()

    rects = edit.selection_rects(cur)
    assert len(rects) == 1, [str(r) for r in rects]
    probe = QTextCursor(doc)
    probe.setPosition(block.position() + 1)
    expected_top = edit.cursorRect(probe).top()
    assert rects[0].top() == expected_top, (
        f"y={rects[0].top()} 应为视口坐标 {expected_top}",
    )


# --------------------------------------------------------------- Ctrl+/ 接线


@test
def test_ctrl_slash_toggles_comment_through_key_event() -> None:
    """Ctrl+/ 经按键分发给当前行加注释，再按一次取消。"""
    edit = make_edit("alpha")
    caret(edit, 0)
    key(edit, key_code=Qt.Key.Key_Slash, modifiers=CTRL, text="/")
    assert edit.toPlainText() == "#alpha", repr(edit.toPlainText())
    key(edit, key_code=Qt.Key.Key_Slash, modifiers=CTRL, text="/")
    assert edit.toPlainText() == "alpha", repr(edit.toPlainText())


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




# ------------------------------------- 软换行行尾：向右拖不能「越拖越少」
#
# Qt 的 hit-test 在**软换行的视觉行**右边缘会塌陷：x 超过该行正文右边界
# （``documentMargin + naturalTextWidth``）后，``cursorForPosition`` 返回的是
# 该视觉行**最后一个字符的位置**，而不是行末位置。
#
# 后果：向右拖到最右边反而**少选一个字符**——用户看到的就是「选不中这行
# 最后一个字」。非换行的短行没有这个问题（x 超出正文后仍映射到行末）。
#
# 这里断言的是不变量而不是固定像素：**同一视觉行内，x 越大选区终点不得变小**。


def _first_visual_row_end(edit: MultiCursorTextEdit) -> tuple[int, int, int]:
    """返回首个视觉行的 (textStart, textLength, 正文右边界 x)。"""
    block = edit.document().begin()
    layout = block.layout()
    line = layout.lineAt(0)
    margin = edit.document().documentMargin()
    right = int(margin + line.naturalTextWidth())
    return line.textStart(), line.textLength(), right


def _drag_to(edit: MultiCursorTextEdit, x_from: int, y_from: int, x_to: int, y_to: int) -> None:
    """在编辑器上完成一次 press(start) -> move(end) -> release(end) 拖选。"""
    events = (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, x_from, y_from),
        (QEvent.Type.MouseMove, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, x_to, y_to),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, x_to, y_to),
    )
    handlers = {
        QEvent.Type.MouseButtonPress: edit.mousePressEvent,
        QEvent.Type.MouseMove: edit.mouseMoveEvent,
        QEvent.Type.MouseButtonRelease: edit.mouseReleaseEvent,
    }
    for kind, button, buttons, x, y in events:
        ev = QMouseEvent(
            kind,
            QPointF(float(x), float(y)),
            QPointF(float(x), float(y)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        handlers[kind](ev)


@test
def test_dragging_right_never_selects_less_within_a_wrapped_row() -> None:
    """同一软换行视觉行内，向右拖的选区终点必须单调不减。

    x 越过正文右边界后终点反而回退，正是「选不中最后一个字」的根因。
    """
    text = "".join(chr(ord("a") + i % 26) for i in range(300))
    edit = make_edit(text)
    _, length, right = _first_visual_row_end(edit)
    assert length > 10, f"首行应有足够字符，实际 {length}"

    row_y = int(edit.document().documentMargin() + 5)
    ends = []
    for x in range(right - 20, right + 8, 2):
        cur = QTextCursor(edit.document())
        cur.setPosition(0)
        edit.setTextCursor(cur)
        _drag_to(edit, 2, row_y, x, row_y)
        ends.append((x, edit.textCursor().selectionEnd()))

    drops = [
        (ends[k - 1], ends[k])
        for k in range(1, len(ends))
        if ends[k][1] < ends[k - 1][1]
    ]
    assert not drops, (
        f"向右拖时选区终点回退（正文右边界 x={right}）：{drops}"
    )


@test
def test_drag_to_far_right_edge_selects_whole_first_visual_row() -> None:
    """拖到编辑器最右边，必须选满整个首个视觉行。"""
    text = "".join(chr(ord("a") + i % 26) for i in range(300))
    edit = make_edit(text)
    start, length, _ = _first_visual_row_end(edit)
    row_y = int(edit.document().documentMargin() + 5)
    far_right = edit.viewport().width() - 2
    _drag_to(edit, 2, row_y, far_right, row_y)
    sel = edit.textCursor()
    assert sel.selectionEnd() == start + length, (
        f"应选到行末 {start + length}，实际 {sel.selectionEnd()}"
    )
    assert len(sel.selectedText()) == length, (
        f"应选 {length} 字符，实际 {len(sel.selectedText())}"
    )


@test
def test_wrapped_row_right_edge_maps_identically_from_either_direction() -> None:
    """同一右边缘点，从左边拖来与从下面拖回，必须映射到同一文本位置。

    这是方向无关性：若正向拖得到行末、反向拖得到「最后一个字符」，
    同一个像素点就会对应两个位置，拖动方向一变选区宽度就跳变。
    """
    text = "".join(chr(ord("a") + i % 26) for i in range(300))
    edit = make_edit(text)
    start, length, _ = _first_visual_row_end(edit)
    margin = edit.document().documentMargin()
    row1_y = int(margin + 5)
    far_right = edit.viewport().width() - 2

    # 正向：从行首拖到右边缘
    anchor = QTextCursor(edit.document())
    anchor.setPosition(start)
    edit.setTextCursor(anchor)
    _drag_to(edit, 2, row1_y, far_right, row1_y)
    forward_end = edit.textCursor().selectionEnd()

    # 反向：从第二行拖回同一右边缘点
    below = QTextCursor(edit.document())
    below.setPosition(start + length + 6)
    edit.setTextCursor(below)
    _drag_to(edit, 2, int(margin + 20), far_right, row1_y)
    backward_start = edit.textCursor().selectionStart()

    assert forward_end == backward_start, (
        f"同一右边缘点映射不一致：正向 {forward_end} vs 反向 {backward_start}"
    )
    assert forward_end == start + length, (
        f"右边缘应映射到行末 {start + length}，实际 {forward_end}"
    )


@test
def test_drag_to_right_edge_of_unwrapped_line_selects_whole_line() -> None:
    """非换行的短行不受影响：拖到最右仍选中整行。"""
    edit = make_edit("abcdef")
    row_y = int(edit.document().documentMargin() + 5)
    _drag_to(edit, 2, row_y, edit.viewport().width() - 2, row_y)
    assert edit.textCursor().selectedText() == "abcdef", (
        edit.textCursor().selectedText()
    )


@test
def test_drag_right_edge_of_last_visual_row_selects_block_end() -> None:
    """块内最后一个视觉行：拖到右边缘选到块末，不越界到下一段。"""
    text = "".join(chr(ord("a") + i % 26) for i in range(300)) + "\nsecond"
    edit = make_edit(text)
    block = edit.document().begin()
    layout = block.layout()
    last = layout.lineAt(layout.lineCount() - 1)
    expect_end = last.textStart() + last.textLength()
    margin = edit.document().documentMargin()
    y = int(margin + last.rect().y() + 5)
    cur = QTextCursor(edit.document())
    cur.setPosition(last.textStart())
    edit.setTextCursor(cur)
    _drag_to(edit, 2, y, edit.viewport().width() - 2, y)
    assert edit.textCursor().selectionEnd() == expect_end, (
        f"应选到 {expect_end}，实际 {edit.textCursor().selectionEnd()}"
    )


# --------------------------------------- 矩形列选（Alt+拖拽）：像素语义


def _char_x(edit: MultiCursorTextEdit, block_number: int, char_index: int) -> float:
    """某块里第 ``char_index`` 个字符边界的视口 x 坐标。

    用 ``cursorRect`` 反查：它走的是控件自己的排版结果，不依赖
    ``QTextLayout`` 尚未建立时的空指针，比直接拿 ``block.layout()`` 安全。
    """
    block = edit.document().findBlockByNumber(block_number)
    cur = QTextCursor(block)
    cur.setPosition(block.position() + char_index)
    return float(edit.cursorRect(cur).left())


def _row_h(edit: MultiCursorTextEdit) -> int:
    """一个视觉行的高度（像素）。"""
    cur = QTextCursor(edit.document().begin())
    return int(edit.cursorRect(cur).height())


def _alt_drag(edit: MultiCursorTextEdit, x1: int, y1: int, x2: int, y2: int) -> None:
    mouse(edit, QEvent.Type.MouseButtonPress, x1, y1, Qt.KeyboardModifier.AltModifier)
    mouse(edit, QEvent.Type.MouseMove, x2, y2, Qt.KeyboardModifier.AltModifier)
    mouse(edit, QEvent.Type.MouseButtonRelease, x2, y2, Qt.KeyboardModifier.AltModifier)


def _drag_rect(edit: MultiCursorTextEdit, x1: int, x2: int, rows: int = 3) -> None:
    """在 ``rows`` 行上拖出 [x1, x2] 的矩形列选。"""
    margin = edit.document().documentMargin()
    row_h = _row_h(edit)
    _alt_drag(
        edit,
        x1,
        int(margin + 2),
        x2,
        int(margin + 2 + (rows - 1) * row_h + 4),
    )


@test
def test_alt_drag_selects_to_each_line_end_not_common_column() -> None:
    """矩形越过短行行尾时，短行选到自己的行尾，而不是被裁成统一列宽。

    旧实现把「列号」当块内字符偏移，短行会被裁到行尾、长行却只选到同一个
    偏移量，行尾内容选不中。改成像素模型后，每行按自己的度量命中。
    """
    edit = make_edit("A" * 20 + "\n" + "B" * 10 + "\n" + "C" * 20)
    _drag_rect(edit, int(_char_x(edit, 0, 0)), int(_char_x(edit, 0, 15)))
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()
    texts = [edit.textCursor().selectedText()]
    texts += [c.selectedText() for c in edit.extra_cursors]
    assert texts[0] == "A" * 15, len(texts[0])
    assert texts[1] == "B" * 10, len(texts[1])
    assert texts[2] == "C" * 15, len(texts[2])


@test
def test_alt_drag_right_edge_includes_whole_last_character() -> None:
    """矩形右边界落在字符内部时，那个字符要整个选中。"""
    edit = make_edit("abcdef\nabcdef")
    margin = edit.document().documentMargin()
    row_h = _row_h(edit)
    x1 = int(_char_x(edit, 0, 0) + 1)
    # 落在第 3 个字符中间：应选到 'abc'
    x2 = int(_char_x(edit, 0, 3) - 1)
    _alt_drag(edit, x1, int(margin + 2), x2, int(margin + 2 + row_h))
    assert edit.textCursor().selectedText() == "abc", edit.textCursor().selectedText()


@test
def test_right_click_inside_rect_selection_keeps_it() -> None:
    """矩形列选后，在选区内右击不应把选区清掉。

    用户此时的意图是「对这个矩形操作」（复制、查找…），清掉选区会让
    菜单里的复制只拿到第一行。
    """
    edit = make_edit("abcdef\nabcdef\nabcdef")
    margin = edit.document().documentMargin()
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()
    right_click(edit, x1 + 1, int(margin + 4))
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()
    assert edit.textCursor().selectedText() == "bc", edit.textCursor().selectedText()


@test
def test_right_click_outside_rect_selection_clears_it() -> None:
    """在矩形选区**外**右击仍按老规矩收敛回单光标。"""
    edit = make_edit("abcdef\nabcdef\nabcdef")
    margin = edit.document().documentMargin()
    row_h = _row_h(edit)
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    assert edit.extra_cursor_count() == 2, edit.extra_cursor_count()
    right_click(edit, 2, int(margin + 4 * row_h))
    assert edit.extra_cursor_count() == 0, edit.extra_cursor_count()


@test
def test_ctrl_c_copies_whole_rect_selection() -> None:
    """矩形列选下 Ctrl+C 要复制整块，而不是只有主光标那一行。"""
    edit = make_edit("abcdef\nabcdef\nabcdef")
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    ev = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier,
        "\x03",
    )
    edit.keyPressEvent(ev)
    assert QApplication.clipboard().text() == "bc\nbc\nbc", (
        QApplication.clipboard().text()
    )


@test
def test_ctrl_x_cuts_whole_rect_selection() -> None:
    """矩形列选下 Ctrl+X 要剪切整块，而不是只有主光标那一行。"""
    edit = make_edit("abcdef\nabcdef\nabcdef")
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    ev = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_X,
        Qt.KeyboardModifier.ControlModifier,
        "\x18",
    )
    edit.keyPressEvent(ev)
    assert QApplication.clipboard().text() == "bc\nbc\nbc", (
        QApplication.clipboard().text()
    )
    assert edit.toPlainText() == "adef\nadef\nadef", repr(edit.toPlainText())


@test
def test_delete_key_removes_whole_rect_selection() -> None:
    """矩形列选下 Delete 要删掉矩形的每一行。"""
    edit = make_edit("abcdef\nabcdef\nabcdef")
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier, "")
    edit.keyPressEvent(ev)
    assert edit.toPlainText() == "adef\nadef\nadef", repr(edit.toPlainText())


@test
def test_context_menu_cut_and_delete_act_on_whole_rect() -> None:
    """右键菜单里的剪切/删除也要作用到矩形的每一行。

    走真实的 ``contextMenuEvent`` 路径：``QTextEdit`` 内部的右键菜单不会
    调 ``createStandardContextMenu()``，只改后者是无效的。
    """
    edit = make_edit("abcdef\nabcdef\nabcdef")
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    menus = []
    edit._exec_context_menu = lambda menu, event: menus.append(menu)
    ev = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        QPoint(int(x1), 4),
        QPoint(int(x1), 4),
    )
    edit.contextMenuEvent(ev)
    assert menus, "右键菜单没有被构造"
    labels = [a.text().replace("&", "").split("\t")[0] for a in menus[0].actions()]
    assert "Cut" in labels, labels
    assert "Delete" in labels, labels
    for action in menus[0].actions():
        label = action.text().replace("&", "").split("\t")[0]
        if label == "Cut":
            action.trigger()
    assert QApplication.clipboard().text() == "bc\nbc\nbc", (
        QApplication.clipboard().text()
    )
    assert edit.toPlainText() == "adef\nadef\nadef", repr(edit.toPlainText())


@test
def test_context_menu_delete_removes_whole_rect() -> None:
    """右键菜单里的「删除」要删掉矩形的每一行。"""
    edit = make_edit("abcdef\nabcdef\nabcdef")
    x1 = int(_char_x(edit, 0, 1))
    x2 = int(_char_x(edit, 0, 3))
    _drag_rect(edit, x1, x2)
    menus = []
    edit._exec_context_menu = lambda menu, event: menus.append(menu)
    ev = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        QPoint(int(x1), 4),
        QPoint(int(x1), 4),
    )
    edit.contextMenuEvent(ev)
    for action in menus[0].actions():
        label = action.text().replace("&", "").split("\t")[0]
        if label == "Delete":
            action.trigger()
    assert edit.toPlainText() == "adef\nadef\nadef", repr(edit.toPlainText())


# --------------------------------------------------- 撤销：光标集合要一起还原
#
# Qt 的撤销栈只还原**文本**，不认识本控件的副光标。多光标删除后按 Ctrl+Z，
# 文本回来了，但副光标仍停在编辑后的位置——用户报障的「多光标删除文字再
# ctrl+z 撤销删除，光标位置错乱」正是这个。
#
# 副光标之所以会错位，是因为它本身也是 ``QTextCursor``：文档被撤销时
# Qt 会**自动**把这些光标平移到「看起来合理、其实不对」的偏移上。


def _cursor_positions(edit: MultiCursorTextEdit) -> list[tuple[int, int]]:
    """全部光标（主 + 副）的 (position, anchor)，按主光标在前。"""
    primary = edit.textCursor()
    out = [(primary.position(), primary.anchor())]
    for cur in edit.extra_cursors:
        out.append((cur.position(), cur.anchor()))
    return out


def _multicursor_setup(edit: MultiCursorTextEdit) -> None:
    """造三个互不相同的光标：主光标 6，副光标 11、17。"""
    edit.add_cursor_at(11)
    edit.add_cursor_at(17)
    caret(edit, 6)


@test
def test_undo_restores_cursor_positions_after_multicursor_delete() -> None:
    """多光标删除后 Ctrl+Z，文本与**全部光标位置**都要回到删除前。"""
    edit = make_edit("alpha beta gamma delta")
    _multicursor_setup(edit)
    before = _cursor_positions(edit)

    edit.delete_at_cursors(backward=True)
    assert edit.toPlainText() == "alphabetagammadelta", repr(edit.toPlainText())
    assert _cursor_positions(edit) != before

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "alpha beta gamma delta", repr(edit.toPlainText())
    assert _cursor_positions(edit) == before, (
        _cursor_positions(edit),
        before,
    )


@test
def test_undo_restores_cursor_positions_after_multicursor_insert() -> None:
    """多光标输入后 Ctrl+Z，光标集合同样要还原。"""
    edit = make_edit("alpha beta gamma delta")
    _multicursor_setup(edit)
    before = _cursor_positions(edit)

    edit.insert_text_at_cursors("X")
    assert edit.toPlainText() != "alpha beta gamma delta"

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "alpha beta gamma delta", repr(edit.toPlainText())
    assert _cursor_positions(edit) == before, (
        _cursor_positions(edit),
        before,
    )


@test
def test_redo_restores_cursor_positions_after_undo() -> None:
    """Ctrl+Shift+Z 重做后，光标要回到「编辑后」的位置。"""
    edit = make_edit("alpha beta gamma delta")
    _multicursor_setup(edit)
    edit.delete_at_cursors(backward=True)
    after = _cursor_positions(edit)

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    key(
        edit,
        key_code=Qt.Key.Key_Z,
        modifiers=Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier,
    )
    assert edit.toPlainText() == "alphabetagammadelta", repr(edit.toPlainText())
    assert _cursor_positions(edit) == after, (
        _cursor_positions(edit),
        after,
    )


@test
def test_undo_key_is_consumed_by_editor() -> None:
    """Ctrl+Z 必须被本控件吃掉，不能再冒泡给 Qt 默认处理。"""
    edit = make_edit("alpha beta gamma delta")
    _multicursor_setup(edit)
    edit.delete_at_cursors(backward=True)
    event = key(
        edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier
    )
    assert event.isAccepted(), "Ctrl+Z 未被消费"


@test
def test_undo_without_multicursor_still_works() -> None:
    """单光标时 Ctrl+Z 依然要能撤销普通输入。"""
    edit = make_edit("alpha")
    caret(edit, 5)
    edit.insertPlainText("beta")
    assert edit.toPlainText() == "alphabeta", repr(edit.toPlainText())
    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "alpha", repr(edit.toPlainText())


@test
def test_undo_after_interleaved_log_append_restores_cursors() -> None:
    """多光标编辑之后又追加了日志，撤销追加再撤销编辑，光标仍要还原。"""
    edit = make_edit("alpha beta gamma delta")
    _multicursor_setup(edit)
    before = _cursor_positions(edit)

    edit.delete_at_cursors(backward=True)
    edit.append_line("a new log line")

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert "a new log line" not in edit.toPlainText(), repr(edit.toPlainText())

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "alpha beta gamma delta", repr(edit.toPlainText())
    assert _cursor_positions(edit) == before, (
        _cursor_positions(edit),
        before,
    )


@test
def test_undo_restores_cursor_selection_state() -> None:
    """选区也要还原：撤销后光标仍带原来的选区。"""
    edit = make_edit("alpha beta gamma delta")
    cur = edit.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, cur.MoveMode.KeepAnchor)
    edit.setTextCursor(cur)
    edit.add_cursor_at(11)

    edit.delete_at_cursors(backward=True)
    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "alpha beta gamma delta", repr(edit.toPlainText())
    assert edit.textCursor().hasSelection(), "选区没有随撤销还原"
    assert edit.textCursor().selectedText() == "alpha", (
        edit.textCursor().selectedText()
    )


@test
def test_undo_restores_cursor_positions_after_delete_line() -> None:
    """多光标删整行后 Ctrl+Z，光标要回到删行前。"""
    edit = make_edit("one\ntwo\nthree\nfour")
    caret(edit, 1)
    edit.add_cursor_at(9)
    before = _cursor_positions(edit)

    edit.delete_line()
    assert edit.toPlainText() != "one\ntwo\nthree\nfour", repr(edit.toPlainText())

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "one\ntwo\nthree\nfour", repr(edit.toPlainText())
    assert _cursor_positions(edit) == before, (
        _cursor_positions(edit),
        before,
    )


@test
def test_undo_restores_cursor_positions_after_duplicate_line() -> None:
    """多光标复制行后 Ctrl+Z，光标要回到复制前。"""
    edit = make_edit("one\ntwo\nthree")
    caret(edit, 1)
    edit.add_cursor_at(6)
    before = _cursor_positions(edit)

    edit.duplicate_line(1)
    assert edit.toPlainText() != "one\ntwo\nthree", repr(edit.toPlainText())

    key(edit, key_code=Qt.Key.Key_Z, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert edit.toPlainText() == "one\ntwo\nthree", repr(edit.toPlainText())
    assert _cursor_positions(edit) == before, (
        _cursor_positions(edit),
        before,
    )


if __name__ == "__main__":
    sys.exit(main())


