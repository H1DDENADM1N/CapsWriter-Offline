"""多光标文本编辑器。

为本项目客户端主界面的文本框提供 VS Code 风格的多光标编辑能力，
以及「未监听时不抢光标」的日志追加行为。

设计要点：
- 主光标仍是 QTextEdit 自带的 ``textCursor()``；副光标存放在
  ``_extra_cursors`` 列表里，位置总是以「文档未变更」为前提，因此在
  任何编辑动作前后都要重新排序、收敛。
- 副光标的插入符与选区直接在**自身 viewport 的 paintEvent** 里画：
  与文字、选区共用同一块画布、同一个绘制时机，不依赖子控件叠加层
  （透明子控件的合成在不同平台/DPI 下不可靠）。
- 一次多光标编辑包在 ``QTextCursor.beginEditBlock()`` 里，这样一次
  ``Ctrl+Z`` 撤回的是「所有光标的一次输入」，而不是逐光标的编辑。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    Property,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QGuiApplication,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from util.client.word_segment import word_end_at, word_range_at, word_start_at

__all__ = [
    "FindBar",
    "FindLineEdit",
    "MultiCursorTextEdit",
    "ScrollToBottomButton",
]


SELECTION_COLOR = QColor(38, 79, 120, 160)


class ScrollToBottomButton(QAbstractButton):
    """浮在文本框底部的滚动快捷按钮。

    默认是「回到底部」（向下的 chevron）；按住 Shift 悬停时翻转为
    「回到顶部」，图标随之转 180°。

    图标为什么自绘而不是用 ``Segoe MDL2 Assets`` 的字形：字体字形没法做
    旋转动画，只能在两个字符之间硬切，看起来像闪了一下。这里画一条
    chevron 路径，翻转就是一个 0→180° 的缓动旋转，配合同样缓动的
    底色/描边变化，切换才顺。

    焦点策略固定为 ``NoFocus``：点完按钮焦点仍在文本框上，用户可以立刻
    继续输入，不必再点一次编辑区。
    """

    SIZE = 30
    # 距视口底边的间距。取 6px 让它整体落进底部渐隐带（28px）里：
    # 内容从按钮后面淡出，视觉上是「浮在文字上方」而不是「压在文字上」。
    MARGIN = 6
    # 翻转动画时长（毫秒）。180° 旋转，太长会「拖」，太短会显得生硬。
    FLIP_MS = 180
    # 悬停配色过渡时长
    HOVER_MS = 120
    # Shift 键状态轮询间隔：只在悬停期间跑，40ms 足够跟手又不费 CPU
    MODIFIER_POLL_MS = 40

    MODE_BOTTOM = "bottom"
    MODE_TOP = "top"

    # 配色（与 gui_theme_custom.css 的 teal 主题一致）
    _BG = QColor(28, 32, 35, 240)
    _BG_HOVER = QColor(0, 178, 148, 90)
    _BORDER = QColor(0, 178, 148, 150)
    _BORDER_HOVER = QColor(0, 178, 148, 255)
    _ICON = QColor(159, 230, 216)
    _ICON_HOVER = QColor(255, 255, 255)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 自己画背景：主题的 QWidget { background-color } 会给这个子控件刷一层
        # 不透明底，把圆角外面的角落填成方块。
        #
        # 规则必须用 ID 选择器限定在自己身上，不能写成裸声明
        # （``background: transparent``）——裸声明会作为 ``*`` 规则作用到
        # 子控件，而 tooltip 正是挂在触发控件下的子控件：背景被这条规则
        # 抢走后就变成系统默认的白底方块，QToolTip 那套深色描边样式全丢。
        #
        # 字体不用在这里写：文本框的等宽字体曾经顺着控件树漏进来，但根源
        # 在 CustomTextEdit 的样式表用了裸声明，那边已改成 ID 选择器；
        # 这里再写一遍 font 只是重复，主题的 QToolTip 规则已经能正常生效。
        self.setObjectName("scrollToBottomButton")
        self.setStyleSheet(
            "#scrollToBottomButton {"
            " background: transparent;"
            "}"
        )
        self._mode = self.MODE_BOTTOM
        self._flip = 0.0
        self._hover = 0.0
        self._flip_anim = QPropertyAnimation(self, b"flip", self)
        self._flip_anim.setDuration(self.FLIP_MS)
        self._flip_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(self.HOVER_MS)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # 鼠标停在按钮上不动时也要能感知 Shift 的按下/松开
        self._modifier_timer = QTimer(self)
        self._modifier_timer.setInterval(self.MODIFIER_POLL_MS)
        self._modifier_timer.timeout.connect(self.sync_modifier_state)
        self.set_mode(self.MODE_BOTTOM, animated=False)
        self.hide()

    # ------------------------------------------------------------- 动画属性

    def _get_flip(self) -> float:
        return self._flip

    def _set_flip(self, value: float) -> None:
        self._flip = float(value)
        self.update()

    flip = Property(float, _get_flip, _set_flip)

    def _get_hover_progress(self) -> float:
        return self._hover

    def _set_hover_progress(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)

    # ----------------------------------------------------------------- 模式

    @property
    def mode(self) -> str:
        """当前语义：``bottom`` 回到底部 / ``top`` 回到顶部。"""
        return self._mode

    def set_mode(self, mode: str, animated: bool = True) -> None:
        """切换语义并（可选）播放 180° 翻转动画。"""
        if mode not in (self.MODE_BOTTOM, self.MODE_TOP):
            raise ValueError(mode)
        self._mode = mode
        self.setToolTip("回到顶部" if mode == self.MODE_TOP else "回到最新内容")
        target = 1.0 if mode == self.MODE_TOP else 0.0
        self._flip_anim.stop()
        if not animated:
            self._set_flip(target)
            return
        self._flip_anim.setStartValue(self._flip)
        self._flip_anim.setEndValue(target)
        self._flip_anim.start()

    def sync_modifier_state(self) -> None:
        """按当前 Shift 状态同步模式（按住 Shift = 回到顶部）。"""
        modifiers = QGuiApplication.queryKeyboardModifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        wanted = self.MODE_TOP if shift else self.MODE_BOTTOM
        if wanted != self._mode:
            self.set_mode(wanted)

    # ----------------------------------------------------------------- 事件

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().enterEvent(event)
        self.sync_modifier_state()
        self._modifier_timer.start()
        self._animate_hover(1.0)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().leaveEvent(event)
        self._modifier_timer.stop()
        self._animate_hover(0.0)
        # 移开就回到默认语义：否则下次进来会「带着」上一次的 Shift 状态
        self.set_mode(self.MODE_BOTTOM)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 移动过程中也实时判断：比等 40ms 轮询更跟手
        self.sync_modifier_state()
        super().mouseMoveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """藏起来就停掉轮询，并把语义复位成「回到底部」。"""
        super().hideEvent(event)
        self._modifier_timer.stop()
        self.set_mode(self.MODE_BOTTOM, animated=False)

    def _animate_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    # ----------------------------------------------------------------- 绘制

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            radius = rect.width() / 2.0
            hover = max(0.0, min(1.0, self._hover))

            painter.setPen(QPen(_mix(self._BORDER, self._BORDER_HOVER, hover), 1.0))
            painter.setBrush(_mix(self._BG, self._BG_HOVER, hover))
            painter.drawRoundedRect(rect, radius, radius)

            # chevron：默认朝下，flip=1 时转 180° 朝上
            painter.save()
            painter.translate(rect.center())
            painter.rotate(180.0 * self._flip)
            path = QPainterPath()
            path.moveTo(-4.6, -2.2)
            path.lineTo(0.0, 2.6)
            path.lineTo(4.6, -2.2)
            pen = QPen(_mix(self._ICON, self._ICON_HOVER, hover), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()
        finally:
            painter.end()


def _mix(start: QColor, end: QColor, ratio: float) -> QColor:
    """两色线性插值（含 alpha），用于悬停渐变。"""
    t = max(0.0, min(1.0, float(ratio)))
    return QColor(
        round(start.red() + (end.red() - start.red()) * t),
        round(start.green() + (end.green() - start.green()) * t),
        round(start.blue() + (end.blue() - start.blue()) * t),
        round(start.alpha() + (end.alpha() - start.alpha()) * t),
    )


class FindLineEdit(QLineEdit):
    """查找 / 替换输入框。

    ``QLineEdit`` 自带 ``returnPressed`` 只覆盖纯回车，组合键需要自己
    识别：``Shift+Enter`` 找上一个、``Ctrl+Alt+Enter`` 全部替换、
    ``Tab`` / ``Shift+Tab`` 在查找框与替换框之间切换。

    之所以做成子类而不是在 ``FindBar`` 里过滤按键：``QLineEdit`` 会先
    消费掉 ``Tab``（把它挪成焦点切换），在父控件里就再也收不到这个键。
    """

    find_prev_requested = Signal()
    replace_all_requested = Signal()
    focus_switch_requested = Signal(bool)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt 命名
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if ctrl and alt:
                self.replace_all_requested.emit()
                event.accept()
                return
            if shift:
                self.find_prev_requested.emit()
                event.accept()
                return
            # 纯回车：交给 ``returnPressed``（查找下一个 / 替换当前）
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Tab:
            self.focus_switch_requested.emit(not shift)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Backtab:
            self.focus_switch_requested.emit(False)
            event.accept()
            return

        super().keyPressEvent(event)


class FindBar(QWidget):
    """编辑器顶部的轻量查找栏（Ctrl+F）/ 替换栏（Ctrl+H）。

    查找与替换**共用同一个浮层**：第一行是查找，第二行是替换。
    ``Ctrl+F`` 只显示第一行（与旧的查找栏完全一致），``Ctrl+H`` 把第二行
    一并展开。切换模式时不清空已经输入的查找词/替换词——用户按错一次
    ``Ctrl+F`` 不该丢掉刚打好的关键词。

    替换动作的语义与 VS Code 一致：
    - 「替换」：若当前选区正好是一个匹配，替换它并跳到下一个匹配；
      否则先定位下一个匹配并**就地替换**（连点即连续替换）。
    - 「全部替换」：替换全文所有匹配。
    """

    def __init__(self, editor: "MultiCursorTextEdit") -> None:
        super().__init__(editor)
        self._editor = editor
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget { background: #2e3236; border: 1px solid #4a4f55; }"
            "QLineEdit { background: #23272b; color: #e6e6e6;"
            " border: 1px solid #4a4f55; padding: 2px 4px; }"
            "QPushButton { background: #3a3f45; color: #e6e6e6;"
            " border: none; padding: 3px 8px; }"
            "QPushButton:hover { background: #4a4f55; }"
            "QPushButton:disabled { color: #7a8087; }"
            # 客户端主题 CSS 把 Segoe MDL2 Assets 设给了**所有** QLabel 与
            # QPushButton（那是给图标用的）。本浮层写的是「上一个 / 下一个 /
            # 替换 / 全部替换 / 3/8」这类中文与数字，沿用图标字体会被画成
            # 一串图标字形。这里显式改回普通文本字体。
            #
            # 必须写在**样式表**里而不是 setFont()：Qt 中样式表指定的字体
            # 优先级高于控件自身的 font 属性，setFont 会被应用级 CSS 盖掉。
            # 控件自身的样式表又优先于应用级样式表，所以这里的规则生效。
            "QLabel, QPushButton { font-family: 'Microsoft YaHei UI',"
            " 'Microsoft YaHei', 'Segoe UI'; font-size: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # ---- 第一行：查找 ----
        find_row = QHBoxLayout()
        find_row.setContentsMargins(0, 0, 0, 0)
        find_row.setSpacing(4)
        self.line_edit = FindLineEdit(self)
        self.line_edit.setPlaceholderText("查找")
        self.line_edit.returnPressed.connect(self.find_next)
        find_row.addWidget(self.line_edit, 1)
        self.prev_button = QPushButton("上一个", self)
        self.prev_button.clicked.connect(self.find_prev)
        find_row.addWidget(self.prev_button)
        self.next_button = QPushButton("下一个", self)
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)
        self.match_label = QLabel("", self)
        self.match_label.setMinimumWidth(72)
        self.match_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        find_row.addWidget(self.match_label)
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.close)
        find_row.addWidget(self.close_button)
        layout.addLayout(find_row)

        # ---- 第二行：替换（默认隐藏，Ctrl+H 展开）----
        # 注意：整行要装进一个 **QWidget** 容器。``QLayout`` 没有
        # ``setVisible``，且隐藏 layout 本身不会让其中的子控件消失。
        self.replace_panel = QWidget(self)
        replace_row = QHBoxLayout(self.replace_panel)
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.setSpacing(4)
        self.replace_edit = FindLineEdit(self.replace_panel)
        self.replace_edit.setPlaceholderText("替换")
        self.replace_edit.returnPressed.connect(self.replace_current)
        replace_row.addWidget(self.replace_edit, 1)
        self.replace_button = QPushButton("替换", self.replace_panel)
        self.replace_button.clicked.connect(self.replace_current)
        replace_row.addWidget(self.replace_button)
        self.replace_all_button = QPushButton("全部替换", self.replace_panel)
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_row.addWidget(self.replace_all_button)
        layout.addWidget(self.replace_panel)

        # 查找框文本变化时实时更新匹配计数
        self.line_edit.textChanged.connect(self.update_match_count)
        # 光标移动也会改变「第 i/N 处」里的 i，所以也要跟着刷新
        editor.cursorPositionChanged.connect(self.update_match_count)
        self.hide()
        self._replace_mode = False
        self.replace_panel.setVisible(False)

        # 组合键：Shift+Enter 找上一个、Ctrl+Alt+Enter 全部替换、
        # Tab/Shift+Tab 在查找框与替换框之间切换。
        for edit in (self.line_edit, self.replace_edit):
            edit.find_prev_requested.connect(self.find_prev)
            edit.replace_all_requested.connect(self.replace_all)
            edit.focus_switch_requested.connect(self._switch_focus)

    # ------------------------------------------------------------- 模式切换

    @property
    def replace_mode(self) -> bool:
        """当前是否处于「替换模式」（第二行可见）。"""
        return self._replace_mode

    def open(self, replace_mode: bool = False) -> None:
        """显示浮层并把焦点交给查找输入框。

        保留已选中的文本作为关键词；**不**清空上一次输入的查找词与
        替换词——用户按错一次 ``Ctrl+F`` 不该丢掉刚打好的关键词。

        ``replace_mode=True``（Ctrl+H）时展开替换行；否则若当前已经是
        替换模式则**保持**替换模式，只把焦点交回查找框。
        """
        selected = self._editor.textCursor().selectedText()
        if selected:
            self.line_edit.setText(selected)
        if replace_mode:
            self._replace_mode = True
        self.replace_panel.setVisible(self._replace_mode)
        self.show()
        self.raise_()
        self.reposition()
        self.line_edit.setFocus()
        self.line_edit.selectAll()
        self.update_match_count()

    def _switch_focus(self, forward: bool) -> None:
        """在查找框与替换框之间切换焦点。

        查找框 → 替换框 → 查找框 循环（``forward`` 为假则反向）。
        不在替换模式时只有查找框一个目标，Tab 保持焦点不动。
        """
        if not self._replace_mode:
            self.line_edit.setFocus()
            return
        if forward:
            if self.line_edit.hasFocus():
                self.replace_edit.setFocus()
                self.replace_edit.selectAll()
            else:
                self.line_edit.setFocus()
                self.line_edit.selectAll()
            return
        if self.replace_edit.hasFocus():
            self.line_edit.setFocus()
            self.line_edit.selectAll()
        else:
            self.replace_edit.setFocus()
            self.replace_edit.selectAll()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """隐藏/关闭时清掉边距，把视口还原成占满整个编辑器的尺寸。

        用 hideEvent 而不是 closeEvent：``close()``、``hide()``、父窗口隐藏
        最终都会走到这里，不会漏掉某条退出路径。

        解释器退出时 Qt 可能已先销毁 C++ 对象，此时访问编辑器会抛
        RuntimeError；边距已无意义，直接忽略以免在 stderr 吐异常。
        """
        editor = getattr(self, "_editor", None)
        if editor is not None:
            try:
                editor.setViewportMargins(0, 0, 0, 0)
                editor.viewport().update()
            except RuntimeError:
                pass
        super().hideEvent(event)

    def reposition(self) -> None:
        """贴在父编辑器顶部，并把正文视口推到它下方。

        宽度取「视口宽度」而不是「编辑器宽度」：编辑器右侧还有 12px
        垂直滚动条，全宽会把它顶部盖住，用户拖不动滚动条。
        """
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        height = self.sizeHint().height()
        self.setFixedWidth(max(1, parent.viewport().width()))
        self.setFixedHeight(height)
        self.move(0, 0)
        # 只有开着的时候才占位，避免隐藏状态下永久留白
        parent.setViewportMargins(0, height, 0, 0)

    def find_next(self) -> None:
        self._editor.find_next(self.line_edit.text())

    def find_prev(self) -> None:
        self._editor.find_next(self.line_edit.text(), backward=True)

    def replace_current(self) -> None:
        self._editor.replace_current_match(
            self.line_edit.text(), self.replace_edit.text()
        )
        self.update_match_count()

    def replace_all(self) -> None:
        self._editor.replace_all_matches(
            self.line_edit.text(), self.replace_edit.text()
        )
        self.update_match_count()

    def update_match_count(self) -> None:
        """刷新「第 i/N 处」计数。

        计数只依赖查找词与文档内容，**不**依赖当前光标位置，所以
        查找框文本一变就能立刻算出来。
        """
        needle = self.line_edit.text()
        if not needle:
            self.match_label.setText("")
            return
        try:
            total, current = self._editor.find_match_info(needle)
        except RuntimeError:
            # 解释器退出阶段 Qt 对象可能已销毁，忽略即可
            return
        if total == 0:
            self.match_label.setText("无匹配")
        else:
            self.match_label.setText(f"{current}/{total}")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self._editor.setFocus()
            event.accept()
            return
        super().keyPressEvent(event)


class MultiCursorTextEdit(QTextEdit):
    """带多光标编辑、「跟随末尾」开关与滚动渐隐的文本框。

    滚动行为分两层（见「滚动跟随与回到底部」一节）：

    - ``follow_caret``：监听开关，决定新日志到达时光标是否跟到末尾；
    - ``stick_to_bottom``：视图是否贴底，由**用户滚轮**驱动，
      用户往上翻看历史时挂起，滚回底部附近才恢复。
    """

    extra_cursor_count_changed = Signal(int)

    # 距底部多少像素内算「已经在底部」：用户滚进这个范围就恢复贴底跟随
    SCROLL_BOTTOM_THRESHOLD = 40
    # 滚轮停止多久算「滚动结束」（毫秒）
    SCROLL_SETTLE_MS = 150
    # 点击按钮后的平滑滚动时长（毫秒）
    SCROLL_ANIM_MS = 180
    # 会改变滚动位置的按键：同样算「用户主动滚动」，见 event()
    SCROLL_KEYS = frozenset(
        {
            Qt.Key.Key_PageUp,
            Qt.Key.Key_PageDown,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        }
    )
    # 上下边缘渐隐带的高度（像素）
    EDGE_FADE_HEIGHT = 28

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._follow_caret = True
        self._extra_cursors: list[QTextCursor] = []
        self._column_anchor: Optional[int] = None
        # 矩形列选锚点：像素坐标 (x, y) + 命中的视觉行。
        # 位置本身不足以描述列选——软换行的一行日志在文本上是同一个块里的
        # 多个视觉行，位置相同、像素行不同。
        self._column_anchor_point: Optional[tuple[int, int]] = None
        self._column_dragging = False
        self._column_moved = False
        # 矩形列选状态：命中时右击不再清空副光标，复制时按矩形整体取文本
        self._rect_active = False
        self._rect_spans: list[tuple[int, int]] = []
        self._rect_rows: list[dict] = []
        # 矩形整体的包围盒 (x_left, y_top, x_right, y_bottom)
        self._rect_bounds: Optional[tuple[int, int, int, int]] = None
        # 普通拖选（非 Alt）的锚点：用于修正 Qt 在软换行视觉行右边缘的塌陷
        self._plain_anchor: Optional[int] = None
        self._plain_dragging = False
        # 多光标模式下 Qt 自带光标必须隐藏（cursorWidth=0），否则它会另画
        # 一根由它自己的计时器控制的线，与我们画的副光标永远不同步。
        # 用户原本的粗细存在这里，退出多光标时原样恢复。
        self._user_cursor_width: Optional[int] = None
        # 副光标闪烁：与 Qt 主光标同相位同周期，见 _restart_caret_blink
        self._caret_phase = True
        self._caret_timer = QTimer(self)
        self._caret_timer.setSingleShot(False)
        self._caret_timer.timeout.connect(self._caret_blink_tick)
        # 副光标的选区高亮交给 Qt 排版层（背景在字形之下，文字可读）。
        # 自己用 fillRect 涂会把文字盖住，这是「列选遮挡文字」的根因。
        self._extra_selections: list[QTextEdit.ExtraSelection] = []
        self._host_selections: list[QTextEdit.ExtraSelection] = []
        # 多光标编辑的撤销/重做快照，见「撤销与光标还原」一节。
        self._edit_log: list[dict] = []
        self._redo_log: list[dict] = []
        self.find_bar = FindBar(self)
        self.find_bar.hide()
        # ---- 滚动跟随 / 回到底部 ----
        self._stick_to_bottom = True
        self._user_scrolling = False
        self._updating_scroll = False
        # 鼠标是否在客户端窗口内：不在时不显示「回到底部」按钮
        self._pointer_inside = True
        # 最近一次滚动的方向：-1 向下（朝底部）、1 向上。只有朝下滚才吸附。
        self._scroll_direction = 0
        self._scroll_button: Optional[ScrollToBottomButton] = None
        self._scroll_animation: Optional[QPropertyAnimation] = None
        self._scroll_settle_timer = QTimer(self)
        self._scroll_settle_timer.setSingleShot(True)
        self._scroll_settle_timer.setInterval(self.SCROLL_SETTLE_MS)
        self._scroll_settle_timer.timeout.connect(self._on_scroll_settled)
        self.verticalScrollBar().valueChanged.connect(self._update_scroll_affordance)
        self.verticalScrollBar().rangeChanged.connect(self._update_scroll_affordance)
        # 视口尺寸变了（改窗口大小、查找栏展开/收起）都要把按钮重新摆正
        self.viewport().installEventFilter(self)
        # ---- 上下边缘渐隐 ----
        self._edge_fade_height = int(self.EDGE_FADE_HEIGHT)
        self._edge_fade_color: Optional[QColor] = None
        # 视口圆角：渐隐带要按它裁剪，否则会把背景圆角涂成直角
        self._corner_radius = 0

    # ----------------------------------------------------------- 跟随末尾开关

    @property
    def follow_caret(self) -> bool:
        return self._follow_caret

    def set_follow_caret(self, follow: bool) -> None:
        self._follow_caret = bool(follow)

    # --------------------------------------------------------------- 日志追加

    def append_line(self, line: str) -> None:
        """追加一行日志。

        ``follow_caret`` 为真且视图贴底时行为等同 ``QTextEdit.append``
        （光标与滚动条跟随末尾）；否则保留用户的光标、选区与滚动位置。

        有选区时**不**把光标拉到末尾：``moveCursor(End)`` 会顺手清掉选区，
        用户刚「全选」的内容会在下一条日志到达时消失。

        用户用滚轮翻上去看历史时（``stick_to_bottom`` 为假）即使还在监听
        也不能滚屏：``QTextEdit.append`` 会把视图带到插入点，用户正在读的
        那几行会在下一条日志到达时被顶走。这种情况走「快照 → 追加 → 还原」。
        """
        if self._follow_caret and self._stick_to_bottom:
            self._stop_scroll_animation()
            if not self.textCursor().hasSelection():
                self.moveCursor(QTextCursor.MoveOperation.End)
            self.append(line)
            self._update_scroll_affordance()
            return
        self._stop_scroll_animation()
        saved = self._snapshot_state()
        self.append(line)
        self._restore_state(saved)
        self._update_scroll_affordance()

    def scroll_to_bottom_if_follow(self) -> None:
        """仅在跟随末尾且视图贴底时把光标与滚动条推到最后一行。

        同样不能在有选区时调用 ``moveCursor(End)``——它会把选区清掉。
        右键菜单关闭后窗口会补发一次 enterEvent（鼠标重新进入窗口），
        本方法正是从 enterEvent 调用的，所以这里必须保住选区。

        「视图贴底」这一条同样重要：用户上滚读历史时，鼠标进出窗口
        （enterEvent 会调本方法）不该把他拽回底部——那正是「翻上去就被
        拽下来」的另一种形态。此时只把「回到底部」按钮亮着。
        """
        if not self._follow_caret:
            return
        if not self._stick_to_bottom:
            self._update_scroll_affordance()
            return
        if not self.textCursor().hasSelection():
            self.moveCursor(QTextCursor.MoveOperation.End)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._update_scroll_affordance()

    # ------------------------------------------------ 滚动跟随与「回到底部」
    #
    # 语音输入时日志一直在追加，默认行为是「贴底跟随」：新内容一到就滚到
    # 最底部。但用户一旦用滚轮往上翻看历史，继续贴底就把人拽回去了。
    # 所以「跟随」被拆成两个互不干扰的状态：
    #
    # - ``_follow_caret``：监听开关（「监听」复选框），决定光标跟不跟末尾；
    # - ``_stick_to_bottom``：视图贴不贴底，由**滚轮**驱动，上滚即挂起。
    #
    # 挂起期间追加日志只保位置、不滚屏，并在下方浮出「回到底部」按钮；
    # 用户自己滚回距底部 ``SCROLL_BOTTOM_THRESHOLD`` 像素以内时恢复贴底
    # 并隐藏按钮。滚轮停手 ``SCROLL_SETTLE_MS`` 毫秒后才认为「滚动结束」，
    # 避免快速连滚时按钮反复闪。

    @property
    def stick_to_bottom(self) -> bool:
        """视图当前是否贴底跟随（用户上滚后为 False）。"""
        return self._stick_to_bottom

    @property
    def scroll_to_bottom_button(self) -> ScrollToBottomButton:
        """「回到底部」悬浮按钮；首次访问时创建。"""
        button = self._scroll_button
        if button is None:
            button = self._create_scroll_button()
        return button

    def scroll_to_bottom(self, animated: bool = True) -> None:
        """滚到最底部并恢复贴底跟随（按钮点击 / 外部调用）。"""
        self._stick_to_bottom = True
        self._animate_scroll_to(self.verticalScrollBar().maximum(), animated)

    def scroll_to_top(self, animated: bool = True) -> None:
        """滚到最顶部并**挂起**贴底跟随。

        挂起是必须的：否则下一条日志一到，视图又被拽回底部，用户刚翻上去
        的内容就白翻了。挂起后按钮继续亮着，点它就能回来。
        """
        self._stick_to_bottom = False
        self._animate_scroll_to(0, animated)

    def _animate_scroll_to(self, target: int, animated: bool) -> None:
        """把滚动条缓动到 ``target``；``animated=False`` 时直接跳。"""
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), int(target)))
        self._stop_scroll_animation()
        if not animated or bar.value() == target:
            bar.setValue(target)
            self._update_scroll_affordance()
            return
        # 平滑滚动：滚动条值走一段缓动，比瞬间跳过去更像聊天类界面。
        # 动画对象必须存在 self 上，否则函数返回后就被回收、动画不动。
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(self.SCROLL_ANIM_MS)
        animation.setStartValue(bar.value())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._scroll_animation = animation

    def _stop_scroll_animation(self) -> None:
        """打断正在进行的平滑滚动。

        追加日志或用户滚轮都会立刻改变滚动位置，此时动画还按旧的目标值
        继续走，会把视图从刚滚到的位置又拉回去。停止已停止的动画是空操作。
        """
        animation = self._scroll_animation
        if animation is not None:
            animation.stop()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt 命名
        """滚轮 = 用户主动滚动：立刻挂起贴底跟随，再交给 Qt 滚动。"""
        self._stop_scroll_animation()
        # 记下方向：只有「往下滚」才允许吸附到底。系统把滚轮设成 1 行时
        # 一格只有十几像素，一进 40px 范围就吸附的话用户根本滚不上去。
        self._scroll_direction = -1 if event.angleDelta().y() < 0 else 1
        self._begin_user_scroll()
        super().wheelEvent(event)
        self._update_scroll_affordance()

    def _begin_user_scroll(self) -> None:
        """标记「用户正在滚动」并开始 150ms 的停手计时。"""
        self._user_scrolling = True
        self._stick_to_bottom = False
        self._scroll_settle_timer.start(self.SCROLL_SETTLE_MS)

    def _on_scroll_settled(self) -> None:
        """滚轮停手：结束「正在滚动」状态并重算按钮显隐。"""
        self._user_scrolling = False
        self._update_scroll_affordance()

    def event(self, event) -> bool:  # noqa: N802 - Qt 命名
        """键盘滚动（PgUp/PgDn/Home/End/方向键）同样算「用户主动滚动」。

        不这么做的话：用户按 PgUp 翻上去，按钮会亮（位置变了），但
        ``stick_to_bottom`` 还是真——下一条日志一来视图又被拽回底部，
        按钮和实际行为对不上。
        """
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in self.SCROLL_KEYS
        ):
            self._scroll_direction = (
                -1
                if event.key()
                in (Qt.Key.Key_PageDown, Qt.Key.Key_Down, Qt.Key.Key_End)
                else 1
            )
            self._begin_user_scroll()
            handled = super().event(event)
            self._update_scroll_affordance()
            return handled
        return super().event(event)

    def _update_scroll_affordance(self) -> None:
        """按当前滚动位置同步「贴底跟随」与「回到底部」按钮。

        连接在滚动条的 ``valueChanged`` / ``rangeChanged`` 上，因此追加
        日志、缩放字号、改窗口大小都会走到这里。
        """
        if self._updating_scroll:
            return
        self._updating_scroll = True
        try:
            bar = self.verticalScrollBar()
            distance = bar.maximum() - bar.value()
            at_bottom = distance <= self.SCROLL_BOTTOM_THRESHOLD
            if at_bottom:
                self._stick_to_bottom = True
                # 用户自己往下滚进 40px 范围：顺手吸附到底，省得差几个像素
                if (
                    self._user_scrolling
                    and distance > 0
                    and self._scroll_direction < 0
                ):
                    bar.setValue(bar.maximum())
            self._set_scroll_button_visible(bar.maximum() > 0 and not at_bottom)
        finally:
            self._updating_scroll = False

    def _create_scroll_button(self) -> ScrollToBottomButton:
        button = ScrollToBottomButton(self.viewport())
        button.clicked.connect(self._on_scroll_button_clicked)
        self._scroll_button = button
        self._reposition_scroll_button()
        return button

    def _on_scroll_button_clicked(self) -> None:
        """按按钮当前的语义滚动：默认回到底部，Shift 悬停时回到顶部。"""
        button = self._scroll_button
        if button is not None and button.mode == ScrollToBottomButton.MODE_TOP:
            self.scroll_to_top(animated=True)
        else:
            self.scroll_to_bottom(animated=True)

    def set_pointer_inside(self, inside: bool) -> None:
        """鼠标是否在客户端窗口内。

        按钮只在鼠标进入窗口时出现：鼠标移出窗口后它还挂着，会让人以为
        窗口里有个「多出来的控件」，而且离开时本来也点不到它。
        """
        inside = bool(inside)
        if inside == self._pointer_inside:
            return
        self._pointer_inside = inside
        self._update_scroll_affordance()

    def _set_scroll_button_visible(self, visible: bool) -> None:
        # 鼠标不在窗口里时一律不显示（滚动位置再「不在底部」也不显示）
        visible = visible and self._pointer_inside
        button = self._scroll_button
        if not visible:
            if button is not None and button.isVisible():
                button.hide()
            return
        if button is None:
            button = self._create_scroll_button()
        if not button.isVisible():
            button.show()
        button.raise_()
        self._reposition_scroll_button()

    def _reposition_scroll_button(self) -> None:
        """把按钮摆在视口底部正中（视口坐标，随视口大小变化）。"""
        button = self._scroll_button
        if button is None:
            return
        viewport = self.viewport()
        x = (viewport.width() - button.width()) // 2
        y = viewport.height() - button.height() - ScrollToBottomButton.MARGIN
        button.move(max(0, x), max(0, y))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 命名
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            self._reposition_scroll_button()
        return super().eventFilter(obj, event)

    # --------------------------------------------------------- 上下边缘渐隐

    def set_edge_fade(
        self,
        color: Optional[QColor] = None,
        height: Optional[int] = None,
    ) -> None:
        """设置边缘渐隐的颜色与高度。

        ``color`` 必须**等于**文本框自身的背景色（含透明度），渐隐带才
        不会显出一条色块——它做的就是把文字往背景色上「擦淡」。
        传 ``None`` 表示继续用调色板里的 Base 色。
        """
        if color is not None:
            self._edge_fade_color = QColor(color)
        if height is not None:
            self._edge_fade_height = max(0, int(height))
        self.viewport().update()

    def set_corner_radius(self, radius: int) -> None:
        """声明视口的圆角半径，渐隐带按这个圆角裁剪。

        圆角是**样式表**画在背景上的，渐隐带却是自己往视口上涂的矩形。
        不裁剪的话，上下两条渐隐带会把两个圆角重新涂成直角——背景圆角
        还在，只是被盖住了，看起来像「只有中间圆了」。
        """
        self._corner_radius = max(0, int(radius))
        self.viewport().update()

    def _paint_edge_fades(self, painter: QPainter) -> None:
        """在视口上下边缘画出渐隐遮罩。

        只有**该方向还有内容**时才画：滚到顶就没有上边渐隐、滚到底就没有
        下边渐隐。这样最新的一行永远是清晰可读的，同时渐隐本身也成了
        「上面/下面还有内容」的提示。
        """
        height = int(self._edge_fade_height)
        if height <= 0:
            return
        bar = self.verticalScrollBar()
        if bar.maximum() <= 0:
            return  # 内容没有溢出，没有可渐隐的东西
        rect = self.viewport().rect()
        if rect.height() <= height * 2:
            return  # 视口太矮，两条渐隐带会吃掉整块内容
        color = self._edge_fade_color
        if color is None:
            color = self.palette().color(QPalette.ColorRole.Base)
        painter.save()
        if self._corner_radius > 0:
            # 裁剪路径必须用**控件**的圆角矩形，不能拿视口矩形套控件的半径：
            # 视口比控件内缩了边框那几像素，圆弧会整体往里偏，四个角各留下
            # 一条月牙形缺口——缺口里的文字压不暗，看上去就像文字从圆角漏
            # 出来。半径不变、圆心换成控件的圆心，圆弧才和背景圆角重合。
            offset = self.viewport().mapTo(self, QPoint(0, 0))
            clip = QPainterPath()
            clip.addRoundedRect(
                QRectF(
                    -offset.x(),
                    -offset.y(),
                    self.width(),
                    self.height(),
                ),
                self._corner_radius,
                self._corner_radius,
            )
            painter.setClipPath(clip)
        try:
            if bar.value() > 0:
                self._paint_fade_band(
                    painter,
                    color,
                    rect.left(),
                    rect.top(),
                    rect.width(),
                    height,
                    top=True,
                )
            if bar.value() < bar.maximum():
                self._paint_fade_band(
                    painter,
                    color,
                    rect.left(),
                    rect.bottom() - height + 1,
                    rect.width(),
                    height,
                    top=False,
                )
        finally:
            painter.restore()

    @staticmethod
    def _paint_fade_band(
        painter: QPainter,
        color: QColor,
        x: int,
        y: int,
        width: int,
        height: int,
        top: bool,
    ) -> None:
        """画一条渐隐带：靠边不透明（把文字擦成背景色），向内渐透明。

        中间几个色标让衰减比线性更「陡」一些（近似 (1-t)^2）：线性渐变
        在视觉上会有明显的「一半位置还很浓」的断层感。
        """
        gradient = QLinearGradient(x, y, x, y + height)
        for position, factor in (
            (0.0, 1.0),
            (0.25, 0.82),
            (0.5, 0.55),
            (0.75, 0.26),
            (1.0, 0.0),
        ):
            stop = QColor(color)
            stop.setAlpha(int(round(color.alpha() * factor)))
            gradient.setColorAt(position if top else 1.0 - position, stop)
        painter.fillRect(QRect(x, y, width, height), gradient)

    # ------------------------------------------------------------- 状态快照

    def _snapshot_state(self) -> tuple:
        cur = self.textCursor()
        return (
            cur.position(),
            cur.anchor(),
            self.verticalScrollBar().value(),
        )

    def _restore_state(self, saved: tuple) -> None:
        position, anchor, scroll = saved
        cur = self.textCursor()
        cur.setPosition(anchor)
        cur.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        self.verticalScrollBar().setValue(scroll)

    # ------------------------------------------------------------- 事件转发

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.find_bar.isVisible():
            self.find_bar.reposition()
        self._reposition_scroll_button()

    # ------------------------------------------------------------- 副光标绘制

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """在视口自身上绘制边缘渐隐与副光标。

        直接与文字共用同一次绘制，避免透明子控件在不同平台/DPI 下
        被合成器丢弃（那正是「只看到选区、看不到竖线」的原因）。

        顺序：正文 → 上下渐隐 → 副光标。渐隐要压在文字上（它做的就是把
        文字擦淡），但要在光标之下——光标是操作指示，不该跟着文字一起
        变淡。
        """
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        try:
            self._paint_edge_fades(painter)
            if self._extra_cursors:
                # 主光标也在同一相位里重画：多光标模式下 Qt 自带光标已被隐藏，
                # 两者必须由同一段代码、同一相位画出来才能真同步。
                self._paint_all_carets(painter, self._caret_phase and self.hasFocus())
        finally:
            painter.end()

    def selection_color(self) -> QColor:
        """选区颜色与 Qt 原生选区完全一致。

        Qt 会自动给主光标画原生选区（用 ``palette Highlight``）。副光标
        如果另用一个半透明色，两边颜色就会不同——主光标那行被叠成
        混合色、副光标行是原色，用户看到的就是「只高亮了一行」。
        统一用同一个颜色，两边就分不出差别。
        """
        return self.palette().color(QPalette.ColorRole.Highlight)

    def caret_metrics(self) -> tuple[QColor, int]:
        """返回与 Qt 主光标一致的（颜色, 宽度）。

        主光标由 QTextEdit 自己绘制，用的是 ``palette(Text)`` 与
        ``cursorWidth()``；副光标必须跟随这两个值，否则两者外观不一。

        多光标模式下我们把真正的 ``cursorWidth`` 模成 0 来隐藏 Qt 自带光标，
        用户原本的粗细保存在 ``_user_cursor_width`` 里。
        """
        width = self._user_cursor_width
        if width is None:
            width = self.cursorWidth()
        return self.palette().color(QPalette.ColorRole.Text), max(1, width)

    def _paint_all_carets(self, painter: QPainter, on: bool) -> None:
        """把主光标与所有副光标画在同一个相位上。

        ``on`` 只控制**竖线**的亮灭——选区高亮必须常亮。
        早期版本用 ``on`` 把整段绘制都包住，灭相位时副光标的选区也跟着
        消失，屏幕上只剩 Qt 自己画的主光标原生选区，看起来就是
        「只高亮了一行」，并且因为闪烁而时有时无。
        """
        self._paint_one_caret(painter, self.textCursor(), on)
        for cur in self._extra_cursors:
            self._paint_one_caret(painter, cur, on)

    def selection_rects(self, cur: QTextCursor) -> list[QRect]:
        """把一段选区分成「每行一个矩形」，用于绘制高亮。

        为什么不能直接用 ``cursorRect(cur)``：对带选区的光标它返回的是
        零宽矩形（如 ``QRect(25, 4, 0, 15)``），``fillRect`` 宽度 0 等于
        什么都没画——这正是「列选只高亮一行」的根因（那一行是 Qt 自己
        画的主光标原生选区）。

        所以按块（行）拆分：每行取起止位置的 x，高度取该块的行高。
        这样跨行选区也能画成阶梯状，并正确支持矩形列选。

        **坐标系**：x 取自 ``cursorRect``、高度取自块高度，都是**视口坐标**
        （会随滚动条变化）。千万不能拿 ``blockBoundingRect`` 的 ``top()``
        当 y：那是**文档坐标**，滚动后能到几千，会把矩形整个画到视口外。
        日志框永远滚在底部，所以这个错误一上手就会发作。
        """
        if not cur.hasSelection():
            return []
        start, end = sorted((cur.anchor(), cur.position()))
        doc = self.document()
        rects: list[QRect] = []
        block = doc.findBlock(start)
        last = doc.findBlock(end)
        guard = 0
        while True:
            guard += 1
            if guard > doc.blockCount() + 2:  # 防御：绝不允许死循环
                break
            block_start = block.position()
            # block.length() 含末尾换行符，行内可见字符到 length()-1 为止
            block_end = block_start + max(0, block.length() - 1)
            seg_start = max(start, block_start)
            seg_end = min(end, block_end)
            if seg_end > seg_start:
                a = QTextCursor(doc)
                a.setPosition(seg_start)
                b = QTextCursor(doc)
                b.setPosition(seg_end)
                rect_a = self.cursorRect(a)
                rect_b = self.cursorRect(b)
                if rect_b.left() > rect_a.left():
                    rects.append(
                        QRect(
                            rect_a.left(),
                            rect_a.top(),
                            rect_b.left() - rect_a.left(),
                            rect_a.height(),
                        )
                    )
            if block == last:
                break
            block = block.next()
        return rects

    def _paint_one_caret(self, painter: QPainter, cur: QTextCursor, on: bool) -> None:
        """只画竖线（受 ``on`` 控制）；选区交给 ``setExtraSelections()``。

        为什么选区不能在这里用 ``fillRect`` 画：``paintEvent`` 里
        ``super().paintEvent()`` 已经把字形画好了，我们再往视口上涂不透明
        高亮，等于把文字整块盖住——实测副光标行可见文字像素为 0，
        用户看到的就是一块实心色块（主光标行因为是 Qt 原生选区所以正常）。

        ``setExtraSelections()`` 由排版层绘制，背景永远在字形**下面**，
        文字自然可读，且滚动、换行、缩放都由 Qt 自己维护，不用我们同步。
        """
        if not on:
            return
        rect = self.cursorRect(cur)
        color, width = self.caret_metrics()
        painter.fillRect(QRect(rect.left(), rect.top(), width, rect.height()), color)

    def extra_selections_count(self) -> int:
        """当前挂到 Qt 上的选区高亮条数（副光标各一条）。"""
        return len(self._extra_selections)

    def _build_extra_selection(self, cur: QTextCursor) -> Optional[QTextEdit.ExtraSelection]:
        """把一个带选区的光标转成 Qt 的 ExtraSelection；无选区返回 None。"""
        if not cur.hasSelection():
            return None
        selection = QTextEdit.ExtraSelection()
        copy = QTextCursor(self.document())
        copy.setPosition(cur.anchor())
        copy.setPosition(cur.position(), QTextCursor.MoveMode.KeepAnchor)
        selection.cursor = copy
        fmt = QTextCharFormat()
        fmt.setBackground(self.selection_color())
        # 前景色必须一起改：Qt 原生选区会把选中文字换成 HighlightedText
        # （本主题白色），只设背景的话副光标行的字仍是 Text 色，
        # 与主光标那行不一致，在深色高亮上还可能看不清。
        fmt.setForeground(
            self.palette().color(QPalette.ColorRole.HighlightedText)
        )
        selection.format = fmt
        return selection

    def _sync_extra_selections(self) -> None:
        """让 Qt 的选区高亮与副光标保持一一对应。

        每次副光标变动（新增、删除、编辑后重定位）都要重算，否则会残留
        旧位置的高亮，看起来像「幽灵选区」。

        走 ``super()`` 而不是 ``self.setExtraSelections``，避免把宿主设置的
        额外选区反复搬进 ``_host_selections`` 造成重复；合并在这里一次做。
        """
        built: list[QTextEdit.ExtraSelection] = []
        for cur in self._extra_cursors:
            sel = self._build_extra_selection(cur)
            if sel is not None:
                built.append(sel)
        self._extra_selections = built
        super().setExtraSelections(built + self._host_selections)

    def setExtraSelections(self, selections) -> None:  # noqa: N802 - Qt 命名
        """宿主若自己设置了额外选区，合并保留，互不吞掉。"""
        self._host_selections = list(selections)
        merged = self._extra_selections + self._host_selections
        super().setExtraSelections(merged)

    @property
    def caret_phase(self) -> bool:
        """当前闪烁相位：True = 亮（画竖线），False = 灭。"""
        return self._caret_phase

    @property
    def caret_blinking(self) -> bool:
        """副光标闪烁定时器是否在跑。"""
        return self._caret_timer.isActive()

    @property
    def caret_blink_interval(self) -> int:
        """闪烁半周期（毫秒）。"""
        return self._caret_timer.interval()

    def _paint_extra_cursor(self, painter: QPainter, cur: QTextCursor) -> None:
        """已由 ``_paint_one_caret`` 取代，保留仅为了兼容旧调用。"""
        self._paint_one_caret(painter, cur)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._restart_caret_blink()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # Qt 主光标失焦即隐去；副光标也必须一起隐去，否则窗口切走后仍留一排竖线
        self._caret_timer.stop()
        self.viewport().update()
        super().focusOutEvent(event)

    def _caret_blink_tick(self) -> None:
        """翻转相位并重绘所有光标。

        周期取自 ``QApplication.cursorFlashTime()``。注意：相位与 Qt 主光标的
        内部计时器并没有硬同步——单靠两个独立计时器永远会漂。真正保证
        同步的是：多光标模式下 Qt 画不了主光标（``cursorWidth=0``），
        主副光标全部由 ``_paint_all_carets`` 按这一个相位绘制。
        """
        if not self._extra_cursors:
            return
        self._caret_phase = not self._caret_phase
        self.viewport().update()

    # ----------------------------------------------------------- 查找与跳转

    def find_next(self, needle: str, backward: bool = False) -> bool:
        """查找并选中 ``needle`` 的下一个（或上一个）匹配。

        起点规则与 VS Code 一致：
        - 向后搜索：有选区时从选区末端开始，纯光标则从光标处开始；
        - 向前搜索：有选区时从选区起点之前开始，纯光标则从光标前一个字符开始。
        找不到时回绕到文档另一端；仍找不到就保持原光标不动并返回 False。
        """
        if not needle:
            return False
        text = self.toPlainText()
        cur = self.textCursor()
        if backward:
            begin = min(cur.position(), cur.anchor())
            idx = text.rfind(needle, 0, begin if begin > 0 else len(text))
            if idx == -1:
                idx = text.rfind(needle)
        else:
            begin = max(cur.position(), cur.anchor())
            idx = text.find(needle, begin)
            if idx == -1:
                idx = text.find(needle)
        if idx == -1:
            return False
        target = QTextCursor(self.document())
        target.setPosition(idx)
        target.setPosition(idx + len(needle), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(target)
        self.ensureCursorVisible()
        return True

    # ----------------------------------------------------------- 查找与替换

    def _match_spans(self, needle: str) -> list[tuple[int, int]]:
        """返回 ``needle`` 在文档中的所有匹配区间 ``[start, end)``。

        用 ``toPlainText()`` 的绝对下标，而不是 ``QTextCursor`` 的位置：
        两者在纯文本文档里一致，但 ``selectedText()`` 在跨行选区里用
        U+2029 作换行符，与文档里的 ``"\\n"`` 不一致——拿它当 needle
        在文档里根本找不到匹配。

        匹配之间**不重叠**（往后 ``len(needle)`` 个字符再找），与本模块
        既有的 ``_occurrence_spans`` 以及 ``str.count`` / ``str.replace``
        一致。这样「匹配计数」与「全部替换处数」永远对得上。
        """
        if not needle:
            return []
        text = self.toPlainText()
        spans: list[tuple[int, int]] = []
        idx = text.find(needle)
        while idx != -1:
            spans.append((idx, idx + len(needle)))
            idx = text.find(needle, idx + len(needle))
        return spans

    def find_match_info(self, needle: str) -> tuple[int, int]:
        """返回 ``(总匹配数, 当前匹配序号)``。

        「当前匹配序号」从 1 开始，取值规则与 VS Code 一致：
        - 选区正好覆盖某个匹配 → 就是那一项（``find_next`` 之后就是这种）；
        - 光标停在某个匹配内部 → 那一项；
        - 光标不在任何匹配里 → 指向**下一个**匹配（回绕时指向第一个），
          也就是「现在按回车会跳到的那一项」。

        计数只依赖查找词与文档内容，与选区之外的编辑状态无关。
        """
        spans = self._match_spans(needle)
        if not spans:
            return 0, 0
        cur = self.textCursor()
        if cur.hasSelection():
            sel_start = min(cur.position(), cur.anchor())
            sel_end = max(cur.position(), cur.anchor())
        else:
            sel_start = sel_end = cur.position()
        # 选区正好覆盖某个匹配
        for index, (start, end) in enumerate(spans, start=1):
            if start == sel_start and end == sel_end:
                return len(spans), index
        # 光标停在某个匹配内部
        for index, (start, end) in enumerate(spans, start=1):
            if start <= sel_start < end:
                return len(spans), index
        # 不在任何匹配里：指向下一个匹配；到末尾则回绕到第一个
        for index, (start, _end) in enumerate(spans, start=1):
            if start > sel_start:
                return len(spans), index
        return len(spans), 1

    def replace_current_match(self, needle: str, replacement: str) -> bool:
        """替换「当前」的一个匹配；返回是否发生了替换。

        语义与 VS Code 一致：
        - 当前选区正好是一个匹配 → 替换它，然后跳到下一个匹配并选中；
        - 否则 → 先定位下一个匹配并**就地替换**（连点即连续替换）。

        ``replacement`` 为空字符串表示「删除匹配」。

        替换前会收敛副光标：文档级操作之后副光标的位置全部失效，留着
        只会让下一次编辑落在错误的位置。收敛前的光标集合记进撤销栈，
        ``Ctrl+Z`` 会一并还原。
        """
        if not needle:
            return False
        text = self.toPlainText()
        cur = self.textCursor()
        start = min(cur.position(), cur.anchor())
        end = max(cur.position(), cur.anchor())

        # 分支一：当前选区正好就是一个匹配
        if end > start and end - start == len(needle) and text[start:end] == needle:
            target = (start, end)
        else:
            # 分支二：定位下一个匹配
            idx = text.find(needle, end)
            if idx == -1:
                idx = text.find(needle)
            if idx == -1:
                return False
            target = (idx, idx + len(needle))

        record = self._edit_begin()
        self.clear_extra_cursors()
        self._replace_span(target[0], target[1], replacement)
        # 替换后从「替换文本末尾」继续找下一个并选中
        self.find_next(needle)
        self._edit_end(record)
        return True

    def replace_all_matches(self, needle: str, replacement: str) -> int:
        """替换全文所有匹配；返回替换处数。

        从**后往前**替换：前面的替换会改变后面匹配的绝对位置，从后往前
        可以保证已处理区间的下标始终有效。

        整批替换包在一次 ``beginEditBlock/endEditBlock`` 里，所以
        「全部替换」只占**一步撤销**；同时用 ``_edit_begin/_edit_end``
        记录光标集合，撤销时主/副光标一并回到替换前。

        **不要**在替换后调用 ``setTextCursor(0)``：``setTextCursor`` 会让
        Qt 把视口滚到「光标可见」的位置，光标在 0 就等于把视图拉到文档
        顶部——用户看到的是「按一次全部替换，文本框跳到最上面、光标位置
        丢失」。Qt 自己会处理好光标位置：等长替换后光标原地不动，不等长
        替换后 Qt 把光标平移相应的位移量，选区仍覆盖同一段文本。
        """
        if not needle:
            return 0
        spans = self._match_spans(needle)
        if not spans:
            return 0

        # 记录要赶在收敛副光标**之前**：否则撤销时还原不了被收敛的那些
        record = self._edit_begin()
        self.clear_extra_cursors()

        editor = self.textCursor()
        editor.beginEditBlock()
        try:
            for start, end in reversed(spans):
                work = QTextCursor(self.document())
                work.setPosition(start)
                work.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                work.insertText(replacement)
        finally:
            editor.endEditBlock()

        self._edit_end(record)
        return len(spans)

    def _replace_span(self, start: int, end: int, replacement: str) -> None:
        """把 ``[start, end)`` 这段文本替换为 ``replacement``。

        只做文本替换，**不**自行记录撤销——撤销由调用方的
        ``_edit_begin/_edit_end`` 统一管理，这样「替换当前 + 跳到下一个」
        整体只占一步撤销。
        """
        work = QTextCursor(self.document())
        work.setPosition(start)
        work.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        work.insertText(replacement)
        # 光标停在替换文本末尾
        cur = QTextCursor(self.document())
        cur.setPosition(start + len(replacement))
        self.setTextCursor(cur)

    # ----------------------------------------------------------- 光标集合维护

    @property
    def extra_cursors(self) -> list[QTextCursor]:
        return list(self._extra_cursors)

    def extra_cursor_count(self) -> int:
        return len(self._extra_cursors)

    def add_cursor_at(self, position: int, anchor: Optional[int] = None) -> None:
        """在 ``position`` 处添加副光标；与主光标或已有副光标重合时忽略。"""
        anchor = position if anchor is None else anchor
        primary = self.textCursor()
        if position == primary.position() and anchor == primary.anchor():
            return
        if any(
            c.position() == position and c.anchor() == anchor
            for c in self._extra_cursors
        ):
            return
        cur = QTextCursor(self.document())
        cur.setPosition(anchor)
        cur.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
        self._extra_cursors.append(cur)
        self._sync_extra_cursors()

    def toggle_cursor_at(self, position: int, anchor: Optional[int] = None) -> None:
        """在 ``position`` 处加一个副光标；若已存在则移除。"""
        anchor = position if anchor is None else anchor
        before = len(self._extra_cursors)
        self._extra_cursors = [
            c
            for c in self._extra_cursors
            if not (c.position() == position and c.anchor() == anchor)
        ]
        if len(self._extra_cursors) == before:
            self.add_cursor_at(position, anchor)
        else:
            self._sync_extra_cursors()

    def clear_extra_cursors(self) -> None:
        """收敛为单光标，主光标位置保持不变。"""
        self._rect_active = False
        self._rect_spans = []
        self._rect_rows = []
        self._rect_bounds = None
        if not self._extra_cursors:
            return
        self._extra_cursors.clear()
        self._sync_extra_cursors()

    def _sync_extra_cursors(self) -> None:
        self._apply_cursor_width_mode()
        self._sync_extra_selections()
        self.viewport().update()
        self._restart_caret_blink()
        self.extra_cursor_count_changed.emit(len(self._extra_cursors))

    def _apply_cursor_width_mode(self) -> None:
        """按是否处于多光标模式切换 Qt 自带光标的可见性。

        有副光标时把 ``cursorWidth`` 置 0，Qt 就不再自己画主光标，
        主副光标改由 ``_paint_all_carets`` 在同一个相位上统一绘制。
        收敛回单光标时恢复用户原本的粗细，常规日志框行为完全不变。
        """
        if self._extra_cursors:
            if self._user_cursor_width is None:
                self._user_cursor_width = self.cursorWidth()
            if self.cursorWidth() != 0:
                super().setCursorWidth(0)
            return
        if self._user_cursor_width is not None:
            width = self._user_cursor_width
            self._user_cursor_width = None
            super().setCursorWidth(width)

    def setCursorWidth(self, width: int) -> None:  # noqa: N802 - Qt 命名
        """记住用户设定的粗细，并在非多光标模式下真正应用。"""
        self._user_cursor_width = int(width)
        if not self._extra_cursors:
            super().setCursorWidth(int(width))

    # -------------------------------------------------------------- 光标闪烁

    def _restart_caret_blink(self) -> None:
        """按 Qt 的闪烁周期重开副光标闪烁。

        周期取自 ``QApplication.cursorFlashTime()``（Windows 上读系统设置，
        默认 1060ms = 530ms 亮 + 530ms 灭）；停止时若 ``cursorFlashTime``
        为 0（系统关闭了光标闪烁），副光标也保持常亮。
        """
        self._caret_timer.stop()
        self._caret_phase = True
        flash_ms = int(QApplication.cursorFlashTime())
        if not self._extra_cursors:
            return
        if flash_ms <= 0:
            self._caret_phase = True
            return
        self._caret_timer.start(max(1, flash_ms // 2))

    def _all_edit_cursors(self) -> list[tuple[QTextCursor, bool]]:
        """主光标与副光标一起返回，按编辑起点降序排列（靠后的先改）。"""
        pairs: list[tuple[QTextCursor, bool]] = [(self.textCursor(), True)]
        pairs.extend((c, False) for c in self._extra_cursors)
        pairs.sort(
            key=lambda pair: (
                -min(pair[0].position(), pair[0].anchor()),
                -pair[0].position(),
            )
        )
        return pairs

    # ----------------------------------------------------------- 同步编辑动作

    def insert_text_at_cursors(self, text: str) -> None:
        """把所有光标处替换为 ``text``（光标若有选区则先删选区）。

        位置推导：光标按起点降序（从后往前）应用，此时比当前光标更靠前的
        位置全未被修改，所以每个光标先记下基于原文档的 ``base``；而更靠后
        位置的编辑不会改当前位置的索引。

        真正会推动本光标的是「比它更靠前」的编辑——那些在降序循环里还没
        发生。因此完成后各自补上后缀位移 ``suffix``（所有更靠前编辑的位移和）。
        旧实现直接把循环当时的绝对位置写回，漏了这一项，导致输入后副光标
        跨行错位、且连续输入时漂移越来越大。
        """
        pairs = self._all_edit_cursors()
        if not text and not any(c.hasSelection() for c, _ in pairs):
            return
        bases = [min(c.position(), c.anchor()) for c, _ in pairs]
        deltas = [len(text) - abs(c.position() - c.anchor()) for c, _ in pairs]
        record = self._edit_begin()
        editor = self.textCursor()
        editor.beginEditBlock()
        try:
            for cur, _is_primary in pairs:
                work = QTextCursor(cur)
                if work.hasSelection():
                    work.removeSelectedText()
                work.insertText(text)
        finally:
            editor.endEditBlock()
        suffix = self._suffix_shift(deltas)
        finals = [b + len(text) + s for b, s in zip(bases, suffix)]
        self._apply_edit_result(pairs, finals)
        self._edit_end(record)

    @staticmethod
    def _suffix_shift(deltas: list[int]) -> list[int]:
        """对每个下标返回「它之后所有编辑」的位移和。

        ``deltas`` 与光标列表同序（按起点降序），也就是靠后的光标在前。
        因此下标 i 之后的所有元素恰好就是「比它更靠前」的编辑。
        """
        suffix = [0] * len(deltas)
        running = 0
        for i in range(len(deltas) - 1, -1, -1):
            suffix[i] = running
            running += deltas[i]
        return suffix

    def delete_at_cursors(self, backward: bool = True) -> None:
        """在所有光标处删除一个字符（有选区则删选区）。

        位置推导同 ``insert_text_at_cursors``。区别只在光标终态：
        前向删除停在 ``base``，后向删除退到 ``base - 1``（有选区则退到选区起点）。
        """
        pairs = self._all_edit_cursors()
        bases = [min(c.position(), c.anchor()) for c, _ in pairs]
        has_sel = [c.hasSelection() for c, _ in pairs]
        sel_len = [abs(c.position() - c.anchor()) for c, _ in pairs]
        at_edge = [
            (b == 0) if backward else (b >= self.document().characterCount() - 1)
            for b in bases
        ]
        editor = self.textCursor()
        record = self._edit_begin()
        editor.beginEditBlock()
        try:
            for cur, _is_primary in pairs:
                work = QTextCursor(cur)
                if work.hasSelection():
                    work.removeSelectedText()
                    continue
                if backward:
                    if work.position() == 0:
                        continue
                    work.movePosition(
                        QTextCursor.MoveOperation.PreviousCharacter,
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    work.removeSelectedText()
                else:
                    if work.position() >= self.document().characterCount() - 1:
                        continue
                    work.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    work.removeSelectedText()
        finally:
            editor.endEditBlock()
        deltas: list[int] = []
        caret_offsets: list[int] = []
        for base, had_sel, slen, edge in zip(bases, has_sel, sel_len, at_edge):
            if had_sel:
                deltas.append(-slen)
                caret_offsets.append(0)
            elif edge:
                deltas.append(0)
                caret_offsets.append(0)
            else:
                deltas.append(-1)
                caret_offsets.append(-1 if backward else 0)
        suffix = self._suffix_shift(deltas)
        finals = [b + off + s for b, off, s in zip(bases, caret_offsets, suffix)]
        self._apply_edit_result(pairs, finals)
        self._edit_end(record)

    def _apply_edit_result(
        self,
        pairs: list[tuple[QTextCursor, bool]],
        positions: list[int],
    ) -> None:
        """把编辑后的绝对位置写回主光标与副光标。"""
        primary_pos = None
        extras: list[QTextCursor] = []
        limit = self.document().characterCount() - 1
        for (cur, is_primary), pos in zip(pairs, positions):
            pos = max(0, min(pos, limit))
            if is_primary:
                primary_pos = pos
                continue
            new = QTextCursor(self.document())
            new.setPosition(pos)
            if new.position() not in {e.position() for e in extras}:
                extras.append(new)
        if primary_pos is not None:
            cur = self.textCursor()
            cur.setPosition(primary_pos)
            self.setTextCursor(cur)
        self._extra_cursors = extras
        self._sync_extra_cursors()

    # ------------------------------------------------------- 撤销与光标还原
    #
    # Qt 的撤销栈只还原**文本**，不认识本控件的副光标。多光标编辑撤销之后
    # 文本确实回来了，但副光标（有时连主光标也）仍停在编辑后的位置——用户
    # 报障的「多光标删除文字再 Ctrl+Z 撤销删除，光标位置错乱」正是这个。
    #
    # 副光标之所以会错位，是因为它本身也是 ``QTextCursor``：文档被撤销时
    # Qt 会**自动**把这些光标平移到「看起来合理、其实不对」的偏移上。
    #
    # 做法：多光标编辑时记下「编辑前的文本特征 + 全部光标位置」；撤销时先让
    # Qt 回退文本，再用文本特征判断这次回退的**是不是**我们记下的那次编辑，
    # 是的话把光标集合显式写回去。

    def _text_signature(self) -> tuple[int, int]:
        """文档文本的轻量特征 ``(长度, hash)``。

        用来判断「一次撤销回退的到底是不是某一次特定编辑」：编辑前、编辑后
        与撤销之后各取一次特征，三者相等才认作同一次编辑。``hash`` 只在进程
        内稳定，而比较的两端都在同一进程内，故可用。
        """
        text = self.toPlainText()
        return (len(text), hash(text))

    def _capture_cursor_state(self) -> list[tuple[int, int, bool]]:
        """记录全部光标（主 + 副）的位置。

        每项是 ``(position, anchor, is_primary)``。
        """
        state: list[tuple[int, int, bool]] = []
        primary = self.textCursor()
        state.append((primary.position(), primary.anchor(), True))
        for cur in self._extra_cursors:
            state.append((cur.position(), cur.anchor(), False))
        return state

    def _restore_cursor_state(self, state) -> None:
        """把 ``_capture_cursor_state`` 记录的光标集合写回编辑器。"""
        doc = self.document()
        limit = max(0, doc.characterCount() - 1)
        primary = None
        extras: list[QTextCursor] = []
        for position, anchor, is_primary in state:
            cur = QTextCursor(doc)
            cur.setPosition(max(0, min(anchor, limit)))
            cur.setPosition(
                max(0, min(position, limit)), QTextCursor.MoveMode.KeepAnchor
            )
            if is_primary:
                primary = cur
            else:
                extras.append(cur)
        if primary is not None:
            self.setTextCursor(primary)
        self._extra_cursors = extras
        self._sync_extra_cursors()

    def _edit_begin(self) -> dict:
        """多光标编辑开始：抓一份「编辑前」的快照。"""
        return {
            "sig_before": self._text_signature(),
            "cursors_before": self._capture_cursor_state(),
        }

    def _edit_end(self, record: dict) -> None:
        """多光标编辑结束：补上「编辑后」的快照并入撤销栈。"""
        record["sig_after"] = self._text_signature()
        record["cursors_after"] = self._capture_cursor_state()
        if record["sig_before"] == record["sig_after"]:
            # 文本没变（例如所有光标都贴在文档边界上，删除无事可做），
            # 不必留一条撤销记录。
            return
        self._edit_log.append(record)
        if len(self._edit_log) > 200:
            del self._edit_log[0]
        self._redo_log.clear()

    def _undo_with_cursors(self) -> bool:
        """撤销一步；若回退的正是本控件的多光标编辑，一并还原光标集合。

        返回 False 表示「当前没有可撤销的内容」，交给 Qt 默认处理。

        匹配方式：撤销**之后**的文本若等于某条记录的「编辑前」文本，就说明
        这一步回退的正是那次编辑，把光标集合写回去；否则说明这一步撤销的
        是别的东西（例如中途追加的日志），记录原样留着，下一次撤销再匹配。
        """
        doc = self.document()
        if not doc.isUndoAvailable():
            return False
        record = self._edit_log[-1] if self._edit_log else None
        super().undo()
        if record is None:
            return True
        if self._text_signature() != record["sig_before"]:
            # 这一步撤销的不是我们记下的那次编辑（多半是中途追加的日志）。
            # 记录留在栈里，等下一次撤销时再匹配。
            return True
        self._restore_cursor_state(record["cursors_before"])
        self._edit_log.pop()
        self._redo_log.append(record)
        return True

    def _redo_with_cursors(self) -> bool:
        """重做一步；若重做的正是本控件的多光标编辑，一并还原光标集合。"""
        doc = self.document()
        if not doc.isRedoAvailable():
            return False
        record = self._redo_log[-1] if self._redo_log else None
        super().redo()
        if record is None:
            return True
        if self._text_signature() != record["sig_after"]:
            return True
        self._restore_cursor_state(record["cursors_after"])
        self._redo_log.pop()
        self._edit_log.append(record)
        return True

    def undo(self) -> None:
        """撤销一步；多光标编辑会一并还原光标集合。"""
        self._undo_with_cursors()

    def redo(self) -> None:
        """重做一步；多光标编辑会一并还原光标集合。"""
        self._redo_with_cursors()

    def _handle_undo_shortcut(self, event: QKeyEvent) -> bool:
        """处理 Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y。

        必须在这里自己接：``QTextEdit::undo()`` **不是虚函数**，Python 子类
        覆写它并不会被 Qt 内部的按键处理调用到（``QTextEdit::keyPressEvent``
        里直接调的是 C++ 版本），只在按键分发处拦截才真正生效。
        """
        mods = event.modifiers()
        if not mods & Qt.KeyboardModifier.ControlModifier:
            return False
        if mods & (
            Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        ):
            return False
        key = event.key()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Z:
            if shift:
                return self._redo_with_cursors()
            return self._undo_with_cursors()
        if key == Qt.Key.Key_Y and not shift:
            return self._redo_with_cursors()
        return False

    # ---------------------------------------------------------- 选中相同内容

    def _word_range_at(self, position: int) -> Optional[tuple[int, int]]:
        """返回 ``position`` 所在单词的 [start, end)；不在单词内返回 None。

        词边界规则见 ``util/client/word_segment.py``：

        - **汉字**走 jieba 词典分词——一整段汉字不再被当成一个词，
          「语音输入测试字符串」会切成「语音输入 / 测试 / 字符串」；
        - **ASCII** 走字母数字下划线的连续段——``foo_bar`` 仍是一个词
          （jieba 会把它切成三段，所以这一路径不能交给 jieba）。

        光标落在分隔符（空白/标点）上时回退到光标左边的字符，
        这样「刚打完一个词」时仍能选到刚写的那个词。
        """
        text = self.toPlainText()
        if not text:
            return None
        return word_range_at(text, position)

    def _selection_seed(self) -> Optional[tuple[str, int, int, bool]]:
        """取当前选区文本与位置；无选区时退化为光标下的单词。

        返回 (needle, start, end, 原本是否已有选区)。
        """
        cur = self.textCursor()
        if cur.hasSelection():
            start = min(cur.position(), cur.anchor())
            end = max(cur.position(), cur.anchor())
            # 用 toPlainText 的切片而不是 cur.selectedText()：后者在跨行选区
            # 里用 U+2029 作换行符，与文档里的 "\n" 不一致，拿它当 needle
            # 在文档里根本找不到匹配。
            return self.toPlainText()[start:end], start, end, True
        under = self._word_range_at(cur.position())
        if under is None:
            return None
        start, end = under
        seed = QTextCursor(self.textCursor())
        seed.setPosition(start)
        seed.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(seed)
        return self.toPlainText()[start:end], start, end, False

    def _occurrence_spans(self, needle: str) -> list[tuple[int, int]]:
        if not needle:
            return []
        text = self.toPlainText()
        spans: list[tuple[int, int]] = []
        idx = text.find(needle)
        while idx != -1:
            spans.append((idx, idx + len(needle)))
            idx = text.find(needle, idx + len(needle))
        return spans

    def _push_selection(self, start: int, end: int) -> None:
        cur = QTextCursor(self.document())
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._extra_cursors.append(cur)
        self._sync_extra_cursors()

    def _selection_chain(self) -> list[tuple[int, int]]:
        """返回当前已选中的各项，顺序为「主选区 → 副光标（添加顺序）」。

        这条链就是 Ctrl+D 已经走过的路径：链尾是「最近一次选中」。
        """
        chain: list[tuple[int, int]] = []
        primary = self.textCursor()
        if primary.hasSelection():
            chain.append(
                (
                    min(primary.position(), primary.anchor()),
                    max(primary.position(), primary.anchor()),
                )
            )
        for cur in self._extra_cursors:
            if cur.hasSelection():
                chain.append(
                    (min(cur.position(), cur.anchor()), max(cur.position(), cur.anchor()))
                )
        return chain

    def select_next_occurrence(self) -> bool:
        """选中下一个相同内容；返回是否发生了选中。

        首次调用且原本没有选区时只选中光标下的单词（与 VS Code 一致），
        再次调用才会追加下一个匹配。

        「下一个」是**向后**找：从当前链尾（最近一次选中的那一项）的
        末尾往后找第一个匹配，而不是从文档开头找第一个还没被选中的。
        否则每次 Ctrl+D 都会把文档里排在最前面的那个匹配选中，用户
        看到的就是「第一次选第 1 项、第二次选第 2 项」这种从头递增
        的行为，而不是「跟着光标往后走」。走到文档末尾才回绕到最前面
        那个还没被选中的匹配。
        """
        seeded = self._selection_seed()
        if seeded is None:
            return False
        needle, _start, _end, had_selection = seeded
        if not had_selection:
            # 刚刚已把光标下的单词选中，等同于 VS Code 的首次 Ctrl+D。
            return True
        spans = self._occurrence_spans(needle)
        if not spans:
            return False
        chain = self._selection_chain()
        taken = set(chain)
        last_end = chain[-1][1] if chain else 0
        # 向后：文档顺序里排在最后一次选中**之后**的第一个尚未选中的匹配
        nxt = next(
            (span for span in spans if span[0] >= last_end and span not in taken),
            None,
        )
        if nxt is None:
            # 文档末尾之后没有未选中的匹配了，回绕到最前面的那个。
            nxt = next((span for span in spans if span not in taken), None)
        if nxt is None:
            return False
        self._push_selection(*nxt)
        return True

    def select_all_occurrences(self) -> bool:
        """选中全文所有与当前选区相同的内容。"""
        seeded = self._selection_seed()
        if seeded is None:
            return False
        needle, _start, _end, _had_selection = seeded
        spans = self._occurrence_spans(needle)
        if len(spans) <= 1:
            return False
        # 主光标保持在**当前选中的那一项**上，其余项作为副光标。
        # 旧实现固定用 spans[0]（文档里最靠前的那个），会让「Ctrl+Shift+L
        # 之后主光标跳到文档开头」，与 Ctrl+D 的链式语义不一致。
        chain = self._selection_chain()
        primary_span = chain[0] if chain else spans[0]
        cur = self.textCursor()
        cur.setPosition(primary_span[0])
        cur.setPosition(primary_span[1], QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        self._extra_cursors.clear()
        for span in spans:
            if span == primary_span:
                continue
            self._push_selection(*span)
        return True

    def undo_last_cursor(self) -> bool:
        """移除最后添加的副光标；返回是否移除成功。"""
        if not self._extra_cursors:
            return False
        self._extra_cursors.pop()
        self._sync_extra_cursors()
        return True

    # --------------------------------------------------------- 垂直光标与列选

    def _line_start(self, position: int) -> int:
        """返回 ``position`` 所在行的起始绝对位置。"""
        block_cur = QTextCursor(self.document())
        block_cur.setPosition(position)
        block_cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        return block_cur.position()

    def _line_end(self, position: int) -> int:
        """返回 ``position`` 所在行的结束绝对位置（不含换行符）。"""
        block_cur = QTextCursor(self.document())
        block_cur.setPosition(position)
        block_cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        return block_cur.position()

    def _line_index_and_column(self, position: int) -> tuple[int, int]:
        block_cur = QTextCursor(self.document())
        block_cur.setPosition(position)
        line = block_cur.blockNumber()
        column = position - self._line_start(position)
        return line, column

    def _position_at_line_column(self, line: int, column: int) -> Optional[int]:
        """把 (行号, 列) 转成绝对位置；行尾之外时裁剪到行尾。"""
        block = self.document().findBlockByNumber(line)
        if not block.isValid():
            return None
        start = block.position()
        end = start + max(0, block.length() - 1)
        return min(start + column, end)

    # ------------------------------------------------ 视觉行（像素）模型
    #
    # 矩形列选是**像素**概念：用户在屏幕上框出一个矩形，落在矩形里的
    # 文字才算选中。而文本位置是**字符**概念，两者不是一一对应：
    #
    # 1. 软换行把一个块拆成多个视觉行。一行很长的日志在屏幕上折成两三
    #    行，但文本上它们属于**同一个块**，「列号」是块内偏移而不是
    #    视觉列号。用块内偏移去算列选，���行部分就会被整段吞掉或整段选上。
    # 2. 行尾不是列边界。短行的正文到行尾就结束了，但用户拖到的那个
    #    像素 x 可能落在行尾**之外**；旧实现把「列号」直接当字符下标去
    #    夹取，短行因此少选——这就是「部分行行尾部分内容选不中」。
    #
    # 所以列选改成以**视觉行**为单位：先定位鼠标落在哪个视觉行，再在
    # 该视觉行内按像素 x 反查字符边界。每个视觉行用自己的字体度量算，
    # 于是折行后的续行也能按自己的列参与选区。

    def _block_visual_rows(self, block_number: int) -> list[dict]:
        """返回一个块的各视觉行描述。

        每项含：``block`` 块号、``index`` 块内视觉行下标、``text_start``
        块内起始下标、``text_length`` 长度、``top``/``height`` 视口 y 几何、
        ``origin_x`` 视口 x 原点、``line`` 对应的 ``QTextLine``。

        几何来自 ``QTextBlock.layout()`` 而不是逐块 ``cursorRect()``：前者是
        O(1) 的布局查询，后者每次都要跑一遍命中测试，拖动时每帧调用会
        卡顿。布局坐标是**文档坐标**，要减掉滚动量才是视口坐标。
        """
        doc = self.document()
        block = doc.findBlockByNumber(block_number)
        if not block.isValid():
            return []
        layout = block.layout()
        if layout is None or layout.lineCount() == 0:
            return []
        origin = layout.position()
        offset_y = self.verticalScrollBar().value()
        base_top = origin.y() - offset_y
        base_x = origin.x()
        rows: list[dict] = []
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            rect = line.rect()
            rows.append(
                {
                    "block": block_number,
                    "index": index,
                    "text_start": line.textStart(),
                    "text_length": line.textLength(),
                    "top": base_top + rect.top(),
                    "height": rect.height(),
                    "origin_x": base_x + rect.left(),
                    "line": line,
                }
            )
        return rows

    def _visual_row_at(self, y: int) -> Optional[dict]:
        """返回 y 像素所在的视觉行描述。

        落点通常在正文上，但也会落在行间空隙（或正文上下的 margin）。
        这时取**最近的**视觉行：空隙上方取上一行、空隙下方取下一行，
        这样拖拽起点即便落在行间也不会让列选失效。

        先用 ``cursorForPosition`` 定位到块（O(log n)），再在该块与前一块
        内找行；只有连块都定位不到时才全文扫描，避免日志很长时每次鼠标
        移动都遍历整篇文档。
        """
        doc = self.document()
        if doc.blockCount() == 0:
            return None
        inside = self.cursorForPosition(QPoint(0, y))
        block = inside.block()
        if block.isValid():
            number = block.blockNumber()
            for candidate in (number, number - 1):
                if candidate < 0:
                    continue
                rows = self._block_visual_rows(candidate)
                if not rows:
                    continue
                for row in rows:
                    if row["top"] <= y < row["top"] + row["height"]:
                        return row
                if y < rows[0]["top"]:
                    return rows[0]
                return rows[-1]
        for block_number in range(doc.blockCount()):
            for row in self._block_visual_rows(block_number):
                if row["top"] <= y < row["top"] + row["height"]:
                    return row
        return None

    def _visual_rows_between(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> list[dict]:
        """列出两个视觉行之间（含两端）的所有视觉行，自上而下。

        ``start`` / ``end`` 是 ``(块号, 块内视觉行下标)``。视觉行的全序就是
        先按块号、再按块内下标，因此两端之间的行可以按块区间枚举，不必给
        整篇文档建索引。
        """
        if start > end:
            start, end = end, start
        first_block, first_index = start
        last_block, last_index = end
        rows: list[dict] = []
        for block_number in range(first_block, last_block + 1):
            for row in self._block_visual_rows(block_number):
                key = (row["block"], row["index"])
                if key < start or key > end:
                    continue
                rows.append(row)
        return rows

    def _row_span_for_pixels(
        self,
        row: dict,
        x_left: int,
        x_right: int,
    ) -> Optional[tuple[int, int]]:
        """求一个视觉行内落在像素区间 ``[x_left, x_right]`` 的字符区间。

        返回**块内**的 ``(起始下标, 结束下标)``；该行与区间无交集时
        返回 None（该行不参与选区）。

        映射规则（与 ``QTextLine`` 的度量自洽）：

        - 起点 = 落在 ``x_left`` 左侧最近的那个字符边界；
        - 终点 = 落在 ``x_right`` 右侧最近的那个字符边界，即**被矩形碰到的
          字符都算选中**；
        - ``x_right`` 越过该行正文右边界时，终点直接取行末——这正是旧实现
          丢字的地方（``xToCursor`` 在正文右边界返回的是**最后一个字符**
          而不是行末，于是少选一个字）。
        """
        line = row["line"]
        text_start = row["text_start"]
        text_length = row["text_length"]
        if text_length <= 0:
            return None
        text_end = text_start + text_length
        origin_x = row["origin_x"]
        rel_left = x_left - origin_x
        rel_right = x_right - origin_x
        # 正文右边界：行末字符边界的 x 坐标
        end_x = line.cursorToX(text_end)[0]
        if rel_right <= 0 or rel_left >= end_x:
            # 矩形与该行正文完全不相交
            return None
        if rel_left <= 0:
            start_index = text_start
        else:
            # xToCursor 返回**块内**下标，且是「就近取整」；要拿到矩形左边
            # 覆盖到的那个字符（把字符整个包含进来），得再向左退一格。
            start_index = line.xToCursor(rel_left)
            if start_index <= text_start:
                start_index = text_start
            elif line.cursorToX(start_index)[0] > rel_left:
                start_index -= 1
            start_index = max(text_start, min(start_index, text_end))
        if rel_right >= end_x:
            end_index = text_end
        else:
            end_index = line.xToCursor(rel_right)
            if end_index >= text_end:
                end_index = text_end
            elif line.cursorToX(end_index)[0] < rel_right:
                # 右边界落在某个字符内部：把它整个选上
                end_index += 1
            end_index = max(text_start, min(end_index, text_end))
        if end_index <= start_index:
            return None
        return (start_index, end_index)

    def _apply_rect_selection(
        self,
        rows: list[dict],
        x_left: int,
        x_right: int,
    ) -> bool:
        """在给定的视觉行与像素 x 区间围成的矩形内选中所有行。

        返回是否真的产生了选区。命中后记录 ``_rect_spans`` / ``_rect_rows``，
        供复制与「右击不丢选区」使用。
        """
        spans: list[tuple[int, int]] = []
        rect_rows: list[dict] = []
        for row in rows:
            span = self._row_span_for_pixels(row, x_left, x_right)
            if span is None:
                continue
            block = self.document().findBlockByNumber(row["block"])
            base = block.position()
            spans.append((base + span[0], base + span[1]))
            rect_rows.append(
                {
                    "row": row,
                    "start": base + span[0],
                    "end": base + span[1],
                    "x_left": x_left,
                    "x_right": x_right,
                }
            )
        if not spans:
            self._rect_active = False
            self._rect_spans = []
            self._rect_rows = []
            self._rect_bounds = None
            return False
        self._rect_spans = spans
        self._rect_rows = rect_rows
        self._rect_active = True
        tops = [entry["row"]["top"] for entry in rect_rows]
        bottoms = [entry["row"]["top"] + entry["row"]["height"] for entry in rect_rows]
        self._rect_bounds = (x_left, int(min(tops)), x_right, int(max(bottoms)))
        first_start, first_end = spans[0]
        cur = self.textCursor()
        cur.setPosition(first_start)
        cur.setPosition(first_end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        self._extra_cursors.clear()
        for start, end in spans[1:]:
            self._push_selection(start, end)
        return True

    def _rect_text(self) -> str:
        """把矩形选区按行拼成文本（每行一段，行间用换行）。"""
        text = self.toPlainText()
        return "\n".join(text[start:end] for start, end in self._rect_spans)

    def _copy_rect_selection(self) -> None:
        """把整个矩形选区（而不是只有主光标那一行）复制到剪贴板。"""
        if not self._rect_active or not self._rect_spans:
            return
        QApplication.clipboard().setText(self._rect_text())

    def _delete_rect_spans(self) -> None:
        """删除矩形选区覆盖的所有行，并收敛回单个光标。

        矩形选区在文档里是**多段互不相连**的选区（每行一段），Qt 自带的
        剪切/删除只作用于主光标那一段，所以必须自己逐段删。

        逐段删除按**位置从后往前**做：删掉后面的段不会影响前面段的
        绝对位置，最后把主光标落到第一段的起点。
        """
        if not self._rect_active or not self._rect_spans:
            return
        spans = sorted(self._rect_spans)
        first_start = spans[0][0]
        editor = self.textCursor()
        record = self._edit_begin()
        editor.beginEditBlock()
        try:
            for start, end in reversed(spans):
                work = QTextCursor(self.document())
                work.setPosition(start)
                work.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                work.removeSelectedText()
        finally:
            editor.endEditBlock()
        self._rect_active = False
        self._rect_spans = []
        self._rect_rows = []
        self._rect_bounds = None
        self._extra_cursors.clear()
        self._sync_extra_cursors()
        cur = QTextCursor(self.document())
        cur.setPosition(first_start)
        self.setTextCursor(cur)
        self._edit_end(record)

    def _cut_rect_selection(self) -> None:
        """剪切矩形选区：复制整块文本，然后把所有行删掉。"""
        if not self._rect_active or not self._rect_spans:
            return
        QApplication.clipboard().setText(self._rect_text())
        self._delete_rect_spans()

    def _point_inside_rect(self, x: int, y: int) -> bool:
        """判断某个像素点是否落在当前矩形选区内。

        判定用的是**矩形整体**的包围盒，而不是逐行判定：矩形覆盖的纵向
        区间里可能夹着「该 x 位置没有文字」的行（例如短行右侧），用户
        在那里右击仍然是「对着这个矩形操作」，不该把选区清掉。
        """
        bounds = self._rect_bounds
        if bounds is None:
            return False
        x_left, y_top, x_right, y_bottom = bounds
        return x_left <= x <= x_right and y_top <= y < y_bottom

    def _position_inside_rect(self, position: int) -> bool:
        """判断某个文本位置是否落在当前矩形选区内。"""
        for start, end in self._rect_spans:
            if start <= position <= end:
                return True
        return False

    def add_cursor_vertical(self, direction: int) -> bool:
        """在上下相邻**视觉行**同列加光标；``direction`` 为 +1 向下、-1 向上。

        连续按同一方向时，从当前最外侧的光标继续延伸（与 VS Code 一致），
        而不是反复围绕主光标打转。

        为什么按**视觉行**而不是按块：

        一个超长的块（没有换行符）在屏幕上会折成多个视觉行，但文本上
        它们属于同一个块。按块定位时，「下一行」会直接跳到下一个块，
        把本块剩下的那些折行视觉行整个跳过——用户看到的就是光标一下子
        跳到很远的地方。软换行的视觉行模型见 ``_block_visual_rows``。
        """
        candidates = [self.textCursor(), *self._extra_cursors]
        if direction > 0:
            base = max(candidates, key=lambda c: c.position())
        else:
            base = min(candidates, key=lambda c: c.position())
        base_position = base.position()

        current = self._visual_row_for_position(base_position)
        if current is None:
            return False
        block_number, row_index = current

        # 列号是**视觉行内**的字符偏移。视觉行首才算是「第一列」——
        # 若按块内偏移算，折行后的第二行会被当成「很长的一行」的后半截，
        # 加出来的光标直接落在行尾。
        column = base_position - self._absolute_row_start(block_number, row_index)

        target = self._neighbor_visual_row(block_number, row_index, direction)
        if target is None:
            return False
        position = self._position_in_visual_row(target[0], target[1], column)
        if position is None:
            return False
        before = self.extra_cursor_count()
        self.add_cursor_at(position)
        return self.extra_cursor_count() > before

    def _visual_row_for_position(self, position: int) -> Optional[tuple[int, int]]:
        """返回 ``position`` 所在的视觉行 (块号, 块内视觉行下标)。

        位置落在块末（换行符之前）时归到该块的最后一行。
        """
        doc = self.document()
        block = doc.findBlock(position)
        if not block.isValid():
            return None
        number = block.blockNumber()
        rows = self._block_visual_rows(number)
        if not rows:
            return None
        offset = position - block.position()
        for row in rows:
            if row["text_start"] <= offset < row["text_start"] + row["text_length"]:
                return (number, row["index"])
        return (number, rows[-1]["index"])

    def _absolute_row_start(self, block_number: int, row_index: int) -> int:
        """返回该视觉行第一个字符的**绝对**文档位置。"""
        doc = self.document()
        block = doc.findBlockByNumber(block_number)
        if not block.isValid():
            return 0
        for row in self._block_visual_rows(block_number):
            if row["index"] == row_index:
                return block.position() + row["text_start"]
        return block.position()

    def _neighbor_visual_row(
        self,
        block_number: int,
        row_index: int,
        direction: int,
    ) -> Optional[tuple[int, int]]:
        """返回指定视觉行在 ``direction`` 方向的相邻视觉行。

        跨块时跳到相邻块的第一行（向下）或最后一行（向上）；空块跳过。
        """
        doc = self.document()
        rows = self._block_visual_rows(block_number)
        if direction > 0:
            if row_index + 1 < len(rows):
                return (block_number, row_index + 1)
            candidate = block_number + 1
            while candidate < doc.blockCount():
                candidate_rows = self._block_visual_rows(candidate)
                if candidate_rows:
                    return (candidate, 0)
                candidate += 1
            return None
        if row_index > 0:
            return (block_number, row_index - 1)
        candidate = block_number - 1
        while candidate >= 0:
            candidate_rows = self._block_visual_rows(candidate)
            if candidate_rows:
                return (candidate, len(candidate_rows) - 1)
            candidate -= 1
        return None

    def _position_in_visual_row(
        self,
        block_number: int,
        row_index: int,
        column: int,
    ) -> Optional[int]:
        """返回视觉行内第 ``column`` 个字符的绝对位置；越界夹到行尾。"""
        doc = self.document()
        block = doc.findBlockByNumber(block_number)
        if not block.isValid():
            return None
        for row in self._block_visual_rows(block_number):
            if row["index"] != row_index:
                continue
            offset = min(max(column, 0), max(row["text_length"], 0))
            return block.position() + row["text_start"] + offset
        return None

    def select_column(
        self,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
    ) -> None:
        """按矩形区域在每行建立等宽选区，第一行作为主光标。"""
        top, bottom = min(start_line, end_line), max(start_line, end_line)
        left, right = min(start_col, end_col), max(start_col, end_col)
        spans: list[tuple[int, int]] = []
        for line in range(top, bottom + 1):
            a = self._position_at_line_column(line, left)
            b = self._position_at_line_column(line, right)
            if a is None or b is None:
                continue
            if b < a:
                a, b = b, a
            spans.append((a, b))
        if not spans:
            return
        first_start, first_end = spans[0]
        cur = self.textCursor()
        cur.setPosition(first_start)
        cur.setPosition(first_end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        self._extra_cursors.clear()
        for a, b in spans[1:]:
            self._push_selection(a, b)

    # ------------------------------------------------------------- 行操作

    def _line_groups(self) -> list[tuple[int, int]]:
        """把主光标与副光标覆盖的行归并成互不相邻的连续区间，升序返回。

        语义对齐 VS Code：单个光标的跨行选区算作**一整块**；相邻的光标行
        合并成一块（否则两块的行操作区域会互相覆盖）；中间没有光标的行
        不属于任何块，行操作**不得**波及它们。

        旧实现把所有光标行压成 ``[min, max]`` 一个区间，于是光标在
        line1 与 line4 时 line2、line3 也被当成选区一起重排——这就是
        「Alt+↑ 上移当前行导致光标位置错乱」的根因。
        """
        doc = self.document()
        spans: list[tuple[int, int]] = []
        for cur in self._all_cursors():
            lo, hi = sorted((cur.position(), cur.anchor()))
            spans.append(
                (doc.findBlock(lo).blockNumber(), doc.findBlock(hi).blockNumber())
            )
        spans.sort()
        merged: list[tuple[int, int]] = []
        for first, last in spans:
            if merged and first <= merged[-1][1] + 1:
                prev_first, prev_last = merged[-1]
                merged[-1] = (prev_first, max(prev_last, last))
            else:
                merged.append((first, last))
        return merged

    def _all_cursors(self) -> list[QTextCursor]:
        return [self.textCursor()] + list(self._extra_cursors)

    def _cursor_specs(self) -> list[dict]:
        """记录每个光标（主 + 副）所在的行、列与锚点行列。"""
        doc = self.document()
        specs: list[dict] = []
        for cur in self._all_cursors():
            pos_block = doc.findBlock(cur.position())
            anchor_block = doc.findBlock(cur.anchor())
            specs.append(
                {
                    "line": pos_block.blockNumber(),
                    "column": cur.position() - pos_block.position(),
                    "anchor_line": anchor_block.blockNumber(),
                    "anchor_column": cur.anchor() - anchor_block.position(),
                }
            )
        return specs

    @staticmethod
    def _position_in_line(doc, line: int, column: int) -> int:  # noqa: ANN001
        """把 (行号, 列号) 换算成字符位置，越界时夹到目标行行尾。

        目标行已不存在（行操作把末尾的行删掉后光标被要求落在其后）时
        夹到**最后一行**的同一列，而不是夹到整个文档末尾字符——后者会
        落成「最后一行行尾」，列位置就丢了。
        """
        block = doc.findBlockByNumber(max(0, line))
        if not block.isValid():
            block = doc.lastBlock()
        return min(
            block.position() + max(0, column),
            block.position() + max(0, block.length() - 1),
        )

    def _place_cursors(self, specs: list[dict], mapper) -> None:  # noqa: ANN001
        """按 ``mapper(行号) -> (新行号, 列偏移)`` 重新安放全部光标。

        行操作会改变行号（删除/插入/交换），列也可能因加注释前缀而右移，
        所以每做完一次行操作都必须把**每一个**光标搬到它应去的新位置；
        旧实现只处理主光标，副光标就停留在旧字符偏移上漂走。
        """
        doc = self.document()
        cursors: list[QTextCursor] = []
        seen: set[tuple[int, int]] = set()
        for spec in specs:
            line, delta = mapper(spec["line"])
            anchor_line, anchor_delta = mapper(spec["anchor_line"])
            target = self._position_in_line(doc, line, spec["column"] + delta)
            anchor = self._position_in_line(
                doc, anchor_line, spec["anchor_column"] + anchor_delta
            )
            key = (anchor, target)
            if key in seen:
                continue
            seen.add(key)
            cur = QTextCursor(doc)
            cur.setPosition(anchor)
            cur.setPosition(target, QTextCursor.MoveMode.KeepAnchor)
            cursors.append(cur)
        if not cursors:
            return
        primary, extras = cursors[0], cursors[1:]
        self.setTextCursor(primary)
        self._extra_cursors = extras
        self._sync_extra_cursors()

    @staticmethod
    def _groups_size_above(groups: list[tuple[int, int]], line: int) -> int:
        """返回完全位于 ``line`` 之上（更靠前）的块所占行数之和。"""
        return sum(last - first + 1 for first, last in groups if last < line)

    @staticmethod
    def _replace_lines(doc, cur, low: int, high: int, texts: list[str]) -> bool:  # noqa: ANN001
        """用 ``texts`` 替换 [low, high] 这些行（保留块外的换行结构）。"""
        low_block = doc.findBlockByNumber(low)
        high_block = doc.findBlockByNumber(high)
        if not low_block.isValid() or not high_block.isValid():
            return False
        start = low_block.position()
        end = high_block.position() + max(0, high_block.length() - 1)
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        cur.setPosition(start)
        cur.insertText("\n".join(texts))
        return True

    def _block_text(self, block) -> str:  # noqa: ANN001 - QTextBlock
        return block.text()

    def delete_line(self) -> bool:
        """删除每个光标块涉及的整行（含换行符）；光标保持**列位置**。

        VS Code 语义：删掉整行后，光标落在接替它的那一行同一列，
        而不是跳到行首；多光标时每个光标落回**自己**那块被删后接替的行，
        中间没有光标的行不受影响。
        """
        groups = self._line_groups()
        doc = self.document()
        if not groups:
            return False
        specs = self._cursor_specs()
        cur = self.textCursor()
        applied = False
        record = self._edit_begin()
        cur.beginEditBlock()
        try:
            for first, last in reversed(groups):
                first_block = doc.findBlockByNumber(first)
                last_block = doc.findBlockByNumber(last)
                if not first_block.isValid() or not last_block.isValid():
                    continue
                start = first_block.position()
                if last_block.next().isValid():
                    end = last_block.next().position()
                else:
                    # 末尾没有换行符：连同前一个换行一起删，避免留下空行
                    end = last_block.position() + max(0, last_block.length() - 1)
                    if first > 0:
                        prev = doc.findBlockByNumber(first - 1)
                        start = prev.position() + max(0, prev.length() - 1)
                cur.setPosition(start)
                cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                applied = True
        finally:
            cur.endEditBlock()
        if not applied:
            return False

        def mapper(line: int) -> tuple[int, int]:
            removed = 0
            for first, last in groups:
                if last < line:
                    removed += last - first + 1
                elif first <= line <= last:
                    # 该行随所在块一起被删：落回这一块的替身行（块首）
                    return (first - removed, 0)
            return (line - removed, 0)

        self._place_cursors(specs, mapper)
        self._edit_end(record)
        return True

    def duplicate_line(self, direction: int = 1) -> bool:
        """向上/向下复制每个光标块涉及的行；光标落在**副本**的同一列。"""
        groups = self._line_groups()
        doc = self.document()
        if not groups:
            return False
        specs = self._cursor_specs()
        cur = self.textCursor()
        applied = False
        record = self._edit_begin()
        cur.beginEditBlock()
        try:
            for first, last in reversed(groups):
                first_block = doc.findBlockByNumber(first)
                last_block = doc.findBlockByNumber(last)
                if not first_block.isValid() or not last_block.isValid():
                    continue
                lines = [
                    doc.findBlockByNumber(i).text() for i in range(first, last + 1)
                ]
                if direction > 0:
                    insert_pos = last_block.position() + max(
                        0, last_block.length() - 1
                    )
                    payload = "\n" + "\n".join(lines)
                else:
                    insert_pos = first_block.position()
                    payload = "\n".join(lines) + "\n"
                cur.setPosition(insert_pos)
                cur.insertText(payload)
                applied = True
        finally:
            cur.endEditBlock()
        if not applied:
            return False

        def mapper(line: int) -> tuple[int, int]:
            for first, last in groups:
                if not first <= line <= last:
                    continue
                offset = line - first
                above = self._groups_size_above(groups, first)
                if direction > 0:
                    # 副本紧跟在块后：光标进入副本
                    return (first + above + (last - first + 1) + offset, 0)
                # 副本插在块前：光标进入副本，行号只被上方块撑高
                return (first + above + offset, 0)
            return (line, 0)

        self._place_cursors(specs, mapper)
        self._edit_end(record)
        return True

    def move_line(self, direction: int) -> bool:
        """把每个光标块整体上移或下移一行；贴边的块被跳过，其余照常移动。"""
        if direction == 0:
            return False
        groups = self._line_groups()
        doc = self.document()
        if not groups:
            return False
        block_count = doc.blockCount()
        movable: list[tuple[int, int]] = []
        for first, last in groups:
            if direction > 0 and last + 1 >= block_count:
                continue
            if direction < 0 and first == 0:
                continue
            movable.append((first, last))
        if not movable:
            return False
        specs = self._cursor_specs()
        cur = self.textCursor()
        record = self._edit_begin()
        cur.beginEditBlock()
        try:
            for first, last in reversed(movable):
                if direction > 0:
                    low, high = first, last + 1
                else:
                    low, high = first - 1, last
                texts = [doc.findBlockByNumber(i).text() for i in range(low, high + 1)]
                if direction > 0:
                    moved = texts[: last - first + 1]
                    texts = [texts[-1]] + moved
                else:
                    texts = texts[1:] + [texts[0]]
                self._replace_lines(doc, cur, low, high, texts)
        finally:
            cur.endEditBlock()

        def mapper(line: int) -> tuple[int, int]:
            for first, last in movable:
                if first <= line <= last:
                    return (line + direction, 0)
            return (line, 0)

        self._place_cursors(specs, mapper)
        self._edit_end(record)
        return True

    def toggle_line_comment(self, prefix: str = "#") -> bool:
        """给每个光标块涉及的行加/去注释前缀；返回操作后是否处于注释状态。

        加/去的判定是**全局**的：混合状态下按一次得到「全部加注释」，
        与 VS Code 一致，也不会把已经有前缀的行叠加成 ``##``。
        """
        if not prefix:
            return False
        groups = self._line_groups()
        doc = self.document()
        if not groups:
            return False
        all_lines: list[int] = []
        for first, last in groups:
            all_lines.extend(range(first, last + 1))
        blocks = [doc.findBlockByNumber(i) for i in all_lines]
        if not all(block.isValid() for block in blocks):
            return False
        all_commented = all(
            block.text().lstrip().startswith(prefix) for block in blocks
        )
        deltas: dict[int, int] = {}
        specs = self._cursor_specs()
        cur = self.textCursor()
        record = self._edit_begin()
        cur.beginEditBlock()
        try:
            for first, last in reversed(groups):
                new_texts: list[str] = []
                for line in range(first, last + 1):
                    text = doc.findBlockByNumber(line).text()
                    pad = len(text) - len(text.lstrip())
                    if all_commented:
                        new_texts.append(text[:pad] + text[pad + len(prefix) :])
                        deltas[line] = -len(prefix)
                    elif text.lstrip().startswith(prefix):
                        # 混合状态：已注释的行保持原样，避免叠加前缀
                        new_texts.append(text)
                        deltas[line] = 0
                    else:
                        new_texts.append(text[:pad] + prefix + text[pad:])
                        deltas[line] = len(prefix)
                self._replace_lines(doc, cur, first, last, new_texts)
        finally:
            cur.endEditBlock()

        def mapper(line: int) -> tuple[int, int]:
            return (line, deltas.get(line, 0))

        self._place_cursors(specs, mapper)
        self._edit_end(record)
        return not all_commented

    def _position_at(self, point: QPoint) -> int:
        """视口坐标 -> 文本位置，修正 Qt 在软换行视觉行右边缘的塌陷。

        Qt（``QTextEdit.cursorForPosition``）在 x 越过某个**软换行**视觉行的
        正文右边界之后，返回的是该视觉行**最后一个字符**的位置，而不是行末
        位置。于是鼠标拖到最右边反而**少选一个字符**——用户看到的现象就是
        「这行最后一个字选不中」。这里在检测到越界时把位置钳到行末。
        """
        inside = self.cursorForPosition(point)
        block = inside.block()
        layout = block.layout()
        if layout is None or layout.lineCount() == 0:
            return inside.position()

        probe = QTextCursor(self.document())
        probe.setPosition(block.position())
        block_rect = self.cursorRect(probe)
        block_top = block_rect.top()
        block_left = block_rect.left()

        y = point.y()
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            rect = line.rect()
            top = block_top + rect.top()
            if not (top <= y < top + rect.height()):
                continue
            right_edge = block_left + rect.left() + line.naturalTextWidth()
            if point.x() >= right_edge:
                return block.position() + line.textStart() + line.textLength()
            return inside.position()
        return inside.position()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        button = event.button()
        alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if button == Qt.MouseButton.RightButton:
            # 右击 = 弹上下文菜单 = 回到常规操作。此时若还留着一排副光标，
            # 用户接下来的输入会同时写进多个位置，是很危险的意外。
            # 先收敛再交给 Qt 弹菜单，不影响主光标位置。
            #
            # 例外：**点在自己的矩形列选区内**时不清——用户此时的意图是
            # 「对这个矩形选区操作」（复制、查找…），把选区清掉会让菜单里的
            # 复制只拿到第一行。落在选区外才收敛回单光标。
            point = event.position().toPoint()
            if self._rect_active and self._point_inside_rect(point.x(), point.y()):
                super().mousePressEvent(event)
                return
            self.clear_extra_cursors()
            super().mousePressEvent(event)
            return
        if button == Qt.MouseButton.LeftButton and alt:
            # Alt+左键是「往集合里再加一个光标」，不能清空
            point = event.position().toPoint()
            self._column_anchor = self._position_at(point)
            self._column_anchor_point = (point.x(), point.y())
            self._column_dragging = True
            self._column_moved = False
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton:
            # 普通左键是「在这里放一个光标」的语义（与 VS Code 一致）：
            # 点完只应剩下这一根，否则接下来输入会同时写进多个位置。
            # 先清再走 Qt 默认处理，让主光标落到点击处。
            self.clear_extra_cursors()
        super().mousePressEvent(event)
        if button == Qt.MouseButton.LeftButton:
            # 记录拖选锚点，供 mouseMoveEvent 修正右边缘塌陷时使用。
            self._plain_anchor = self.textCursor().position()
            self._plain_dragging = True

    def _rect_drag_selection(self, end_point: tuple[int, int]) -> bool:
        """按「锚点像素 + 当前像素」计算矩形列选并应用。

        返回是否产生了选区。矩形是**像素**概念：纵向取锚点与当前点之间
        的所有视觉行（含两端），横向取两点的 x 区间；每个视觉行用**自己
        的**字体度量反查字符边界，所以软换行的续行、短行的行尾都能正确
        命中——这正是旧实现（用块内字符偏移当列号）丢字的原因。
        """
        anchor_point = self._column_anchor_point
        if anchor_point is None:
            return False
        ax, ay = anchor_point
        bx, by = end_point
        anchor_row = self._visual_row_at(ay)
        end_row = self._visual_row_at(by)
        if anchor_row is None or end_row is None:
            return False
        rows = self._visual_rows_between(
            (anchor_row["block"], anchor_row["index"]),
            (end_row["block"], end_row["index"]),
        )
        if not rows:
            return False
        x_left = min(ax, bx)
        x_right = max(ax, bx)
        return self._apply_rect_selection(rows, x_left, x_right)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._column_dragging and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            point = event.position().toPoint()
            if self._rect_drag_selection((point.x(), point.y())):
                self._column_moved = True
                event.accept()
                return
        super().mouseMoveEvent(event)
        if self._plain_dragging and self._plain_anchor is not None:
            point = event.position().toPoint()
            # Qt 自己的拖选不经过可覆写的 cursorForPosition，右边缘塌陷必须
            # 在这里补：仅当修正值与 Qt 的结果不同才接管，避免过度干预。
            corrected = self._position_at(point)
            native = self.cursorForPosition(point).position()
            if corrected != native:
                cur = QTextCursor(self.document())
                cur.setPosition(self._plain_anchor)
                cur.setPosition(corrected, QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cur)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """双击选词：中文按词典分词，不按整段汉字。

        Qt 自带的双击把**一整段连续汉字**当作一个词——在
        「语音输入测试字符串」上会一次选中 9 个字。选词粒度应与 Ctrl+D
        一致，所以这里让 Qt 先按它自己的规则选，再把选区**收窄**到
        真正的那个词。

        收窄而不是重算：Qt 已经算好了双击命中的词边界，我们只需要知道
        那个词在文档里的范围，再取其中分词后的那一个。

        锚点是**鼠标点到的那个字符**，不是选区起点：Qt 对整段汉字只给出
        一个跨越全段的选区，起点永远是 0；用起点当锚点的话，双击段落的
        最后一个词也会选中开头的第一个词。

        ASCII 词不受影响——分词结果与 Qt 的词边界一致，无需收窄。
        """
        super().mouseDoubleClickEvent(event)
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        start = min(cursor.position(), cursor.anchor())
        end = max(cursor.position(), cursor.anchor())
        text = self.toPlainText()
        if not text:
            return

        # 锚点 = 鼠标点到的位置。取不到就退回选区起点。
        anchor = self._position_at(event.position().toPoint())
        if anchor < start or anchor > end:
            anchor = start
        anchor = min(max(anchor, 0), max(len(text) - 1, 0))

        narrowed = word_range_at(text, anchor)
        if narrowed is None or narrowed == (start, end):
            return
        new_start, new_end = narrowed
        # 收窄后必须仍在原选区之内，否则说明分词结果与 Qt 的词边界
        # 不一致——此时保持 Qt 的选择，不擅自改变用户的选区。
        if new_start < start or new_end > end:
            return
        cursor.setPosition(new_start)
        cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._column_dragging:
            self._column_dragging = False
            anchor = self._column_anchor
            self._column_anchor = None
            self._column_anchor_point = None
            moved = self._column_moved
            self._column_moved = False
            if anchor is not None:
                if moved:
                    point = event.position().toPoint()
                    self._rect_drag_selection((point.x(), point.y()))
                else:
                    # 没有拖动：按 Alt+点击语义加/减一个副光标
                    self.toggle_cursor_at(anchor)
                event.accept()
                return
        self._plain_dragging = False
        self._plain_anchor = None
        super().mouseReleaseEvent(event)

    def _column_span(self, anchor: int, other: int) -> tuple[int, int, int, int]:
        """把两个绝对位置换算成 select_column 需要的四元组。"""
        a_line, a_col = self._line_index_and_column(anchor)
        b_line, b_col = self._line_index_and_column(other)
        return a_line, a_col, b_line, b_col

    # ------------------------------------------------------------- 按键分发

    def _navigation_operation(
        self, event: QKeyEvent
    ) -> Optional[tuple[QTextCursor.MoveOperation, QTextCursor.MoveMode]]:
        """把方向类按键翻译成 Qt 的移动操作；非方向键返回 None。

        Shift 修饰时用 KeepAnchor（扩展选区），否则 MoveAnchor（收起选区）。
        Ctrl+Home/End 走文档首尾，Home/End 走行首尾，与 Qt 默认一致。
        翻页键（PageUp/PageDown）不在此列：它们的位移量取决于视口高度，
        交给 Qt 默认处理更合适。

        **Ctrl+←/→ 不在这里**：按词跳要按 jieba 的词粒度算边界，而 Qt 的
        ``PreviousWord``/``NextWord`` 对中文太粗（整段连续汉字算一个词）。
        它由 :meth:`move_all_cursors_by_word` 单独处理。
        """
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        mode = (
            QTextCursor.MoveMode.KeepAnchor
            if mods & Qt.KeyboardModifier.ShiftModifier
            else QTextCursor.MoveMode.MoveAnchor
        )
        key = event.key()
        Op = QTextCursor.MoveOperation
        if key == Qt.Key.Key_Up:
            return Op.Up, mode
        if key == Qt.Key.Key_Down:
            return Op.Down, mode
        if key == Qt.Key.Key_Left:
            return Op.Left, mode
        if key == Qt.Key.Key_Right:
            return Op.Right, mode
        if key == Qt.Key.Key_Home:
            return (Op.Start if ctrl else Op.StartOfLine), mode
        if key == Qt.Key.Key_End:
            return (Op.End if ctrl else Op.EndOfLine), mode
        return None

    def move_all_cursors_to_line_edge(
        self,
        to_start: bool,
        mode: Optional[QTextCursor.MoveMode] = None,
    ) -> None:
        """把所有光标移到所在**视觉行**的行首 / 行尾。

        「行」按视觉行算：长行在屏幕上折成几行，「行首」就是当前屏幕上
        那一行的开头。Qt 的 ``StartOfLine``/``EndOfLine`` 本身就是视觉行
        语义，直接可用。

        ``mode`` 传 ``KeepAnchor`` 时扩展选区而不是移动光标。
        """
        operation = (
            QTextCursor.MoveOperation.StartOfLine
            if to_start
            else QTextCursor.MoveOperation.EndOfLine
        )
        self.move_all_cursors(operation, mode)

    def move_all_cursors_by_word(self, to_start: bool, mode=None) -> None:  # noqa: ANN001
        """把所有光标按**词**移动：``to_start`` 为真跳到上一个词开头。

        与 Qt 的 ``PreviousWord``/``NextWord`` 不同，中文按 **jieba 词典**
        的词粒度跳——Qt 把整段连续汉字算一个词，在「语音输入测试字符串」
        上一跳就是 9 个字。

        这也让单光标与多光标的行为一致了：原先单光标走 Qt 原生（按词）、
        多光标走 ``_navigation_operation``（按字符），两套语义。
        """
        text = self.toPlainText()
        if not text:
            return
        if mode is None:
            mode = QTextCursor.MoveMode.MoveAnchor

        moved: list[QTextCursor] = []
        for cur in list(self._extra_cursors):
            work = QTextCursor(cur)
            target = word_start_at(text, work.position()) if to_start else word_end_at(
                text, work.position()
            )
            work.setPosition(target, mode)
            moved.append(work)
        if moved:
            self._extra_cursors = moved

        primary = self.textCursor()
        target = word_start_at(text, primary.position()) if to_start else word_end_at(
            text, primary.position()
        )
        primary.setPosition(target, mode)
        self.setTextCursor(primary)

        self._dedupe_extra_cursors()
        self._sync_extra_cursors()

    def move_all_cursors(
        self,
        operation: QTextCursor.MoveOperation,
        mode: Optional[QTextCursor.MoveMode] = None,
    ) -> None:
        """对所有光标（主 + 副）施加同一个移动操作。

        移动不改文本，所以不需要位移补偿；各光标独立移动即可。
        Qt 的 ``movePosition`` 在 Up/Down 时会记住「目标列」，因此行长度不同
        时各光标会被自动夹到行尾，不会错位。

        移动后若有副光标与其他光标重合，只保留一个，避免多根线叠在同一处。
        """
        if mode is None:
            mode = QTextCursor.MoveMode.MoveAnchor
        moved: list[QTextCursor] = []
        for cur in list(self._extra_cursors):
            work = QTextCursor(cur)
            work.movePosition(operation, mode)
            moved.append(work)
        if moved:
            self._extra_cursors = moved
        self.moveCursor(operation, mode)
        self._dedupe_extra_cursors()
        self._sync_extra_cursors()

    def _dedupe_extra_cursors(self) -> None:
        """去掉与主光标或彼此完全重复的副光标。"""
        seen: set[tuple[int, int]] = set()
        primary = self.textCursor()
        seen.add((primary.position(), primary.anchor()))
        kept: list[QTextCursor] = []
        for cur in self._extra_cursors:
            key = (cur.position(), cur.anchor())
            if key in seen:
                continue
            seen.add(key)
            kept.append(cur)
        if len(kept) != len(self._extra_cursors):
            self._extra_cursors = kept

    def _shortcut_action(self, event: QKeyEvent) -> bool:
        """处理 VS Code 风格的快捷键；返回是否已消费该按键。"""
        mods = event.modifiers()
        key = event.key()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        no_alt = not alt

        if ctrl and no_alt and not shift and key == Qt.Key.Key_F:
            self.find_bar.open()
            return True
        if ctrl and no_alt and not shift and key == Qt.Key.Key_H:
            # Ctrl+H 展开替换行。若浮层已经开着，open() 会保留用户已经
            # 输入的查找词/替换词，不会因为再按一次 Ctrl+F 就丢掉。
            self.find_bar.open(replace_mode=True)
            return True
        if ctrl and no_alt and not shift and key == Qt.Key.Key_Slash:
            self.toggle_line_comment("#")
            return True
        if ctrl and no_alt and not shift and key == Qt.Key.Key_D:
            self.select_next_occurrence()
            return True
        if ctrl and shift and no_alt and key == Qt.Key.Key_L:
            self.select_all_occurrences()
            return True
        if ctrl and no_alt and not shift and key == Qt.Key.Key_U:
            self.undo_last_cursor()
            return True
        if ctrl and alt and not shift and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.add_cursor_vertical(-1 if key == Qt.Key.Key_Up else 1)
            return True
        if ctrl and shift and no_alt and key == Qt.Key.Key_K:
            self.delete_line()
            return True
        # Ctrl+←/→：按词跳。中文按 jieba 词典的词粒度（Qt 原生把整段
        # 连续汉字算一个词，太粗），ASCII 按整词。
        if ctrl and no_alt and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            mode = (
                QTextCursor.MoveMode.KeepAnchor
                if shift
                else QTextCursor.MoveMode.MoveAnchor
            )
            self.move_all_cursors_by_word(key == Qt.Key.Key_Left, mode)
            return True
        if alt and shift and not ctrl and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.duplicate_line(-1 if key == Qt.Key.Key_Up else 1)
            return True
        if alt and not ctrl and not shift and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move_line(-1 if key == Qt.Key.Key_Up else 1)
            return True
        # Alt+←/→：跳到所在视觉行的行首 / 行尾。
        #
        # 注意与 Alt+↑/↓ 的区分：↑/↓ 是「移动整行」，←/→ 只是「移动
        # 光标」。两者不能混，否则 Alt+↑ 会变成两件事。
        if alt and not ctrl and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            mode = (
                QTextCursor.MoveMode.KeepAnchor
                if shift
                else QTextCursor.MoveMode.MoveAnchor
            )
            self.move_all_cursors_to_line_edge(key == Qt.Key.Key_Left, mode)
            return True
        return False

    def createStandardContextMenu(self):  # noqa: N802
        """构建标准右键菜单；矩形列选时把 Copy/Cut/Delete 换成整块版本。

        Qt 自带的这些动作只会作用于**主光标**那一行的选区——矩形列选
        有多行，复制/剪切/删除都只拿到第一行。把它们换掉后，右键菜单与
        Ctrl+C / Ctrl+X 的行为一致。
        """
        menu = super().createStandardContextMenu()
        if not self._rect_active or not self._rect_spans:
            return menu
        handlers = {
            "Copy": self._copy_rect_selection,
            "Cut": self._cut_rect_selection,
            "Delete": self._delete_rect_spans,
        }
        actions = menu.actions()
        replacements = []
        for action in actions:
            label = action.text().replace("&", "").split("\t")[0]
            handler = handlers.get(label)
            if handler is None:
                continue
            replacements.append((actions.index(action), action, label, handler))
        for index, action, label, handler in reversed(replacements):
            menu.removeAction(action)
            new_action = menu.addAction(action.text())
            new_action.setShortcut(action.shortcut())
            new_action.setEnabled(True)
            new_action.triggered.connect(handler)
            menu.insertAction(menu.actions()[min(index, len(menu.actions()))], new_action)
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """弹出右键菜单。

        必须自己建菜单再 ``exec``：``QTextEdit.contextMenuEvent`` 内部走的是
        ``QWidgetTextControl`` 自己的菜单构造，**不会**调用本控件的
        ``createStandardContextMenu()``，所以只在后者里替换动作是无效的——
        右键菜单里的剪切/删除依旧只作用于主光标那一行。

        非矩形选区时走 Qt 原生路径，保留拼写建议等原生菜单项。
        """
        if not self._rect_active or not self._rect_spans:
            super().contextMenuEvent(event)
            return
        menu = self.createStandardContextMenu()
        self._exec_context_menu(menu, event)

    def _exec_context_menu(self, menu, event: QContextMenuEvent) -> None:
        """真正弹出菜单；单独成方法便于测试时替换。"""
        menu.exec(event.globalPos())

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._extra_cursors:
            self.clear_extra_cursors()
            event.accept()
            return
        # Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y 必须在这里自己接：Qt 内部的
        # keyPressEvent 直接调 C++ 版 undo()，Python 子类覆写 undo() 不会被
        # 它调到。多光标编辑若走 Qt 默认路径，副光标会停在错位的位置。
        if self._handle_undo_shortcut(event):
            event.accept()
            return
        if self._shortcut_action(event):
            event.accept()
            return
        if (
            self._rect_active
            and event.key() == Qt.Key.Key_C
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            and not event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            # 矩形列选要复制**整块**文本，Qt 默认只会复制主光标那一行。
            self._copy_rect_selection()
            event.accept()
            return
        if (
            self._rect_active
            and event.key() == Qt.Key.Key_X
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            and not event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            # 矩形列选是**多段**选区，Qt 默认剪切只切主光标那一行。
            self._cut_rect_selection()
            event.accept()
            return
        if self._rect_active and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # 同理：Delete/Backspace 也要作用到矩形的每一行。
            self._delete_rect_spans()
            event.accept()
            return
        if self._extra_cursors:
            text = event.text()
            if text and text.isprintable() and not (
                event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier
            ):
                self.insert_text_at_cursors(text)
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
                self.delete_at_cursors(backward=event.key() == Qt.Key.Key_Backspace)
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.insert_text_at_cursors("\n")
                event.accept()
                return
            nav = self._navigation_operation(event)
            if nav is not None:
                operation, mode = nav
                self.move_all_cursors(operation, mode)
                event.accept()
                return
        super().keyPressEvent(event)
