"""等宽字体网格对齐（util/client/multi_cursor_font.py）行为测试。

不依赖 pytest：直接 `python tests/mono_font_grid_test.py` 运行，离屏执行。

背景 —— 为什么需要「吸附到网格」：

字体文件 ``MapleMono-NF-CN-Regular.ttf`` 的**设计** advance 是严格 2:1：

    unitsPerEm = 1000
    Latin (A / i / space) = 600/1000 em
    CJK   (中 / 。/ ，)   = 1200/1000 em

但 Qt 把 advance 量化到**整数像素**，比例于是被破坏。以 12pt 为例：
Latin 落到 10px、CJK 落到 **19px**（本该是 20px）——每个汉字少 1px，
误差沿线累积。后果就是用户看到的「长行自动换行后 mono 字体对不齐」：

    max |x - (margin + cellIndex * L)| = 15px      （理想值 0）

而且光标上下移动会跟着漂移（Qt 的 Up/Down 保持 goal-x）：

    光标在汉字上 -> 向下 -> x 偏了 1/2/3 px（每个汉字累积 1px）

所以修复方式是：**把字号吸附到最近的「CJK advance 恰为 Latin advance 两倍」的点**。
吸附之后网格不变量严格成立，上面那个 15px 变成 0px。
"""

import os
import sys
import traceback
import unicodedata
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import PySide6  # noqa: E402

from PySide6.QtGui import QFont, QFontMetrics, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit  # noqa: E402

APP = QApplication.instance() or QApplication([])

from util.client.multi_cursor_font import (  # noqa: E402
    MONO_FONT_FAMILY,
    ensure_mono_font_loaded,
    grid_error,
    is_grid_exact,
    snap_point_size,
)

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def cells(ch: str) -> int:
    """一个字符占几个等宽格：全角 2 格，半角 1 格。"""
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def make_edit(text: str = ""):
    """造一个已显示的编辑器（离屏）。"""
    from util.client.multicursor_edit import MultiCursorTextEdit

    edit = MultiCursorTextEdit()
    edit.resize(320, 320)
    edit.show()
    edit.raise_()
    edit.activateWindow()
    APP.processEvents()
    edit.setPlainText(text)
    APP.processEvents()
    return edit


# ------------------------------------------------------------ 网格判据本身


@test
def test_grid_error_is_zero_for_exact_grid_size() -> None:
    """网格正确的字号：Latin 与 CJK advance 恰好 2:1，误差为 0。"""
    assert ensure_mono_font_loaded() is True, "字体加载失败"
    size = snap_point_size(12.0)
    assert grid_error(size) == 0, (size, grid_error(size))


@test
def test_plain_12pt_is_not_on_the_grid() -> None:
    """12pt **不在**网格上——这正是要修的 bug 的根因。

    若哪天这条断言失败，说明 Qt 的取整行为变了，本模块的吸附就失去意义，
    需要重新评估（而不是继续保留一份无效的吸附逻辑）。
    """
    assert ensure_mono_font_loaded() is True, "字体加载失败"
    assert is_grid_exact(12.0) is False, (
        "12pt 意外地满足了 2:1；请复核吸附逻辑是否还有必要"
    )
    assert grid_error(12.0) > 0, grid_error(12.0)


# -------------------------------------------------------------- 吸附的行为


@test
def test_snap_returns_a_size_on_the_grid() -> None:
    """吸附后的字号一定满足 2:1。"""
    for target in range(5, 46):
        snapped = snap_point_size(float(target))
        assert is_grid_exact(snapped) is True, (target, snapped)


@test
def test_snap_stays_close_to_the_requested_size() -> None:
    """吸附不能把字号改得面目全非（否则用户会觉得字号乱跳）。"""
    for target in range(5, 46):
        snapped = snap_point_size(float(target))
        assert abs(snapped - target) <= 1.0, (target, snapped)


