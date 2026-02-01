import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QLabel


class Hint_While_Recording_At_Cursor_Position(QLabel):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        font = QFont("Segoe MDL2 Assets", 14)
        self.setFont(font)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#212121"))  # 设置背景颜色
        palette.setColor(QPalette.WindowText, QColor("#00B294"))  # 设置文本颜色
        self.setPalette(palette)
        self.setVisible(False)  # 初始时隐藏标签

        # 创建一个定时器来定期更新鼠标位置
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_tooltip_position)
        self.timer.start(100)  # 每100毫秒更新一次

        # 当前屏幕和缩放比例缓存
        self.current_screen = None
        self.current_device_pixel_ratio = 1.0
        self.test_counter = 0

    def update_tooltip_position(self):
        # 使用Qt的QCursor获取全局鼠标位置
        cursor_pos = QCursor.pos()

        # 获取当前鼠标所在的屏幕
        current_screen = QApplication.screenAt(cursor_pos)

        # 如果屏幕发生变化，更新缩放比例
        if current_screen and current_screen != self.current_screen:
            self.current_screen = current_screen
            self.current_device_pixel_ratio = current_screen.devicePixelRatio()
            print(
                f"屏幕切换到: {current_screen}, 缩放比例: {self.current_device_pixel_ratio}"
            )

        # 如果没有找到屏幕，使用主屏幕
        if current_screen is None:
            current_screen = QApplication.primaryScreen()
            self.current_device_pixel_ratio = (
                current_screen.devicePixelRatio() if current_screen else 1.0
            )

        # 获取屏幕的几何区域
        screen_geometry = current_screen.geometry()

        # 直接使用全局坐标，但需要考虑设备像素比的影响
        # 在高DPI显示器上，Qt会自动处理坐标转换，所以我们只需要添加偏移量
        final_x = cursor_pos.x() + 20
        final_y = cursor_pos.y() + 20

        # 检查并调整位置，确保提示框完全在屏幕内
        widget_width = self.sizeHint().width()
        widget_height = self.sizeHint().height()

        # 右边界检查
        if final_x + widget_width > screen_geometry.right():
            final_x = cursor_pos.x() - widget_width - 20

        # 下边界检查
        if final_y + widget_height > screen_geometry.bottom():
            final_y = cursor_pos.y() - widget_height - 20

        # 确保位置不小于屏幕左上角
        final_x = max(screen_geometry.left(), final_x)
        final_y = max(screen_geometry.top(), final_y)

        # 更新标签的位置和文本
        self.move(int(final_x), int(final_y))

        # 测试模式：交替显示和隐藏
        self.test_counter += 1
        if self.test_counter % 20 == 0:  # 每2秒切换一次
            self.setText(chr(0xF8B1))
            self.setVisible(True)
            print(f"显示提示框在位置: ({int(final_x)}, {int(final_y)})")
        elif self.test_counter % 20 == 10:  # 每2秒隐藏一次
            self.setVisible(False)
            print("隐藏提示框")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    tooltip = Hint_While_Recording_At_Cursor_Position()
    tooltip.show()  # 显示标签
    print("测试开始：提示框将跟随鼠标移动，每2秒显示/隐藏一次")
    print("移动鼠标到不同屏幕来测试多屏幕支持")
    sys.exit(app.exec())
