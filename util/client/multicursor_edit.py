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

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

__all__ = ["FindBar", "MultiCursorTextEdit"]


SELECTION_COLOR = QColor(38, 79, 120, 160)


class FindBar(QWidget):
    """编辑器顶部的轻量查找栏（Ctrl+F）。

    只做「查找下一个 / 上一个」，不做替换，因为它服务的是客户端日志框，
    真正的编辑仍在主文本框里完成。
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
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        self.line_edit = QLineEdit(self)
        self.line_edit.setPlaceholderText("查找")
        self.line_edit.returnPressed.connect(self.find_next)
        layout.addWidget(self.line_edit, 1)
        self.prev_button = QPushButton("上一个", self)
        self.prev_button.clicked.connect(self.find_prev)
        layout.addWidget(self.prev_button)
        self.next_button = QPushButton("下一个", self)
        self.next_button.clicked.connect(self.find_next)
        layout.addWidget(self.next_button)
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        self.hide()

    def open(self) -> None:
        """显示查找栏并把焦点交给输入框（保留已选中的文本作为关键词）。

        用 ``setViewportMargins`` 给查找栏留出顶部空间，让正文整体下移，
        而不是把找到的内容盖住。
        """
        selected = self._editor.textCursor().selectedText()
        if selected:
            self.line_edit.setText(selected)
        self.show()
        self.raise_()
        self.reposition()
        self.line_edit.setFocus()
        self.line_edit.selectAll()

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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self._editor.setFocus()
            event.accept()
            return
        super().keyPressEvent(event)


class MultiCursorTextEdit(QTextEdit):
    """带多光标编辑与「跟随末尾」开关的文本框。"""

    extra_cursor_count_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._follow_caret = True
        self._extra_cursors: list[QTextCursor] = []
        self._column_anchor: Optional[int] = None
        self._column_dragging = False
        self._column_moved = False
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
        self.find_bar = FindBar(self)
        self.find_bar.hide()

    # ----------------------------------------------------------- 跟随末尾开关

    @property
    def follow_caret(self) -> bool:
        return self._follow_caret

    def set_follow_caret(self, follow: bool) -> None:
        self._follow_caret = bool(follow)

    # --------------------------------------------------------------- 日志追加

    def append_line(self, line: str) -> None:
        """追加一行日志。

        ``follow_caret`` 为真时行为等同 ``QTextEdit.append``（光标与滚动条
        跟随末尾）；为假时保留用户的光标、选区与滚动位置。
        """
        if self._follow_caret:
            self.moveCursor(QTextCursor.MoveOperation.End)
            self.append(line)
            return
        saved = self._snapshot_state()
        self.append(line)
        self._restore_state(saved)

    def scroll_to_bottom_if_follow(self) -> None:
        """仅在跟随末尾时把光标与滚动条推到最后一行。"""
        if not self._follow_caret:
            return
        self.moveCursor(QTextCursor.MoveOperation.End)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

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

    # ------------------------------------------------------------- 副光标绘制

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """在视口自身上绘制副光标。

        直接与文字共用同一次绘制，避免透明子控件在不同平台/DPI 下
        被合成器丢弃（那正是「只看到选区、看不到竖线」的原因）。
        """
        super().paintEvent(event)
        if not self._extra_cursors:
            return
        painter = QPainter(self.viewport())
        try:
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

    # ---------------------------------------------------------- 选中相同内容

    _WORD_CHARS = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789_"
    )

    def _word_range_at(self, position: int) -> Optional[tuple[int, int]]:
        """返回 ``position`` 所在单词的 [start, end)；不在单词内返回 None。"""
        text = self.toPlainText()
        if not text:
            return None
        pos = max(0, min(position, len(text)))
        if pos < len(text) and text[pos] in self._WORD_CHARS:
            pass
        elif pos > 0 and text[pos - 1] in self._WORD_CHARS:
            pos -= 1
        else:
            return None
        start = pos
        while start > 0 and text[start - 1] in self._WORD_CHARS:
            start -= 1
        end = pos
        while end < len(text) and text[end] in self._WORD_CHARS:
            end += 1
        if start == end:
            return None
        return start, end

    def _selection_seed(self) -> Optional[tuple[str, int, int, bool]]:
        """取当前选区文本与位置；无选区时退化为光标下的单词。

        返回 (needle, start, end, 原本是否已有选区)。
        """
        cur = self.textCursor()
        if cur.hasSelection():
            start = min(cur.position(), cur.anchor())
            end = max(cur.position(), cur.anchor())
            return cur.selectedText(), start, end, True
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

    def _taken_spans(self) -> set[tuple[int, int]]:
        taken = set()
        primary = self.textCursor()
        if primary.hasSelection():
            taken.add((min(primary.position(), primary.anchor()), max(primary.position(), primary.anchor())))
        for cur in self._extra_cursors:
            if cur.hasSelection():
                taken.add((min(cur.position(), cur.anchor()), max(cur.position(), cur.anchor())))
        return taken

    def _push_selection(self, start: int, end: int) -> None:
        cur = QTextCursor(self.document())
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._extra_cursors.append(cur)
        self._sync_extra_cursors()

    def select_next_occurrence(self) -> bool:
        """选中下一个相同内容；返回是否发生了选中。

        首次调用且原本没有选区时只选中光标下的单词（与 VS Code 一致），
        再次调用才会追加下一个匹配。
        """
        seeded = self._selection_seed()
        if seeded is None:
            return False
        needle, _start, _end, had_selection = seeded
        if not had_selection:
            return True
        taken = self._taken_spans()
        for span in self._occurrence_spans(needle):
            if span in taken:
                continue
            self._push_selection(*span)
            return True
        return False

    def select_all_occurrences(self) -> bool:
        """选中全文所有与当前选区相同的内容。"""
        seeded = self._selection_seed()
        if seeded is None:
            return False
        needle, _start, _end, _had_selection = seeded
        spans = self._occurrence_spans(needle)
        if len(spans) <= 1:
            return False
        primary_span = spans[0]
        cur = self.textCursor()
        cur.setPosition(primary_span[0])
        cur.setPosition(primary_span[1], QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        self._extra_cursors.clear()
        for span in spans[1:]:
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

    def add_cursor_vertical(self, direction: int) -> bool:
        """在上下相邻行同列加光标；``direction`` 为 +1 向下、-1 向上。

        连续按同一方向时，从当前最外侧的光标继续延伸（与 VS Code 一致），
        而不是反复围绕主光标打转。
        """
        candidates = [self.textCursor(), *self._extra_cursors]
        line, column = self._line_index_and_column(self.textCursor().position())
        if direction > 0:
            base = max(candidates, key=lambda c: c.position())
        else:
            base = min(candidates, key=lambda c: c.position())
        base_line, base_column = self._line_index_and_column(base.position())
        column = base_column
        target_line = base_line + (1 if direction > 0 else -1)
        pos = self._position_at_line_column(target_line, column)
        if pos is None:
            return False
        before = self.extra_cursor_count()
        self.add_cursor_at(pos)
        return self.extra_cursor_count() > before

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
            self.clear_extra_cursors()
            super().mousePressEvent(event)
            return
        if button == Qt.MouseButton.LeftButton and alt:
            # Alt+左键是「往集合里再加一个光标」，不能清空
            point = event.position().toPoint()
            self._column_anchor = self._position_at(point)
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

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._column_dragging and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            anchor = self._column_anchor
            if anchor is not None:
                end = self._position_at(event.position().toPoint())
                a_line, _ = self._line_index_and_column(anchor)
                b_line, _ = self._line_index_and_column(end)
                if a_line != b_line:
                    self._column_moved = True
                    self.select_column(*self._column_span(anchor, end))
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._column_dragging:
            self._column_dragging = False
            anchor = self._column_anchor
            self._column_anchor = None
            moved = self._column_moved
            self._column_moved = False
            if anchor is not None:
                if moved:
                    end = self._position_at(event.position().toPoint())
                    self.select_column(*self._column_span(anchor, end))
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
        if alt and shift and not ctrl and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.duplicate_line(-1 if key == Qt.Key.Key_Up else 1)
            return True
        if alt and not ctrl and not shift and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move_line(-1 if key == Qt.Key.Key_Up else 1)
            return True
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._extra_cursors:
            self.clear_extra_cursors()
            event.accept()
            return
        if self._shortcut_action(event):
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