@test
def test_snap_keeps_latin_width_unchanged() -> None:
    """吸附优先找**Latin 宽度不变**的解。

    Latin 宽度变了意味着整篇文本的视觉宽度变了——用户只是调了字号，
    看到的行宽却跟着变，很突兀。CJK 宽度允许变（必须变才能凑成 2:1）。
    """
    for target in range(5, 46):
        before = QFontMetrics(
            _font_at(float(target))
        ).horizontalAdvance("A")
        after = QFontMetrics(_font_at(snap_point_size(float(target)))).horizontalAdvance(
            "A"
        )
        assert before == after, (target, before, after)


@test
def test_snap_is_idempotent() -> None:
    """对已吸附的字号再吸附，结果不变（避免反复调用时数值漂移）。"""
    for target in range(5, 46):
        once = snap_point_size(float(target))
        twice = snap_point_size(once)
        assert once == twice, (target, once, twice)


@test
def test_consecutive_zoom_levels_stay_distinct() -> None:
    """相邻字号吸附后不能塌成同一个值（否则 Ctrl+滚轮会「卡住」）。

    7pt 与 8pt 是最容易撞车的一对：7->7.13、8->7.87，若吸附成同一个值，
    用户连按两次滚轮却看到字号没变。
    """
    snapped = [snap_point_size(float(pt)) for pt in range(5, 46)]
    for i in range(1, len(snapped)):
        assert snapped[i] != snapped[i - 1], (i, snapped[i - 1], snapped[i])


@test
def test_stylesheet_path_also_snaps_to_the_grid() -> None:
    """**生产路径**必须走吸附：``mono_font_stylesheet`` 是 GUI 真正用的那个。

    直接测 ``snap_point_size`` 是不够的——若只有 stylesheet 这条路忘了
    吸附，网格照样是坏的（GUI 走的正是这条路）。
    """
    from util.client.multi_cursor_font import mono_font_stylesheet

    for size in range(5, 46):
        sheet = mono_font_stylesheet(size)
        assert f"font-size: {snap_point_size(float(size))}pt" in sheet, (size, sheet)


@test
def test_applied_font_is_grid_exact_for_every_zoom_level() -> None:
    """``apply_mono_font`` 应用后，字体必须落在网格上。

    这是 GUI 初始化走的路径（``CustomTextEdit.__init__``）。
    """
    from util.client.multi_cursor_font import apply_mono_font

    for size in range(5, 46):
        widget = QTextEdit()
        apply_mono_font(widget, size)
        APP.processEvents()
        metrics = widget.fontMetrics()
        latin = metrics.horizontalAdvance("A")
        cjk = metrics.horizontalAdvance("\u4e2d")
        assert cjk == 2 * latin, (size, latin, cjk)


@test
def test_snap_works_on_a_fresh_process_without_prior_font_load() -> None:
    """**全新进程**里第一次调用吸附就必须给出正确结果。

    字体没注册进 Qt 时，``QFontMetrics`` 量到的全是退化值（16/16），
    网格搜索会找不到解并把**错误的结果缓存下来**，此后永远错。

    这个场景必须用子进程验证：当前测试进程里字体多半已经加载过了，
    在进程内模拟不出来。

    子进程的输出重定向到**文件**而不是管道——受限环境下建管道会被拒
    （``PermissionError: [WinError 5]``）。
    """
    import subprocess
    import tempfile

    script = (
        "import os, sys\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from util.client.multi_cursor_font import snap_point_size, is_grid_exact, grid_error\n"
        "size = snap_point_size(12.0)\n"
        "print('RESULT', size, is_grid_exact(size), grid_error(size))\n"
    )
    handle, path = tempfile.mkstemp(suffix=".txt")
    os.close(handle)
    try:
        with open(path, "w", encoding="utf-8") as sink:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                stdout=sink,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
        assert completed.returncode == 0, completed.returncode
        output = Path(path).read_text(encoding="utf-8")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    line = [ln for ln in output.splitlines() if ln.startswith("RESULT")]
    assert line, output
    _label, size, exact, error = line[0].split()
    assert exact == "True", f"全新进程里吸附结果 {size} 不在网格上（误差 {error}px）"


# ------------------------------------------------- 渲染后的网格不变量


