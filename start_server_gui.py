import multiprocessing as mul
import subprocess
import sys
import threading
from queue import Queue
from typing import Optional

from loguru import logger as default_logger
from loguru._logger import Logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qt_material import apply_stylesheet

from util.check_process import check_process
from util.config import DebugConfig
from util.config import ServerConfig as Config
from util.safe_logger import SafeLogger
from util.server.check_model import check_model_gui
from util.server.check_port import check_port_server


class GUI(QMainWindow):
    def __init__(self, logger: Optional[Logger] = None):
        super().__init__()
        self.logger = logger if logger is not None else default_logger
        self.init_ui()
        self.output_queue_server = Queue()
        self.start_script()

    def init_ui(self):
        self.resize(440, 440)
        self.setWindowTitle("CapsWriter-Offline-Server")
        self.setWindowIcon(QIcon("assets/icon/server-icon.ico"))
        self.create_text_box()
        self.create_clear_button()  # Create clear button
        self.create_systray_icon()
        self.hide()

    def create_text_box(self):
        self.text_box_server = QTextEdit()
        self.text_box_server.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_box_server.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCentralWidget(self.text_box_server)

    def create_clear_button(self):
        # Create a button
        self.clear_button = QPushButton("Clear Server Text", self)

        # Connect click event
        self.clear_button.clicked.connect(lambda: self.clear_text_box())

        # Create a vertical layout
        layout = QVBoxLayout()

        # Add text box and button to the layout
        layout.addWidget(self.text_box_server)
        layout.addWidget(self.clear_button)

        # Create a central widget
        central_widget = QWidget()
        central_widget.setLayout(layout)

        # Set the central widget
        self.setCentralWidget(central_widget)

    def clear_text_box(self):
        # Clear the content of the server text box
        self.text_box_server.clear()

    def create_systray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("assets/icon/server-icon.ico"))
        show_action = QAction("🪟 Show", self)
        restart_server_action = QAction("🔄 Restart Server", self)
        quit_action = QAction("❌ Quit", self)

        show_action.triggered.connect(self.showNormal)
        restart_server_action.triggered.connect(self.restart_server)
        quit_action.triggered.connect(self.quit_app)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        tray_menu = QMenu()
        tray_menu.addAction(show_action)
        tray_menu.addAction(restart_server_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def closeEvent(self, event):
        # Minimize to system tray instead of closing the window when the user clicks the close button
        self.hide()  # Hide the window
        event.ignore()  # Ignore the close event

    def restart_server(self):
        subprocess.Popen(
            [".\\runtime\\python.exe", ".\\util\\server\\restart.py"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding="utf-8",
        )

    def quit_app(self):
        # Terminate core_server.py process
        if hasattr(self, "core_server_process") and self.core_server_process:
            self.core_server_process.terminate()
            self.core_server_process.kill()

        # Hide the system tray icon
        self.tray_icon.setVisible(False)

        # Quit the application
        QApplication.quit()

        try:
            if Config.start_online_translate_server:
                proc = subprocess.Popen(
                    "taskkill /IM python_CapsWriter_Server.exe /IM deeplx_windows_amd64.exe /F",
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True,
                    text=True,
                )
            else:
                proc = subprocess.Popen(
                    "taskkill /IM python_CapsWriter_Server.exe /F",
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True,
                    text=True,
                )
            stdout, stderr = proc.communicate()
            logger.debug(f"Taskkill output: {stdout}")
            if stderr:
                logger.error(f"Taskkill errors: {stderr}")
        except Exception as e:
            logger.error(f"Error occurred while quitting the application: {e}")

    def show_window_centered(self):
        """显示窗口并居中"""
        # 激活窗口
        self.showNormal()
        self.activateWindow()

        # 临时设置窗口为置顶以便正确居中
        was_on_top = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        if not was_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()

        # 获取主屏幕几何信息
        screen_geometry = QApplication.primaryScreen().availableGeometry()

        # 获取窗口几何信息
        window_geometry = self.frameGeometry()

        # 计算居中位置
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)

        # 移动窗口到中心位置
        self.move(window_geometry.topLeft())

        # 恢复取消置顶
        self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
        self.show()

    def on_tray_icon_activated(self, reason):
        # Called when the system tray icon is activated
        if reason == QSystemTrayIcon.DoubleClick:
            # 如果窗口已经可见且在中心位置，则隐藏它
            if self.isVisible() and self.is_centered():
                self.hide()
            else:
                self.show_window_centered()  # Show the main window centered

    def is_centered(self):
        """检查窗口是否在屏幕中心"""
        # 获取屏幕几何信息
        screen = (
            self.screen() if hasattr(self, "screen") else QApplication.primaryScreen()
        )
        screen_geometry = screen.availableGeometry()

        # 获取窗口几何信息
        window_geometry = self.frameGeometry()

        # 计算预期的中心位置
        center_point = screen_geometry.center()
        expected_center_x = center_point.x() - window_geometry.width() // 2
        expected_center_y = center_point.y() - window_geometry.height() // 2

        # 检查当前窗口位置是否接近中心位置（允许几个像素的误差）
        tolerance = 5  # 像素容差
        return (
            abs(window_geometry.x() - expected_center_x) <= tolerance
            and abs(window_geometry.y() - expected_center_y) <= tolerance
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()  # Press ESC to hide main window

    def start_script(self):
        # Start core_server.py and redirect output to the server queue
        self.core_server_process = subprocess.Popen(
            [".\\runtime\\python_CapsWriter_Server.exe", "core_server.py"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(
            target=self.enqueue_output,
            args=(self.core_server_process.stdout, self.output_queue_server),
            daemon=True,
        ).start()

        # Update text box
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_text_box)
        self.update_timer.start(100)

    def enqueue_output(self, out, queue):
        for line in iter(out.readline, ""):
            line = line.strip()
            queue.put(line)

    def update_text_box(self):
        # Update server text box
        while not self.output_queue_server.empty():
            try:
                line = self.output_queue_server.get()
                self.text_box_server.append(line)
            except Exception as e:
                self.text_box_server.append(e)
                break

    def showEvent(self, event):
        self.text_box_server.moveCursor(QTextCursor.End)  # 滚动到最下行

    def enterEvent(self, event):
        self.text_box_server.moveCursor(QTextCursor.End)  # 滚动到最下行


if __name__ == "__main__":
    ctx = mul.get_context("spawn")
    SafeLogger(mp_context=ctx)
    default_logger.add(
        sink=sys.stderr,
        level=DebugConfig.logger_level,
        catch=True,
    )
    default_logger.info("Starting CapsWriter-Offline-Server GUI...")

    # 检查模型文件
    check_model_gui(passed_logger=default_logger)
    # 检查端口占用情况
    if Config.check_port_usage_before_start:
        used_port_infos: list | None = check_port_server(default_logger)
        if used_port_infos:
            raise Exception(f"端口被占用，无法启动服务端 {used_port_infos}")

    if Config.only_run_once and check_process(
        "python_CapsWriter_Server.exe", logger=default_logger
    ):
        raise Exception(
            "已经有一个服务端在运行了！（用户配置了 只允许运行一次，禁止多开；而且检测到 python_CapsWriter_Server.exe 进程已在运行。如果你确定需要启动多个服务端同时运行，请先修改 config.py  class ServerConfig:  Only_run_once = False 。）"
        )

    if Config.in_the_meantime_start_the_client and not (
        check_process("start_client_gui.exe", logger=default_logger)
        or check_process("start_client_gui_admin.exe", logger=default_logger)
    ):
        # 设置了启动服务端的同时启动客户端且客户端未在运行
        if Config.in_the_meantime_start_the_client_and_run_as_admin:
            # 以用管理员权限启动客户端...
            subprocess.Popen(
                ["start_client_gui_admin.exe"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            # 以用户权限启动客户端...
            subprocess.Popen(
                ["start_client_gui.exe"], creationflags=subprocess.CREATE_NO_WINDOW
            )

    app = QApplication([])
    apply_stylesheet(app, theme="dark_amber.xml")
    gui = GUI(logger=default_logger)
    if not Config.shrink_automatically_to_tray:
        gui.show()
    sys.exit(app.exec())
