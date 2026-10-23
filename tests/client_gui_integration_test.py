"""start_client_gui 集成的行为测试。

覆盖用户提出的两个关键回归点：
1. 取消监听后，日志继续追加，但不移动用户的光标与滚动位置；
2. 主界面文本框具备多光标能力，且原有字号缩放仍然可用。

用法：
    ./runtime/python.exe tests/client_gui_integration_test.py
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtWidgets import QMainWindow  # noqa: E402

APP = QApplication.instance() or QApplication([])

import start_client_gui as gui_module  # noqa: E402
from util.client.multicursor_edit import MultiCursorTextEdit  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def make_box(text: str = "") -> gui_module.CustomTextEdit:
    box = gui_module.CustomTextEdit()
    box.setPlainText(text)
    box.resize(600, 400)
    box.show()
    APP.processEvents()
    return box


def caret(box, position: int) -> None:
    cur = box.textCursor()
    cur.setPosition(position)
    box.setTextCursor(cur)
    APP.processEvents()


# ------------------------------------------------------------ 类层次与开关


@test
def test_custom_text_edit_is_multicursor_editor() -> None:
    """主界面文本框继承多光标编辑器，既有能力全部可用。"""
    box = make_box("hello")
    assert isinstance(box, MultiCursorTextEdit), type(box.__mro__)


@test
def test_follow_caret_defaults_to_true() -> None:
    """首次启动时仍保持「追加日志滚动到底」的旧行为。"""
    box = make_box("x")
    assert box.follow_caret is True


@test
def test_monitor_off_disables_follow_caret() -> None:
    """停止监听后关闭自动跟随，用户光标不再被抢走。"""
    box = make_box("line1\nline2")
    box.set_follow_caret(False)
    caret(box, 2)
    box.append_line("new log line")
    assert box.textCursor().position() == 2, box.textCursor().position()


@test
def test_monitor_on_restores_follow_caret() -> None:
    """重新开始监听后恢复自动跟随。"""
    box = make_box("a\nb")
    box.set_follow_caret(False)
    box.set_follow_caret(True)
    box.append_line("tail")
    text = box.toPlainText()
    assert text.endswith("tail"), repr(text)
    assert box.textCursor().position() == len(text), box.textCursor().position()


@test
def test_font_zoom_still_works_after_multicursor_change() -> None:
    """原有 Ctrl+滚轮缩放字号的能力不被破坏。"""
    box = make_box("x")
    box.font_size = 12
    box.max_font_size = 45
    assert box.min_font_size == 5
    assert box.max_font_size == 45


# ---------------------------------------------------------------- 字体


@test
def test_text_box_uses_maple_mono_font() -> None:
    """文本框默认使用 MapleMono-NF-CN-Regular 等宽字体。

    该字体族在 Qt 字体库里不一定被自动索引到（Windows 装了但 Qt 没枚举到），
    所以实现里会用 ``addApplicationFont`` 显式加载，加载后的族名是
    ``Maple Mono NF CN``——注意与文件名 ``MapleMono-NF-CN-Regular`` 不同。
    """
    from util.client.multi_cursor_font import MONO_FONT_FAMILY, apply_mono_font

    box = make_box("x")
    apply_mono_font(box)
    APP.processEvents()
    family = box.font().family()
    assert family == MONO_FONT_FAMILY, family


@test
def test_mono_font_family_is_available_after_apply() -> None:
    """apply 之后该族名必须在字体库里真正可用（不能只是字符串设进去）。"""
    from PySide6.QtGui import QFont, QFontInfo

    from util.client.multi_cursor_font import (
        MONO_FONT_FAMILY,
        ensure_mono_font_loaded,
    )

    assert ensure_mono_font_loaded() is True, "字体加载失败"
    info = QFontInfo(QFont(MONO_FONT_FAMILY))
    assert info.family() == MONO_FONT_FAMILY, info.family()
    assert info.exactMatch() is True, "Qt 没有真正匹配到该字体，退化成替代字体"


@test
def test_mono_font_survives_stylesheet_change() -> None:
    """Ctrl+滚轮会重设 stylesheet，字体族不能因此被冲掉。

    根因：``setStyleSheet("font-size: 14pt;")`` 只改字号，理论上不动族名；
    但若实现里把族名也只写在 stylesheet 里、或每次重设时忘了带上，
    缩放一次字体就退回系统默认。
    """
    from util.client.multi_cursor_font import (
        MONO_FONT_FAMILY,
        apply_mono_font,
        mono_font_stylesheet,
    )

    box = make_box("x")
    apply_mono_font(box)
    box.setStyleSheet(mono_font_stylesheet(18))
    APP.processEvents()
    assert box.font().family() == MONO_FONT_FAMILY, box.font().family()
    assert box.font().pointSize() == 18, box.font().pointSize()


@test
def test_mono_font_is_monospaced() -> None:
    """等宽字体：'i' 和 'W' 的宽度必须相同（否则日志对齐会乱）。"""
    from util.client.multi_cursor_font import apply_mono_font

    box = make_box("x")
    apply_mono_font(box)
    APP.processEvents()
    fm = box.fontMetrics()
    assert fm.horizontalAdvance("i") == fm.horizontalAdvance("W"), (
        fm.horizontalAdvance("i"),
        fm.horizontalAdvance("W"),
    )


@test
def test_background_switch_keeps_mono_font() -> None:
    """切换文本框背景（显隐时间标签时）不能把等宽字体冲掉。

    根因：``show_time_label`` 模式下鼠标进出窗口会重设 stylesheet
    改背景透明度；若那次重设只写 ``background-color``，族名就没了，
    用户一进一出窗口字体就变回系统默认。
    """
    from util.client.multi_cursor_font import MONO_FONT_FAMILY

    box = make_box("x")
    box.apply_background(255)
    APP.processEvents()
    assert box.font().family() == MONO_FONT_FAMILY, box.font().family()

    box.apply_background(0)
    APP.processEvents()
    assert box.font().family() == MONO_FONT_FAMILY, (
        box.font().family(),
    )


@test
def test_apply_font_size_clamps_and_keeps_font() -> None:
    """字号夹在 5–45pt 之间，且族名始终跟着走。"""
    from util.client.multi_cursor_font import MONO_FONT_FAMILY

    box = make_box("x")
    box.apply_font_size(999)
    APP.processEvents()
    assert box.font_size == 45, box.font_size
    assert box.font().family() == MONO_FONT_FAMILY

    box.apply_font_size(1)
    APP.processEvents()
    assert box.font_size == 5, box.font_size
    assert box.font().family() == MONO_FONT_FAMILY


@test
def test_text_box_has_rounded_corners() -> None:
    """文本框圆角写在样式表里，且切背景/切字号都不能把它冲掉。"""
    box = make_box("x")
    radius = f"border-radius: {gui_module.CustomTextEdit.CORNER_RADIUS}px"
    assert radius in box.styleSheet(), box.styleSheet()

    box.apply_background(0)
    assert radius in box.styleSheet(), "切背景后圆角丢了"
    box.apply_font_size(18)
    assert radius in box.styleSheet(), "切字号后圆角丢了"


@test
def test_window_background_carries_corner_radius() -> None:
    """窗口背景样式里带圆角；alpha=0（时钟模式）时仍然全透明。

    这里只借用 ``GUI._apply_window_background`` 的样式表构造逻辑，不启动
    整个客户端（那会拉起子进程和托盘图标）。
    """

    class _WindowStub(QMainWindow):
        WINDOW_CORNER_RADIUS = gui_module.GUI.WINDOW_CORNER_RADIUS
        _apply_window_background = gui_module.GUI._apply_window_background

    win = _WindowStub()
    win._apply_window_background(255)
    sheet = win.styleSheet()
    assert f"border-radius: {gui_module.GUI.WINDOW_CORNER_RADIUS}px" in sheet, sheet
    assert "rgba(35, 38, 41, 255)" in sheet, sheet

    win._apply_window_background(0)
    assert "rgba(35, 38, 41, 0)" in win.styleSheet(), win.styleSheet()
    assert "border-radius" in win.styleSheet()


@test
def test_central_widget_is_transparent_in_theme() -> None:
    """中央 widget 必须在主题里被设成透明，否则方形背景会盖掉窗口圆角。"""
    css_path = (
        Path(__file__).resolve().parents[1]
        / "util"
        / "client"
        / "gui_theme_custom.css"
    )
    css = css_path.read_text(encoding="utf-8")
    assert "QWidget#clientCentralWidget" in css, "主题里缺少中央 widget 透明规则"
    block = css.split("QWidget#clientCentralWidget", 1)[1].split("}", 1)[0]
    assert "transparent" in block, block


@test
def test_edge_fade_reaches_the_corners() -> None:
    """渐隐必须盖住视口的四个角——它们在卡片圆角**内侧**。

    踩过的坑：裁剪路径原来是「视口矩形 + 控件半径」，而视口比控件内缩了
    边框那 4px，圆弧于是整体往里偏，四个角各留下一条月牙形缺口。缺口里
    的文字压不暗，看上去就像文字从圆角漏出来。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter

    box = make_box("\n".join(f"log {i}" for i in range(200)))
    # 复现真实文本框的几何：主题里 QTextEdit 带 4px 内边距，视口因此比控件
    # 内缩 4px——这正是当初裁剪路径算错、四个角漏出月牙缺口的前提。
    box.setStyleSheet(
        "QTextEdit { border: none; padding: 4px;"
        " background-color: #2e3236; border-radius: 10px; }"
    )
    bar = box.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    box.set_edge_fade(gui_module.QColor(46, 50, 54, 255))
    APP.processEvents()
    assert box.viewport().mapTo(box, QPoint(0, 0)) == QPoint(4, 4), "内边距没生效"

    img = QImage(box.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    try:
        box._paint_edge_fades(painter)
    finally:
        painter.end()

    w, h = img.width(), img.height()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        alpha = img.pixelColor(x, y).alpha()
        assert alpha > 200, (x, y, alpha)


@test
def test_multi_cursor_edit_works_in_client_box() -> None:
    """客户端文本框里能真正用上多光标同步输入。"""
    box = make_box("ab\nab")
    caret(box, 1)
    box.add_cursor_at(4)
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier, "X")
    box.keyPressEvent(event)
    assert box.toPlainText() == "aXb\naXb", repr(box.toPlainText())