@test
def test_wrapped_text_lands_on_a_perfect_grid() -> None:
    """软换行后，每个字符的 x 必须落在理想网格线上。

    这是用户可见症状的**直接**断言：不变量成立 => 「mono 对不齐」消失。
    """
    edit = make_edit()
    try:
        edit.setStyleSheet(
            f"font-family: '{MONO_FONT_FAMILY}';"
            f" font-size: {snap_point_size(12.0)}pt;"
        )
        APP.processEvents()
        text = "中文测试" * 12 + "ASCII" * 8
        edit.setPlainText(text)
        APP.processEvents()

        doc = edit.document()
        layout = doc.findBlockByNumber(0).layout()
        margin = edit.cursorRect(QTextCursor(doc)).left()
        cell_width = edit.fontMetrics().horizontalAdvance("A")

        worst = 0
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            cell = 0
            for offset in range(line.textLength()):
                position = line.textStart() + offset
                cursor = QTextCursor(doc)
                cursor.setPosition(position)
                x = edit.cursorRect(cursor).left()
                worst = max(worst, abs(x - (margin + cell * cell_width)))
                cell += cells(text[position])
        assert worst == 0, f"网格偏差 {worst}px（理想 0）"
    finally:
        edit.close()


@test
def test_same_cell_column_shares_x_across_wrapped_rows() -> None:
    """同一个格号在不同换行行之间必须是同一个 x。

    这是「上下对齐」的直观含义：用户在第一行看到的第 N 格，
    在下一行也得是第 N 格。
    """
    edit = make_edit()
    try:
        edit.setStyleSheet(
            f"font-family: '{MONO_FONT_FAMILY}';"
            f" font-size: {snap_point_size(12.0)}pt;"
        )
        APP.processEvents()
        text = "中文测试" * 12 + "ASCII" * 8
        edit.setPlainText(text)
        APP.processEvents()

        doc = edit.document()
        layout = doc.findBlockByNumber(0).layout()
        x_by_cell: dict[int, set[int]] = {}
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            cell = 0
            for offset in range(line.textLength()):
                position = line.textStart() + offset
                cursor = QTextCursor(doc)
                cursor.setPosition(position)
                x_by_cell.setdefault(cell, set()).add(edit.cursorRect(cursor).left())
                cell += cells(text[position])

        mismatched = {c: xs for c, xs in x_by_cell.items() if len(xs) > 1}
        assert not mismatched, f"这些格号在不同行之间 x 不一致: {mismatched}"
    finally:
        edit.close()


@test
def test_cursor_vertical_movement_keeps_its_column() -> None:
    """上下移动光标不能横向漂移。

    Qt 的 Up/Down 会记住「目标 x」，但如果字体网格本身是坏的，
    目标 x 会落在字符中间，往下一行就对不齐——这就是用户说的
    「光标上下移动位置错乱」。
    """
    from PySide6.QtGui import QTextCursor

    edit = make_edit()
    try:
        edit.setStyleSheet(
            f"font-family: '{MONO_FONT_FAMILY}';"
            f" font-size: {snap_point_size(12.0)}pt;"
        )
        APP.processEvents()
        text = "中文测试" * 12
        edit.setPlainText(text)
        APP.processEvents()
        doc = edit.document()

        def x_at(position: int) -> int:
            cursor = QTextCursor(doc)
            cursor.setPosition(position)
            return edit.cursorRect(cursor).left()

        for start in (0, 1, 2, 3, 5):
            cursor = edit.textCursor()
            cursor.setPosition(start)
            edit.setTextCursor(cursor)
            before = x_at(start)
            edit.move_all_cursors(QTextCursor.MoveOperation.Down)
            APP.processEvents()
            after = x_at(edit.textCursor().position())
            assert after == before, (start, before, after)
    finally:
        edit.close()


def _font_at(point_size: float) -> QFont:
    """造一个指定字号的等宽字体。"""
    font = QFont(MONO_FONT_FAMILY)
    font.setPointSizeF(point_size)
    return font


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
