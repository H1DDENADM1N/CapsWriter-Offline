import sys

from loguru import logger as default_logger
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.edgeMargin = 5  # 侧边停靠残余像素值
        self.isBerthLeft = False
        self.isBerthRight = False
        self.logger = default_logger
        self.initUI()

    def initUI(self):
        self.resize(425, 425)
        self.setWindowTitle("多屏贴边停靠测试 v2")
        self.setWindowOpacity(0.9)
        self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
        self.label = QLabel("多屏贴边停靠演示 v2\n支持多显示器环境", self)
        self.label.setGeometry(10, 10, 425, 425)
        self.label.setAlignment(Qt.AlignCenter)

        # 创建一个定时器，每隔三秒检查窗口状态
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.checkWindowActive)
        self.timer.start(3000)  # 3000毫秒间隔

        self.logger.info("窗口初始化完成")

    def checkWindowActive(self):
        """检查窗口是否处于活跃状态"""
        if self.isActiveWindow():
            self.label.setText("窗口活跃状态")
            self.logger.info("窗口处于活跃状态")
        else:
            self.label.setText("窗口不活跃状态")
            self.logger.info("窗口处于不活跃状态")
            x, y, width, height, screenWidth, screenHeight, currentScreen = (
                self.checkWindowInfo()
            )
            if x == 0:  # 窗口非活跃状态，从左边弹出的，恢复继续停靠在左边
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif (
                x == screenWidth - width
            ):  # 窗口非活跃状态，从右边弹出的，恢复继续停靠在右边
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            else:
                self.logger.debug("窗口无需恢复停靠")
                pass

    def enterEvent(self, event):
        """鼠标进入窗口事件"""
        super().enterEvent(event)
        self.logger.debug("鼠标进入窗口")
        x, y, width, height, screenWidth, screenHeight, currentScreen = (
            self.checkWindowInfo()
        )
        currentScreenRect = currentScreen.geometry()
        if self.isBerthLeft:  # 已停靠在左边
            target_x = currentScreenRect.left()
            self.logger.debug(f"[enterEvent] 从左边弹出，移动到 ({target_x}, {y})")
            self.move(target_x, y)  # 从左边弹出，使用当前屏幕的左边界
            self.isBerthLeft = False
        elif self.isBerthRight:  # 已停靠在右边
            target_x = currentScreenRect.right() - width
            self.logger.debug(f"[enterEvent] 从右边弹出，移动到 ({target_x}, {y})")
            self.move(target_x, y)  # 从右边弹出，使用当前屏幕的右边界
            self.isBerthRight = False
        else:
            self.logger.debug("[enterEvent] 窗口未停靠")

    def leaveEvent(self, event):
        """鼠标离开窗口事件"""
        super().leaveEvent(event)
        self.logger.debug("鼠标离开窗口")
        x, y, width, height, screenWidth, screenHeight, currentScreen = (
            self.checkWindowInfo()
        )
        currentScreenRect = currentScreen.geometry()
        self.logger.debug(f"窗口信息: x={x}, y={y}, width={width}, height={height}, ")
        self.logger.debug(
            f"[leaveEvent] 当前屏幕: left={currentScreenRect.left()}, right={currentScreenRect.right()}, width={screenWidth}, height={screenHeight}"
        )
        # 计算窗口的边界坐标
        window_left = x
        window_right = x + width
        currentScreenRect = currentScreen.geometry()

        # 检查窗口是否超出当前屏幕的边界
        is_out_left = window_left < currentScreenRect.left() - width / 2
        is_out_right = window_right > currentScreenRect.right() + width / 2

        self.logger.debug(
            f"[leaveEvent] 边界检查: window_left={window_left}, window_right={window_right}, screen_left={currentScreenRect.left()}, screen_right={currentScreenRect.right()}"
        )
        self.logger.debug(
            f"[leaveEvent] 边界检查: is_out_left={is_out_left}, is_out_right={is_out_right}"
        )
        self.logger.debug(f"[leaveEvent] 窗口活跃状态: {self.isActiveWindow()}")

        if self.isActiveWindow():  # 窗口活跃状态，用户点击了窗口，则不恢复继续停靠
            self.label.setText("窗口活跃状态")
            self.logger.info("窗口活跃状态")
            if is_out_left:
                self.logger.debug(
                    "[leaveEvent] 活跃状态，窗口的一半已超出屏幕左边界，将窗口停靠在左边"
                )
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif is_out_right:
                self.logger.debug(
                    "[leaveEvent] 活跃状态，窗口的一半已超出屏幕右边界，将窗口停靠在右边"
                )
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            else:
                self.logger.debug("[leaveEvent] 活跃状态，无需停靠")
                # print("窗口活跃状态，无需停靠")
                pass
        else:  # 窗口非活跃状态，用户可能只是鼠标划过看一眼，失去焦点时恢复继续停靠
            self.label.setText("窗口不活跃状态")
            self.logger.info("窗口不活跃状态")
            if is_out_left:
                self.logger.debug("[leaveEvent] 窗口的一半已超出屏幕左边界")
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif is_out_right:
                self.logger.debug("[leaveEvent] 窗口的一半已超出屏幕右边界")
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif (
                x == currentScreenRect.left()
            ):  # 窗口非活跃状态，从左边弹出的，恢复继续停靠在左边
                self.logger.debug(
                    "[leaveEvent] 窗口非活跃状态，从左边弹出的，恢复继续停靠在左边"
                )
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif (
                x == currentScreenRect.right() - width
            ):  # 窗口非活跃状态，从右边弹出的，恢复继续停靠在右边
                self.logger.debug(
                    "[leaveEvent] 窗口非活跃状态，从右边弹出的，恢复继续停靠在右边"
                )
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            else:
                self.logger.debug("[leaveEvent] 窗口未超出屏幕边界")
                # print("窗口未超出屏幕边界")
                pass

    def berthToLeft(
        self, x, y, width, height, screenWidth, screenHeight, currentScreen
    ):
        """停靠到左边"""
        self.logger.debug("[berthToLeft] 开始停靠到左边")

        # 检查是否在屏幕交界处
        if self.isAtScreenBoundary(x, y, width, height, currentScreen, is_left=True):
            self.logger.debug("[berthToLeft] 在屏幕交界处，不进行停靠")
            return

        currentScreenRect = currentScreen.geometry()
        target_x = currentScreenRect.left() - width + self.edgeMargin
        self.logger.debug(f"[berthToLeft] 停靠位置: x={target_x}, y={y}")
        self.logger.debug(
            f"[berthToLeft] 当前屏幕左边界: {currentScreenRect.left()}, "
            f"窗口宽度: {width}, edgeMargin: {self.edgeMargin}"
        )
        self.move(target_x, y)  # 停靠到左边
        self.isBerthLeft = True
        self.logger.debug("[berthToLeft] 停靠完成")

    def berthToRight(
        self, x, y, width, height, screenWidth, screenHeight, currentScreen
    ):
        """停靠到右边"""
        self.logger.debug("[berthToRight] 开始停靠到右边")

        # 检查是否在屏幕交界处
        if self.isAtScreenBoundary(x, y, width, height, currentScreen, is_left=False):
            self.logger.debug("[berthToRight] 在屏幕交界处，不进行停靠")
            return

        currentScreenRect = currentScreen.geometry()
        target_x = currentScreenRect.right() - self.edgeMargin
        self.logger.debug(f"[berthToRight] 停靠位置: x={target_x}, y={y}")
        self.logger.debug(
            f"[berthToRight] 当前屏幕右边界: {currentScreenRect.right()}, edgeMargin: {self.edgeMargin}"
        )
        self.move(target_x, y)  # 停靠到右边
        self.isBerthRight = True
        self.logger.debug("[berthToRight] 停靠完成")

    def isAtScreenBoundary(self, x, y, width, height, currentScreen, is_left=True):
        """
        检测窗口是否位于屏幕交界处（多显示器环境下的主副屏交界）
        如果是交界处，则不应用贴边隐藏

        Args:
            x: 窗口x坐标（绝对坐标）
            y: 窗口y坐标
            width: 窗口宽度
            height: 窗口高度
            currentScreen: 窗口当前所在的屏幕
            is_left: 是否检测左边界（True为左边界，False为右边界）

        Returns:
            bool: 如果在交界处返回True，否则返回False
        """
        self.logger.debug(f"[isAtScreenBoundary] 开始检测，is_left={is_left}")

        # 获取所有屏幕
        screens = QApplication.screens()
        self.logger.debug(f"[isAtScreenBoundary] 屏幕数量: {len(screens)}")

        if len(screens) <= 1:
            # 只有一个屏幕，不存在交界处问题
            self.logger.debug("[isAtScreenBoundary] 只有一个屏幕，不存在交界处")
            return False

        # 获取当前屏幕的几何信息（绝对坐标）
        currentScreenRect = currentScreen.geometry()
        self.logger.debug(
            f"[isAtScreenBoundary] 当前屏幕: left={currentScreenRect.left()}, "
            f"right={currentScreenRect.right()}"
        )

        # 计算窗口的边界坐标（绝对坐标）
        if is_left:
            window_edge_x = x
        else:
            window_edge_x = x + width

        self.logger.debug(f"[isAtScreenBoundary] 窗口边缘x坐标: {window_edge_x}")

        # 检查窗口边缘是否与当前屏幕的边缘重合（使用绝对坐标）
        if is_left:
            # 检查左边界是否与当前屏幕的左边界重合
            diff = abs(window_edge_x - currentScreenRect.left())
            self.logger.debug(f"[isAtScreenBoundary] 左边界差值: {diff}")
            if diff < 5:  # 5像素容差
                self.logger.debug("[isAtScreenBoundary] 在当前屏幕的左边界")
                return True  # 在当前屏幕的左边界
        else:
            # 检查右边界是否与当前屏幕的右边界重合
            diff = abs(window_edge_x - currentScreenRect.right())
            self.logger.debug(f"[isAtScreenBoundary] 右边界差值: {diff}")
            if diff < 5:  # 5像素容差
                self.logger.debug("[isAtScreenBoundary] 在当前屏幕的右边界")
                return True  # 在当前屏幕的右边界

    def checkWindowInfo(self):
        geometry = self.geometry()
        x = geometry.x()
        y = geometry.y()
        width = geometry.width()
        height = geometry.height()
        # 添加诊断日志：记录窗口几何信息
        self.logger.debug(
            f"[checkWindowInfo] 获取窗口几何信息: x={x}, y={y}, width={width}, height={height}"
        )
        # 获取窗口中心点，用于确定窗口所在的屏幕
        center_point = QPoint(x + width // 2, y + height // 2)
        self.logger.debug(
            f"[checkWindowInfo] 窗口中心点: ({center_point.x()}, {center_point.y()})"
        )
        # 获取所有屏幕信息（诊断日志）
        screens = QApplication.instance().screens()
        self.logger.debug(f"[checkWindowInfo] 所有屏幕数量: {len(screens)}")
        for i, screen in enumerate(screens):
            rect = screen.geometry()
            self.logger.debug(
                f"[checkWindowInfo] 屏幕{i}: left={rect.left()}, right={rect.right()}, width={rect.width()}, height={rect.height()}"
            )
        # 获取窗口当前所在的屏幕
        currentScreen = QApplication.instance().screenAt(center_point)
        if currentScreen is None:
            # 如果找不到屏幕，找到与窗口重叠面积最大的屏幕
            self.logger.debug(
                "[checkWindowInfo] 找不到屏幕，查找与窗口重叠面积最大的屏幕"
            )
            self.logger.debug(
                f"[checkWindowInfo] 窗口中心点({center_point.x()}, {center_point.y()})超出所有屏幕范围"
            )
            self.logger.debug(
                f"[checkWindowInfo] 窗口位置: x={x}, y={y}, width={width}, height={height}"
            )

            max_overlap = 0
            best_screen = None

            for screen in screens:
                screenRect = screen.geometry()
                # 计算窗口与屏幕的交集
                overlap_left = max(x, screenRect.left())
                overlap_right = min(x + width, screenRect.right())
                overlap_top = max(y, screenRect.top())
                overlap_bottom = min(y + height, screenRect.bottom())

                # 计算重叠面积
                overlap_width = max(0, overlap_right - overlap_left)
                overlap_height = max(0, overlap_bottom - overlap_top)
                overlap_area = overlap_width * overlap_height

                self.logger.debug(
                    f"[checkWindowInfo] 屏幕{screenRect.left()}-{screenRect.right()}: 重叠面积={overlap_area}"
                )

                if overlap_area > max_overlap:
                    max_overlap = overlap_area
                    best_screen = screen

            if best_screen is not None:
                currentScreen = best_screen
                self.logger.debug(
                    f"[checkWindowInfo] 找到最佳屏幕: left={currentScreen.geometry().left()}, right={currentScreen.geometry().right()}"
                )
            else:
                # 如果仍然找不到，使用主屏幕作为后备
                self.logger.debug("[checkWindowInfo] 未找到重叠屏幕，使用主屏幕")
                currentScreen = QApplication.instance().primaryScreen()
        screenRect = currentScreen.geometry()
        screenWidth = screenRect.width()
        screenHeight = screenRect.height()
        self.logger.debug(
            f"[checkWindowInfo] 当前屏幕: left={screenRect.left()}, right={screenRect.right()}, width={screenWidth}, height={screenHeight}"
        )
        return x, y, width, height, screenWidth, screenHeight, currentScreen


def test_gui():
    """测试GUI函数"""
    app = QApplication([])
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    test_gui()