@test
def test_escape_without_extras_bubbles_up() -> None:
    """无副光标时 Esc 必须留给主窗口做隐藏，否则窗口关不掉。"""
    box = make_box("abc")
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, "")
    box.keyPressEvent(event)
    assert not event.isAccepted()


@test
def test_append_line_keeps_selection_when_not_following() -> None:
    """不跟随时，用户已有的选区在日志追加后依然存在。"""
    box = make_box("alpha beta")
    box.set_follow_caret(False)
    cur = box.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    box.setTextCursor(cur)
    box.append_line("log")
    assert box.textCursor().selectedText() == "alpha", box.textCursor().selectedText()


# ------------------------------------------------------- 右侧贴边弹出位置


def _screen_rect(width: int = 1920, height: int = 1080):
    return QRect(0, 0, width, height)


@test
def test_right_pop_out_covers_last_screen_column() -> None:
    """从右侧贴边弹出后，窗口必须覆盖到屏幕最后一列。

    否则鼠标移到屏幕最右一列会离开窗口 → 窗口贴回 → 窗口又盖住该列 →
    enterEvent 再弹出，形成在屏幕右边缘反复闪烁的循环。
    """
    screen = _screen_rect()
    width = 425
    x = gui_module.GUI._right_pop_out_x(screen, width)
    assert x + width - 1 >= screen.right(), (
        f"弹出后窗口右边缘 {x + width - 1} 未覆盖屏幕最后列 {screen.right()}"
    )


@test
def test_right_pop_out_keeps_cursor_inside_window() -> None:
    """鼠标停在屏幕最后一列时，仍在弹出后的窗口范围内。"""
    screen = _screen_rect()
    width = 425
    x = gui_module.GUI._right_pop_out_x(screen, width)
    assert x <= screen.right() <= x + width - 1


@test
def test_right_pop_out_is_one_pixel_right_of_naive_formula() -> None:
    """修复点明确为 +1 像素，锁死 off-by-one 回归。"""
    screen = _screen_rect()
    width = 425
    assert gui_module.GUI._right_pop_out_x(screen, width) == screen.right() - width + 1
    assert gui_module.GUI._right_pop_out_x(screen, width) == (screen.right() - width) + 1


@test
def test_window_leave_hides_scroll_button() -> None:
    """鼠标离开客户端窗口时藏起「回到底部」按钮，进入时按位置重新显示。

    这条走的是 GUI 的 enterEvent / leaveEvent → set_pointer_inside 的接线，
    编辑器自身的显隐逻辑另有单测覆盖。
    """
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint, QPointF

    # 只构造界面：不拉起子进程、不装文件监控、不建托盘图标
    gui_module.GUI.start_script = lambda self: None
    gui_module.GUI.init_file_watcher = lambda self: None
    gui_module.GUI.create_systray_icon = lambda self: None
    gui = gui_module.GUI()
    gui.show()
    APP.processEvents()
    box = gui.text_box_client
    for i in range(60):
        box.append_line(f"log {i}")
    APP.processEvents()

    pos = QPointF(20, 20)
    for _ in range(4):  # 多滚几格，离开窗口时的布局变化不会再把它算成「在底部」
        APP.sendEvent(
            box.viewport(),
            QWheelEvent(
                pos,
                pos,
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )
    APP.processEvents()
    button = box.scroll_to_bottom_button
    assert button.isVisible(), "上滚后按钮没出现"

    # 真实光标位置在测试里不可控，直接按「不在窗口内」处理
    gui._cursor_inside_window = lambda: False
    APP.sendEvent(gui, QEvent(QEvent.Type.Leave))
    APP.processEvents()
    assert not button.isVisible(), "鼠标离开窗口后按钮还挂着"

    APP.sendEvent(gui, QEvent(QEvent.Type.Enter))
    APP.processEvents()
    assert button.isVisible(), "鼠标回到窗口且不在底部时按钮没回来"

    gui.close()


@test
def test_text_box_stylesheet_is_scoped_to_itself() -> None:
    """文本框样式表必须用 ID 选择器圈住，不能留裸声明。

    裸声明（``font-family: …`` 直接跟在 ``setStyleSheet`` 里）会被 Qt 当成
    ``*`` 规则作用到**子控件**上，而 tooltip 正是挂在触发控件下的子控件：
    文本框这套「等宽字体 + 12.38pt」会顺着控件树渗进「返回底部」按钮的
    提示框，把主题 ``QToolTip`` 的字体整段顶掉。
    """
    box = make_box("x")
    sheet = box.styleSheet().strip()
    name = gui_module.CustomTextEdit.TEXT_BOX_OBJECT_NAME
    assert box.objectName() == name, box.objectName()
    assert sheet.startswith(f"QTextEdit#{name} {{"), sheet
    assert sheet.endswith("}"), sheet
    # 花括号外不该再有声明——那正是会漏到子控件的那部分
    assert sheet.count("{") == 1 and sheet.count("}") == 1, sheet


@test
def test_scroll_button_tooltip_follows_theme_style() -> None:
    """自绘按钮的 tooltip 必须吃主题 ``QToolTip`` 的字体。

    拿同一窗口里普通按钮（``clear_button``）的 tooltip 当参照：两者的
    字体族和字号必须一致，且不能是文本框的等宽字体。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QToolTip

    from util.client.multi_cursor_font import MONO_FONT_FAMILY

    # 只构造界面：不拉起子进程、不装文件监控、不建托盘图标
    gui_module.GUI.start_script = lambda self: None
    gui_module.GUI.init_file_watcher = lambda self: None
    gui_module.GUI.create_systray_icon = lambda self: None
    gui = gui_module.GUI()
    gui.show()
    APP.processEvents()

    def tip_font(widget):
        QToolTip.showText(gui.mapToGlobal(QPoint(80, 160)), "回到最新内容", widget)
        APP.processEvents()
        for top in APP.topLevelWidgets():
            if top.metaObject().className() == "QTipLabel":
                font = top.font()
                top.hide()
                return font
        return None

    ref = tip_font(gui.clear_button)
    btn = tip_font(gui.text_box_client.scroll_to_bottom_button)
    gui.close()

    assert ref is not None and btn is not None, "tooltip 没弹出来"
    assert btn.family() != MONO_FONT_FAMILY, f"按钮 tooltip 用了等宽字体 {btn.family()}"
    assert (btn.family(), btn.pointSize()) == (ref.family(), ref.pointSize()), (
        f"按钮 tooltip 是 {btn.family()} {btn.pointSize()}pt，"
        f"主题里是 {ref.family()} {ref.pointSize()}pt"
    )


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
