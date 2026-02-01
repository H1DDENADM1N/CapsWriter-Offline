import argparse
import multiprocessing as mul
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Optional

import win32api
import win32con
import win32gui
import win32print
from loguru import logger as default_logger
from loguru._logger import Logger
from PySide6.QtCore import QFileSystemWatcher, QPoint, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QIcon,
    QPalette,
    QTextCursor,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qt_material import apply_stylesheet
from tomlkit import dumps, parse

from util.check_process import check_process
from util.client.check_microphone_usage import is_microphone_in_use
from util.config import ClientConfig as Config
from util.config import DebugConfig
from util.explorer_token_downgrade import downgraded_via_explorer_token
from util.notice import DesktopNotification
from util.safe_logger import SafeLogger


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
        self.setText(chr(0xF8B1))
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
        if is_microphone_in_use():
            self.setVisible(True)
        else:
            self.setVisible(False)


class TimeOverlayLabel(QLabel):
    """
    在界面上显示半透明的时间标签
    """

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._setup_style()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 让鼠标事件穿透
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 初始化时钟
        self._init_timer()

    def _setup_style(self):
        """设置时间标签样式"""
        self.setStyleSheet(
            """
            color: rgba(0, 178, 148, 255);
            background-color: transparent;
            font-family: 'LCD';
            font-size: 90px;
            font-weight: bold;
            """
        )

    def _init_timer(self):
        """初始化时钟功能"""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(50)  # 每50ms更新一次
        self.update_time()  # 立即更新一次时间

    def update_time(self):
        """更新时间显示"""
        # current_time = datetime.now().strftime("%H:%M:%S") # 24小时制
        current_time = datetime.now().strftime("%I:%M:%S")  # 12小时制
        self.setText(current_time)

    def stop_timer(self):
        """停止定时器"""
        if self.timer:
            self.timer.stop()

    def start_timer(self):
        """启动定时器"""
        if self.timer and not self.timer.isActive():
            self.timer.start(50)


class InputDialog_Api_Key:
    @staticmethod
    def get_text(
        parent=None,
        title="标题",
        label="标签",
        default="",
        on_submit=None,
        on_cancel=None,
        show_link=False,
        link_text="前往官网获取API Key",
        link_url="https://open.bigmodel.cn/usercenter/apikeys",
        is_password=True,
        placeholder="请输入API Key",
        validator=None,  # 输入验证器
    ):
        """
        显示增强版非模态输入弹窗
        Args:
            parent: 父窗口
            title: 窗口标题
            label: 提示标签
            default: 默认文本
            on_submit: 提交回调函数
            on_cancel: 取消回调函数
            show_link: 是否显示超链接
            link_text: 超链接显示文本
            link_url: 超链接URL
            is_password: 是否为密码输入
            placeholder: 输入框占位符文本
            validator: QValidator 输入验证器
        Returns:
            QDialog: 创建的对话框对象
        """
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setModal(False)

        # 设置窗口大小和置顶
        dialog.setFixedSize(520, 220)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

        # 创建主布局
        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # 标签区域
        if label:
            label_widget = QLabel(label)
            label_widget.setWordWrap(True)
            main_layout.addWidget(label_widget)

        # 超链接区域
        if show_link:
            link_container = QHBoxLayout()

            # 图标
            link_icon = QLabel("🔗")
            link_container.addWidget(link_icon)

            # 链接文本
            link_label = QLabel(
                f'<a href="{link_url}" style="color: #0066cc; text-decoration: none;">{link_text}</a>'
            )
            link_label.setOpenExternalLinks(True)
            link_label.setTextFormat(Qt.TextFormat.RichText)
            link_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextBrowserInteraction
            )
            link_container.addWidget(link_label)

            link_container.addStretch()
            main_layout.addLayout(link_container)

        # 输入区域
        input_container = QVBoxLayout()
        input_container.setSpacing(5)

        # 输入框和按钮的水平布局
        input_row = QHBoxLayout()

        # 输入框
        line_edit = QLineEdit()
        line_edit.setText(default)
        line_edit.setPlaceholderText(placeholder)

        # 设置回显模式
        if is_password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)

        # 设置验证器（如果有）
        if validator:
            line_edit.setValidator(validator)

        input_row.addWidget(line_edit)

        # 按钮容器
        button_container = QHBoxLayout()
        button_container.setSpacing(2)

        # 眼睛按钮（切换明文/密文）- 仅当是密码输入时显示
        if is_password:
            eye_button = QPushButton("按住显示明文")

            # 设置字体确保emoji显示正常
            font = eye_button.font()
            font_families = [
                "Segoe UI Emoji",  # Windows
                "Apple Color Emoji",  # macOS
                "Noto Color Emoji",  # Linux
                font.family(),
            ]
            font.setFamilies(font_families)
            eye_button.setFont(font)

            # 定时器用于鼠标移出检测（可选）
            mouse_leave_timer = QTimer()
            mouse_leave_timer.setSingleShot(False)
            mouse_leave_timer.setInterval(100)  # 每100ms检查一次

            # 标志位
            is_button_pressed = False

            def show_password():
                """按下按钮时显示明文"""
                nonlocal is_button_pressed
                is_button_pressed = True
                line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
                eye_button.setText("明文显示中")

                # 可选：启动定时器检测鼠标是否还在按钮上
                mouse_leave_timer.start()

            def hide_password():
                """松开按钮时隐藏密码"""
                nonlocal is_button_pressed
                is_button_pressed = False
                line_edit.setEchoMode(QLineEdit.EchoMode.Password)
                eye_button.setText("按住显示明文")
                mouse_leave_timer.stop()

            def check_mouse_position():
                """检查鼠标是否还在按钮上（可选功能）"""
                if is_button_pressed and not eye_button.underMouse():
                    hide_password()

            # 连接事件
            eye_button.pressed.connect(show_password)
            eye_button.released.connect(hide_password)

            # 连接定时器（可选）
            mouse_leave_timer.timeout.connect(check_mouse_position)

            # 确保即使鼠标移开，也能在鼠标释放时恢复密文
            # 添加一个鼠标移动事件处理，确保按钮释放时总是调用hide_password
            original_mouse_move_event = eye_button.mouseMoveEvent

            def custom_mouse_move_event(event):
                original_mouse_move_event(event)
                if is_button_pressed and not eye_button.underMouse():
                    # 如果鼠标移出按钮区域，检查鼠标是否还在按下状态
                    pass

            eye_button.mouseMoveEvent = custom_mouse_move_event

            button_container.addWidget(eye_button)

        input_row.addLayout(button_container)
        input_container.addLayout(input_row)

        main_layout.addLayout(input_container)

        # 按钮区域
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.setCenterButtons(True)

        # 样式化按钮
        ok_button = button_box.button(QDialogButtonBox.Ok)
        cancel_button = button_box.button(QDialogButtonBox.Cancel)

        ok_button.setMinimumWidth(80)
        cancel_button.setMinimumWidth(80)

        # 添加样式
        ok_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)

        main_layout.addWidget(button_box)

        # 连接信号
        def accept():
            if on_submit:
                on_submit(line_edit.text())
            dialog.accept()

        def reject():
            if on_cancel:
                on_cancel()
            dialog.reject()

        button_box.accepted.connect(accept)
        button_box.rejected.connect(reject)

        # 回车键支持
        line_edit.returnPressed.connect(accept)

        # 显示对话框并居中
        dialog.show()
        InputDialog_Api_Key.center_dialog(dialog)

        # 激活窗口并设置焦点
        dialog.activateWindow()
        line_edit.setFocus()
        line_edit.selectAll()

        # 窗口关闭时清理定时器
        def on_dialog_finished():
            if is_password and "mouse_leave_timer" in locals():
                mouse_leave_timer.stop()

        dialog.finished.connect(on_dialog_finished)

        return dialog

    @staticmethod
    def center_dialog(dialog):
        """将窗口居中显示在屏幕上"""
        frame_geometry = dialog.frameGeometry()
        screen = (
            dialog.screen()
            if hasattr(dialog, "screen")
            else QApplication.primaryScreen()
        )
        center_point = screen.availableGeometry().center()
        frame_geometry.moveCenter(center_point)
        dialog.move(frame_geometry.topLeft())


class GUI(QMainWindow):
    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger if logger is not None else default_logger
        super().__init__()
        self.config_toml_path = Path() / "config.toml"
        self.config_data = None  # 存储配置数据
        self.load_config()  # 初始加载配置
        self.init_ui()
        self.output_queue_client = Queue()
        self.start_script()
        self.edgeMargin = 5  # 侧边停靠残余像素值
        self.isBerthLeft = False
        self.isBerthRight = False
        self.original_stays_on_top = bool(
            self.windowFlags() & Qt.WindowStaysOnTopHint
        )  # 记录原始置顶状态

        # 初始化文件系统监控器
        self.init_file_watcher()

        # 初始化通知列表
        self.notifications = []

    def create_time_label(self):
        """创建时间标签"""
        if not hasattr(self, "time_label") and self.get_config_value(
            "client.show_time_label", False
        ):
            self.time_label = TimeOverlayLabel(self.centralWidget())
            self.adjust_time_label_position()

    def show_notification(
        self,
        title: str,
        message: str,
        duration: int = 3000,
        notification_type: str = "info",
    ):
        """显示自定义桌面通知

        Args:
            title: 通知标题
            message: 通知内容
            duration: 显示持续时间（毫秒）
            notification_type: 通知类型（info/success/warning/error）
        """
        # 创建通知
        notification = DesktopNotification(
            title=title,
            message=message,
            duration=duration,
            notification_type=notification_type,
        )

        # 计算通知位置（右上角）
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        notification_x = screen_geometry.width() - 420
        notification_y = 40 + len(self.notifications) * 135  # 每个通知间隔135像素

        # 如果超出屏幕高度，重置位置
        if notification_y > screen_geometry.height() - 150:
            notification_y = 40

        position = QPoint(notification_x, notification_y)
        notification.show_notification(position)

        # 添加到通知列表
        self.notifications.append(notification)

        # 清理已关闭的通知
        def remove_notification():
            if notification in self.notifications:
                self.notifications.remove(notification)

        notification.notification_closed.connect(remove_notification)

    def load_config(self):
        """加载配置文件到内存"""
        try:
            with open(self.config_toml_path, "r", encoding="utf-8") as f:
                config_str = f.read()
                self.config_data = parse(config_str)
            self.logger.debug("配置文件已加载到内存")
        except Exception as e:
            self.logger.error(f"读取配置文件失败: {e}")
            self.config_data = None

    def save_config(self):
        """保存配置数据到文件"""
        try:
            with open(self.config_toml_path, "w", encoding="utf-8") as f:
                f.write(dumps(self.config_data))
            self.logger.debug("配置已保存到文件")
            return True
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")
            return False

    def get_config_value(self, path: str, default=None):
        """通过点分隔的路径获取配置值"""
        if not self.config_data:
            self.load_config()
            if not self.config_data:
                return default

        try:
            # 使用点分割路径
            keys = path.split(".")
            value = self.config_data

            # 逐层访问嵌套字典
            for key in keys:
                if key in value:
                    value = value[key]
                else:
                    return default
            return value
        except Exception as e:
            self.logger.error(f"获取配置值失败 [{path}]: {e}")
            return default

    def set_config_value(self, path: str, value):
        """通过点分隔的路径设置配置值"""
        if not self.config_data:
            self.load_config()
            if not self.config_data:
                return False

        try:
            # 使用点分割路径
            keys = path.split(".")
            data = self.config_data

            # 逐层访问嵌套字典，如果不存在则创建
            for i, key in enumerate(keys[:-1]):
                if key not in data:
                    data[key] = {}
                data = data[key]

            # 设置最终的值
            data[keys[-1]] = value
            return True
        except Exception as e:
            self.logger.error(f"设置配置值失败 [{path}]: {e}")
            return False

    def init_ui(self):
        self.resize(425, 425)
        self.setWindowTitle("CapsWriter-Offline-Client")
        self.setWindowIcon(QIcon("assets/icon/client-icon.ico"))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.FramelessWindowHint  # 隐藏标题栏
            | Qt.Tool  # 隐藏Windows任务栏上的图标
            | Qt.WindowStaysOnTopHint  # 置顶
        )
        self.create_stay_on_top_button()
        self.create_show_time_label_button()
        self.create_cloudypaste_button()  # Create cloudy paste button
        self.create_clear_button()  # Create clear button
        self.create_close_button()
        self.create_custom_title_bar()
        self.create_text_box()
        self.create_monitor_checkbox()  # Create monitor checkbox
        # self.create_stay_on_top_checkbox()
        self.create_wordcount_label()
        self.create_systray_icon()

        # Create a vertical layout
        self.layout = QVBoxLayout()
        self.layout.setSpacing(0)  # 设置控件间距为0像素
        self.layout.setContentsMargins(3, 3, 3, 3)  # 设置左、上、右、下的边距
        self.layout2 = QHBoxLayout()
        self.layout2.setSpacing(0)  # 设置控件间距为0像素
        self.layout2.setContentsMargins(0, 0, 0, 0)  # 设置左、上、右、下的边距为0像素

        # Add text box and button to the layout
        self.layout.addLayout(self.title_bar)
        self.layout.addWidget(self.text_box_client)
        self.layout2.addWidget(self.monitor_checkbox, alignment=Qt.AlignLeft)
        # self.layout2.addWidget(self.stay_on_top_checkbox, alignment=Qt.AlignLeft)
        self.layout2.addSpacerItem(
            QSpacerItem(40, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        self.layout2.addWidget(self.text_box_wordCountLabel, alignment=Qt.AlignRight)
        self.layout.addLayout(self.layout2)

        # Create a central widget
        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        # Set the central widget
        self.setCentralWidget(central_widget)

    def init_file_watcher(self):
        """初始化文件系统监控器"""
        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.addPath(str(self.config_toml_path))
        self.file_watcher.fileChanged.connect(self.on_config_file_changed)

        # 使用定时器来防止多次触发
        self.config_update_timer = QTimer()
        self.config_update_timer.setSingleShot(True)
        self.config_update_timer.timeout.connect(self.update_tray_menu_from_config)

    def on_config_file_changed(self, path):
        """当配置文件发生变化时触发"""
        # 重新添加文件监控（因为文件变化时监控可能会失效）
        if not self.file_watcher.files():
            self.file_watcher.addPath(str(self.config_toml_path))

        # 重新加载配置到内存
        self.load_config()

        # 启动定时器，延迟更新，防止多次触发
        self.config_update_timer.start(1000)  # 1秒后更新

    def update_tray_menu_from_config(self):
        """从内存中的配置数据更新托盘菜单"""
        try:
            # 更新保存音频选项
            old_value_save_audio = self.get_config_value("client.save_audio", False)
            match old_value_save_audio:
                case True:
                    self.save_audio_action.setText("✅ 保存音频")
                case False:
                    self.save_audio_action.setText("❌ 保存音频")

            # 更新保存日记选项
            old_value_save_markdown = self.get_config_value(
                "client.save_markdown", False
            )
            match old_value_save_markdown:
                case True:
                    self.save_markdown_action.setText("✅ 保存日记")
                    self.save_non_kwd_markdown_action.setEnabled(True)
                    self.save_non_kwd_markdown_action.setText("⚙️ 保存非关键词日记")
                case False:
                    self.save_markdown_action.setText("❌ 保存日记")
                    self.save_non_kwd_markdown_action.setEnabled(False)
                    self.save_non_kwd_markdown_action.setText("❗ 请先启用保存日记")

            # 更新保存非关键词日记选项
            old_value_save_non_kwd_markdown = self.get_config_value(
                "client.save_non_kwd_markdown", False
            )
            match old_value_save_non_kwd_markdown:
                case True:
                    self.save_non_kwd_markdown_action.setText("✅ 保存非关键词日记")
                case False:
                    self.save_non_kwd_markdown_action.setText("❌ 保存非关键词日记")
            if old_value_save_markdown is False:
                self.save_non_kwd_markdown_action.setEnabled(False)
                self.save_non_kwd_markdown_action.setText("❗ 请先启用保存日记")

            # 更新简繁体转换选项
            old_value_convert_to_traditional_chinese_main = self.get_config_value(
                "client.convert_to_traditional_chinese_main", "简"
            )
            match old_value_convert_to_traditional_chinese_main:
                case "简":
                    self.convert_to_traditional_chinese_main_action.setText("简体中文")
                case "繁":
                    self.convert_to_traditional_chinese_main_action.setText("繁體中文")

            # 更新AI优化语言表达选项
            old_value_enable_ai_optimize_language_expression = self.get_config_value(
                "client.enable_ai_optimize_language_expression", False
            )
            match old_value_enable_ai_optimize_language_expression:
                case True:
                    self.enable_ai_optimize_language_expression_action.setText(
                        "✅ AI 优化语言表达"
                    )
                    self.prompt_style_menu.setEnabled(True)
                case False:
                    self.enable_ai_optimize_language_expression_action.setText(
                        "❌ AI 优化语言表达"
                    )
                    self.prompt_style_menu.setEnabled(False)

            # 更新AI供应商
            old_value_ai_provider_selection = self.get_config_value(
                "client.ai_provider", ""
            )
            self.update_ai_provider_menu(old_value_ai_provider_selection)

            # 更新AI提示风格
            old_value_prompt_style_selection = self.get_config_value(
                "client.prompt_style_selection", "official"
            )
            self.update_prompt_style_menu(old_value_prompt_style_selection)

            self.logger.debug("托盘菜单已根据配置文件更新")

        except Exception as e:
            self.logger.error(f"更新托盘菜单失败: {e}")

    def update_ai_provider_menu(self, ai_provider: str):
        """更新AI供应商菜单选中状态"""
        # 先取消所有选中状态
        for action in [
            self.ai_provider_zhipuai_action,
            self.ai_provider_openai_action,
        ]:
            action.setChecked(False)

        # 根据配置文件设置选中状态
        match ai_provider:
            case "zhipuai":
                self.ai_provider_zhipuai_action.setChecked(True)
            case "openai":
                self.ai_provider_openai_action.setChecked(True)
            case _:
                self.logger.warning(f"不支持的 AI 提供商：{ai_provider}")

    def show_prompt_style_notification(self, prompt_style: str):
        """显示提示风格变更通知"""
        notifications = {
            "official": ("新提示风格已启用", "正式公文"),
            "sweetheart": ("新提示风格已启用", "甜言蜜语"),
            "social": ("新提示风格已启用", "社媒文案"),
            "poetry": ("新提示风格已启用", "赋诗一首"),
            "english": ("新提示风格已启用", "英语大师"),
            "academic": ("新提示风格已启用", "学术论文"),
            "customer_service": ("新提示风格已启用", "客户服务"),
            "creative_writing": ("新提示风格已启用", "创意写作"),
        }

        if prompt_style in notifications:
            title, message = notifications[prompt_style]
            self.show_notification(title, message, 2000, "info")

    def update_prompt_style_menu(self, prompt_style: str):
        """更新提示风格菜单选中状态"""
        # 获取当前配置文件中的值
        actual_current_value = self.get_config_value(
            "client.prompt_style_selection", "official"
        )

        # 通过比较传入值和实际配置值来确定是否显示通知
        # 仅在函数被调用且值确实已更改时显示通知
        if hasattr(self, "_last_updated_prompt_style"):
            # 如果之前已更新过，那么比较上次更新的值和现在的实际配置值
            should_show_notification = (
                self._last_updated_prompt_style != actual_current_value
            )
        else:
            # 第一次调用，不显示通知
            should_show_notification = False

        # 更新内部记录的值
        self._last_updated_prompt_style = actual_current_value

        # 取消所有菜单项的选中状态
        all_actions = [
            self.prompt_official_action,
            self.prompt_sweetheart_action,
            self.prompt_social_action,
            self.prompt_poetry_action,
            self.prompt_english_action,
            self.prompt_academic_action,
            self.prompt_customer_service_action,
            self.prompt_creative_writing_action,
        ]

        for action in all_actions:
            action.setChecked(False)

        # 设置正确的菜单项为选中状态
        match prompt_style:
            case "official":
                self.prompt_official_action.setChecked(True)
            case "sweetheart":
                self.prompt_sweetheart_action.setChecked(True)
            case "social":
                self.prompt_social_action.setChecked(True)
            case "poetry":
                self.prompt_poetry_action.setChecked(True)
            case "english":
                self.prompt_english_action.setChecked(True)
            case "academic":
                self.prompt_academic_action.setChecked(True)
            case "customer_service":
                self.prompt_customer_service_action.setChecked(True)
            case "creative_writing":
                self.prompt_creative_writing_action.setChecked(True)
            case _:
                self.logger.warning(f"不支持的 AI 提示风格：{prompt_style}")

        # 启用了 是否在切换提示风格时显示提示  而且  AI 提示风格 确实发生变化时才显示通知
        if Config.show_prompt_style_changed_notification and should_show_notification:
            self.show_prompt_style_notification(actual_current_value)

    def create_custom_title_bar(self):
        # 创建自定义标题栏
        self.title_bar = QHBoxLayout()
        self.title_bar.addWidget(self.stay_on_top_button)
        self.title_bar.addWidget(self.show_time_label_button)
        self.title = QLabel("CapsWriter-Offline-Client")
        font = QFont()
        font.setBold(True)
        self.title.setFont(font)
        self.title_bar.addWidget(self.title)
        self.title_bar.addSpacerItem(
            QSpacerItem(80, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        self.title_bar.addWidget(self.cloudypaste_button, alignment=Qt.AlignRight)
        self.title_bar.addWidget(self.clear_button, alignment=Qt.AlignRight)
        self.title_bar.addWidget(self.close_button)

    def create_stay_on_top_button(self):
        self.stay_on_top_button = QPushButton()
        pin_char = chr(0xE840)
        self.stay_on_top_button.setText(pin_char)
        self.stay_on_top_button.setToolTip("置顶窗口，将它显示在其他窗口之上 / 不置顶")
        self.stay_on_top_button.setMaximumSize(50, 50)
        self.stay_on_top_button.clicked.connect(self.window_stay_on_top_toggled)

    def create_show_time_label_button(self):
        self.show_time_label_button = QPushButton()
        old_value_show_time_label = self.get_config_value(
            "client.show_time_label", False
        )
        show_char = chr(0xF43A)
        hide_char = chr(0xEAAE)
        match old_value_show_time_label:
            case True:
                self.show_time_label_button.setText(show_char)
            case False:
                self.show_time_label_button.setText(hide_char)
        self.show_time_label_button.setToolTip(
            "是否在鼠标离开客户端界面时 显示数字时钟 以代替 客户端界面"
        )
        self.show_time_label_button.setMaximumSize(50, 50)
        self.show_time_label_button.clicked.connect(self.show_time_label_button_toggled)

    def create_close_button(self):
        self.close_button = QPushButton(chr(0xE8BB))
        self.close_button.setMaximumSize(50, 50)
        self.close_button.clicked.connect(self.hide)

    def create_text_box(self):
        self.text_box_client = QTextEdit()
        self.text_box_client.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_box_client.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def create_monitor_checkbox(self):
        # 创建一个QCheckBox控件
        self.monitor_checkbox = QCheckBox("监听")
        self.monitor_checkbox.setToolTip("监听客户端输出 / 不监听，仅用作笔记本")
        self.monitor_checkbox.setMaximumSize(65, 30)
        # 当状态改变时，调用self.on_monitor_toggled函数
        self.monitor_checkbox.stateChanged.connect(self.on_monitor_toggled)
        # 设置默认状态
        self.monitor_checkbox.setChecked(True)

    def create_wordcount_label(self):
        self.text_box_wordCountLabel = QLabel("字符数字节数", self)
        self.text_box_wordCountLabel.setToolTip("光标已选中字符数 / 总字符数 | 字节数")
        self.text_box_wordCountLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.text_box_client.textChanged.connect(self.update_word_count_toggled)
        self.text_box_client.selectionChanged.connect(self.update_word_count_toggled)

    def create_cloudypaste_button(self):
        self.cloudypaste_button = QPushButton(chr(0xE753), self)
        self.cloudypaste_button.setToolTip(
            "将文本上传至云剪切板，方便向ios设备分享。基于 share.lanol.cn ，一个无依赖即用即走的剪切板。"
        )
        self.cloudypaste_button.setMaximumSize(80, 30)
        self.cloudypaste_button.clicked.connect(self.cloudy_paste)

    def create_clear_button(self):
        # Create a button
        self.clear_button = QPushButton(chr(0xE75C), self)
        self.clear_button.setToolTip("清空文本框中的全部内容")
        self.clear_button.setMaximumSize(80, 30)
        # Connect click event
        self.clear_button.clicked.connect(lambda: self.clear_text_box())

    def create_systray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("assets/icon/client-icon.ico"))
        edit_hot_en_action = QAction("Edit hot-en.txt", self)
        edit_hot_rule_action = QAction("Edit hot-rule.txt", self)
        edit_hot_zh_action = QAction("Edit hot-zh.txt", self)
        edit_keyword_action = QAction("Edit keywords.txt", self)

        explore_home_folder_action = QAction("📁 Open Home Folder With Explorer", self)
        vscode_home_folder_action = QAction("🤓 Open Home Folder With VSCode", self)
        chatglm_website_action = QAction("🤖 ChatGLM Website", self)

        self.save_audio_action = QAction("⚙️ 保存音频", self)
        self.save_markdown_action = QAction("⚙️ 保存日记", self)
        self.save_non_kwd_markdown_action = QAction("⚙️ 保存非关键词日记", self)
        self.convert_to_traditional_chinese_main_action = QAction(
            "⚙️ 默认使用 简/繁 体", self
        )
        self.enable_ai_optimize_language_expression_action = QAction(
            "⚙️ AI 优化语言表达", self
        )
        self.edit_api_key_action = QAction("🔑 修改 API Key", self)

        # 从内存配置中获取当前值
        old_value_save_audio = self.get_config_value("client.save_audio", False)
        old_value_save_markdown = self.get_config_value("client.save_markdown", False)
        old_value_save_non_kwd_markdown = self.get_config_value(
            "client.save_non_kwd_markdown", False
        )
        old_value_convert_to_traditional_chinese_main = self.get_config_value(
            "client.convert_to_traditional_chinese_main", "简"
        )
        old_value_enable_ai_optimize_language_expression = self.get_config_value(
            "client.enable_ai_optimize_language_expression", False
        )
        old_value_ai_provider_selection = self.get_config_value(
            "client.ai_provider", ""
        )
        old_value_prompt_style_selection = self.get_config_value(
            "client.prompt_style_selection", "official"
        )

        match old_value_save_audio:
            case True:
                self.save_audio_action.setText("✅ 保存音频")
            case False:
                self.save_audio_action.setText("❌ 保存音频")
        match old_value_save_markdown:
            case True:
                self.save_markdown_action.setText("✅ 保存日记")
            case False:
                self.save_markdown_action.setText("❌ 保存日记")
        match old_value_save_non_kwd_markdown:
            case True:
                self.save_non_kwd_markdown_action.setText("✅ 保存非关键词日记")
            case False:
                self.save_non_kwd_markdown_action.setText("❌ 保存非关键词日记")
        if old_value_save_markdown is False:
            self.save_non_kwd_markdown_action.setEnabled(False)
            self.save_non_kwd_markdown_action.setText("❗ 请先启用保存日记")
        match old_value_convert_to_traditional_chinese_main:
            case "简":
                self.convert_to_traditional_chinese_main_action.setText("简体中文")
            case "繁":
                self.convert_to_traditional_chinese_main_action.setText("繁體中文")
        match old_value_enable_ai_optimize_language_expression:
            case True:
                self.enable_ai_optimize_language_expression_action.setText(
                    "✅ AI 优化语言表达"
                )
            case False:
                self.enable_ai_optimize_language_expression_action.setText(
                    "❌ AI 优化语言表达"
                )

        self.ai_provider_selection = old_value_ai_provider_selection
        self.prompt_style_selection = old_value_prompt_style_selection

        github_website_action = QAction("🌐 GitHub Website", self)
        transcribe_file_action = QAction("📽️ Transcribe File", self)
        show_action = QAction("🪟 Show", self)
        config_selector_action = QAction("⚙️ Config Selector", self)
        restart_client_action = QAction("🔄 Restart Client", self)
        quit_action = QAction("❌ Quit", self)

        edit_hot_en_action.triggered.connect(self.edit_hot_en)
        edit_hot_rule_action.triggered.connect(self.edit_hot_rule)
        edit_hot_zh_action.triggered.connect(self.edit_hot_zh)
        edit_keyword_action.triggered.connect(self.edit_keyword)

        explore_home_folder_action.triggered.connect(self.explore_home_folder)
        vscode_home_folder_action.triggered.connect(self.vscode_home_folder)
        chatglm_website_action.triggered.connect(self.open_chatglm_website)

        self.save_audio_action.triggered.connect(self.toogle_save_audio)
        self.save_markdown_action.triggered.connect(self.toogle_save_markdown)
        self.save_non_kwd_markdown_action.triggered.connect(
            self.toogle_save_non_kwd_markdown
        )
        self.convert_to_traditional_chinese_main_action.triggered.connect(
            self.switch_between_simplified_and_traditional
        )
        self.enable_ai_optimize_language_expression_action.triggered.connect(
            self.toogle_ai_provider_and_ai_optimize_language_expression
        )
        self.edit_api_key_action.triggered.connect(self.edit_api_key)
        github_website_action.triggered.connect(self.open_github_website)
        transcribe_file_action.triggered.connect(self.transcribe_file)
        show_action.triggered.connect(self.showNormal)
        config_selector_action.triggered.connect(self.open_config_selector)
        restart_client_action.triggered.connect(self.restart_client)
        quit_action.triggered.connect(self.quit_app)

        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        tray_menu = QMenu()
        edit_menu = QMenu("📝 Edit Hot Rules", tray_menu)
        view_menu = QMenu("👁️ View", tray_menu)

        edit_menu.addAction(edit_hot_en_action)
        edit_menu.addAction(edit_hot_rule_action)
        edit_menu.addAction(edit_hot_zh_action)
        edit_menu.addAction(edit_keyword_action)

        view_menu.addAction(explore_home_folder_action)
        view_menu.addAction(vscode_home_folder_action)
        view_menu.addAction(chatglm_website_action)

        self.create_ai_provider_submenu(tray_menu)
        self.create_prompt_style_submenu(tray_menu)

        tray_menu.addMenu(edit_menu)
        tray_menu.addMenu(view_menu)
        tray_menu.addSeparator()
        tray_menu.addAction(self.save_audio_action)
        tray_menu.addAction(self.save_markdown_action)
        tray_menu.addAction(self.save_non_kwd_markdown_action)
        tray_menu.addAction(self.convert_to_traditional_chinese_main_action)
        tray_menu.addAction(self.enable_ai_optimize_language_expression_action)
        tray_menu.addMenu(self.ai_provider_menu)
        tray_menu.addAction(self.edit_api_key_action)
        tray_menu.addMenu(self.prompt_style_menu)
        tray_menu.addSeparator()
        tray_menu.addAction(github_website_action)
        tray_menu.addAction(transcribe_file_action)
        tray_menu.addSeparator()
        tray_menu.addAction(show_action)
        tray_menu.addAction(config_selector_action)
        tray_menu.addAction(restart_client_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def create_ai_provider_submenu(self, tray_menu: QMenu):
        self.ai_provider_menu = QMenu("🤖 AI 服务商", tray_menu)
        if (
            self.enable_ai_optimize_language_expression_action.text()
            == "❌ AI 优化语言表达"
        ):
            self.ai_provider_menu.setDisabled(True)
        else:
            self.ai_provider_menu.setEnabled(True)
        ai_provider_group = QActionGroup(self.ai_provider_menu)
        ai_provider_group.setExclusive(True)

        self.ai_provider_openai_action = QAction(
            "OpenAI（兼容）", self.ai_provider_menu
        )
        self.ai_provider_zhipuai_action = QAction("智谱AI", self.ai_provider_menu)

        self.ai_provider_openai_action.setCheckable(True)
        self.ai_provider_zhipuai_action.setCheckable(True)

        self.ai_provider_openai_action.triggered.connect(self.switch_ai_provider)
        self.ai_provider_zhipuai_action.triggered.connect(self.switch_ai_provider)

        ai_provider_group.addAction(self.ai_provider_openai_action)
        ai_provider_group.addAction(self.ai_provider_zhipuai_action)

        self.ai_provider_menu.addAction(self.ai_provider_openai_action)
        self.ai_provider_menu.addAction(self.ai_provider_zhipuai_action)

        self.update_ai_provider_menu(self.ai_provider_selection)

    def create_prompt_style_submenu(self, tray_menu: QMenu):
        self.prompt_style_menu = QMenu("🤖 AI 优化风格", tray_menu)
        if (
            self.enable_ai_optimize_language_expression_action.text()
            == "❌ AI 优化语言表达"
        ):
            self.prompt_style_menu.setDisabled(True)
        else:
            self.prompt_style_menu.setEnabled(True)
        prompt_style_group = QActionGroup(self.prompt_style_menu)
        prompt_style_group.setExclusive(True)

        self.prompt_official_action = QAction("正式公文", self.prompt_style_menu)
        self.prompt_sweetheart_action = QAction("甜言蜜语", self.prompt_style_menu)
        self.prompt_social_action = QAction("社媒文案", self.prompt_style_menu)
        self.prompt_poetry_action = QAction("赋诗一首", self.prompt_style_menu)
        self.prompt_english_action = QAction("英语大师", self.prompt_style_menu)
        self.prompt_academic_action = QAction("学术论文", self.prompt_style_menu)
        self.prompt_customer_service_action = QAction(
            "客户服务", self.prompt_style_menu
        )
        self.prompt_creative_writing_action = QAction(
            "创意写作", self.prompt_style_menu
        )

        self.prompt_official_action.setCheckable(True)
        self.prompt_sweetheart_action.setCheckable(True)
        self.prompt_social_action.setCheckable(True)
        self.prompt_poetry_action.setCheckable(True)
        self.prompt_english_action.setCheckable(True)
        self.prompt_academic_action.setCheckable(True)
        self.prompt_customer_service_action.setCheckable(True)
        self.prompt_creative_writing_action.setCheckable(True)

        self.prompt_official_action.triggered.connect(
            self.switch_prompt_style_selection
        )
        self.prompt_sweetheart_action.triggered.connect(
            self.switch_prompt_style_selection
        )
        self.prompt_social_action.triggered.connect(self.switch_prompt_style_selection)
        self.prompt_poetry_action.triggered.connect(self.switch_prompt_style_selection)
        self.prompt_english_action.triggered.connect(self.switch_prompt_style_selection)
        self.prompt_academic_action.triggered.connect(
            self.switch_prompt_style_selection
        )
        self.prompt_customer_service_action.triggered.connect(
            self.switch_prompt_style_selection
        )
        self.prompt_creative_writing_action.triggered.connect(
            self.switch_prompt_style_selection
        )

        prompt_style_group.addAction(self.prompt_official_action)
        prompt_style_group.addAction(self.prompt_sweetheart_action)
        prompt_style_group.addAction(self.prompt_social_action)
        prompt_style_group.addAction(self.prompt_poetry_action)
        prompt_style_group.addAction(self.prompt_english_action)
        prompt_style_group.addAction(self.prompt_academic_action)
        prompt_style_group.addAction(self.prompt_customer_service_action)
        prompt_style_group.addAction(self.prompt_creative_writing_action)

        self.prompt_style_menu.addAction(self.prompt_official_action)
        self.prompt_style_menu.addAction(self.prompt_sweetheart_action)
        self.prompt_style_menu.addAction(self.prompt_social_action)
        self.prompt_style_menu.addAction(self.prompt_poetry_action)
        self.prompt_style_menu.addAction(self.prompt_english_action)
        self.prompt_style_menu.addAction(self.prompt_academic_action)
        self.prompt_style_menu.addAction(self.prompt_customer_service_action)
        self.prompt_style_menu.addAction(self.prompt_creative_writing_action)

        self.update_prompt_style_menu(self.prompt_style_selection)

    def toogle_save_audio(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value("client.save_audio", False)
        # 切换值
        new_value = not old_value
        # 更新内存配置并保存到文件
        if self.set_config_value("client.save_audio", new_value):
            if self.save_config():
                # 更新托盘菜单
                if old_value:
                    self.save_audio_action.setText("❌ 保存音频")
                else:
                    self.save_audio_action.setText("✅ 保存音频")
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def toogle_save_markdown(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value("client.save_markdown", False)
        # 切换值
        new_value = not old_value
        # 更新内存配置并保存到文件
        if self.set_config_value("client.save_markdown", new_value):
            if self.save_config():
                # 更新托盘菜单
                if old_value:
                    self.save_markdown_action.setText("❌ 保存日记")
                    self.save_non_kwd_markdown_action.setText("❗ 请先启用保存日记")
                    self.save_non_kwd_markdown_action.setEnabled(False)
                else:
                    self.save_markdown_action.setText("✅ 保存日记")
                    self.save_non_kwd_markdown_action.setText("⚙️ 保存非关键词日记")
                    self.save_non_kwd_markdown_action.setEnabled(True)
                    self.update_save_non_kwd_markdown()
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def toogle_save_non_kwd_markdown(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value("client.save_non_kwd_markdown", False)
        # 切换值
        new_value = not old_value
        # 更新内存配置并保存到文件
        if self.set_config_value("client.save_non_kwd_markdown", new_value):
            if self.save_config():
                # 更新托盘菜单
                if old_value:
                    self.save_non_kwd_markdown_action.setText("❌ 保存非关键词日记")
                else:
                    self.save_non_kwd_markdown_action.setText("✅ 保存非关键词日记")
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def update_save_non_kwd_markdown(self):
        try:
            old_value = self.get_config_value("client.save_non_kwd_markdown", False)
            if old_value:
                self.save_non_kwd_markdown_action.setText("✅ 保存非关键词日记")
            else:
                self.save_non_kwd_markdown_action.setText("❌ 保存非关键词日记")
        except Exception as e:
            self.logger.error(f"更新托盘菜单失败: {e}")

    def switch_between_simplified_and_traditional(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value(
            "client.convert_to_traditional_chinese_main", "简"
        )
        # 切换值
        match old_value:
            case "简":
                new_value = "繁"
            case "繁":
                new_value = "简"
            case _:
                new_value = "简"
        # 更新内存配置并保存到文件
        if self.set_config_value(
            "client.convert_to_traditional_chinese_main", new_value
        ):
            if self.save_config():
                # 更新托盘菜单
                match old_value:
                    case "简":
                        self.convert_to_traditional_chinese_main_action.setText(
                            "繁體中文"
                        )
                    case "繁":
                        self.convert_to_traditional_chinese_main_action.setText(
                            "简体中文"
                        )
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def toogle_ai_provider_and_ai_optimize_language_expression(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value(
            "client.enable_ai_optimize_language_expression", False
        )
        # 切换值
        new_value = not old_value
        # 更新内存配置并保存到文件
        if self.set_config_value(
            "client.enable_ai_optimize_language_expression", new_value
        ):
            if self.save_config():
                # 更新托盘菜单
                if old_value:
                    self.enable_ai_optimize_language_expression_action.setText(
                        "❌ AI 优化语言表达"
                    )
                    self.ai_provider_menu.setDisabled(True)
                    self.ai_provider_menu.setTitle("❗ 请先启用AI优化语言表达")
                    self.prompt_style_menu.setDisabled(True)
                    self.prompt_style_menu.setTitle("❗ 请先启用AI优化语言表达")
                else:
                    self.enable_ai_optimize_language_expression_action.setText(
                        "✅ AI 优化语言表达"
                    )
                    self.ai_provider_menu.setEnabled(True)
                    self.ai_provider_menu.setTitle("🤖 AI 服务商")
                    self.prompt_style_menu.setEnabled(True)
                    self.prompt_style_menu.setTitle("🤖 AI 优化风格")
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def edit_api_key(self):
        """根据当前配置动态编辑相应的 API Key"""
        ai_provider = self.get_config_value("client.ai_provider", "zhipuai")

        match ai_provider:
            case "zhipuai":
                self.edit_zhipuai_api_key()
            case "openai":
                self.edit_openai_api_key()
            case _:
                self.show_unsupported_provider_warning(ai_provider)

    def edit_zhipuai_api_key(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value("client.zhipuai.api_key", "")
        # 获取新值
        InputDialog_Api_Key.get_text(
            parent=self,
            title="智谱AI API Key",
            label="请在此输入您的智谱AI API Key。如需获取新的API Key，请点击下方链接:",
            on_submit=self.update_zhipuai_api_key,
            # on_cancel=lambda: print("[yellow4]取消修改 API Key[/]"),
            default=old_value,
            placeholder="请输入API Key",
            show_link=True,
            link_text="访问智谱AI官网获取API Key",
            link_url="https://open.bigmodel.cn/usercenter/apikeys",
        )

    def edit_openai_api_key(self):
        # 从内存配置中获取当前值
        old_value = self.get_config_value("client.openai.api_key", "")
        # 获取新值
        InputDialog_Api_Key.get_text(
            parent=self,
            title="API Key",
            label="请在此输入您的 OpenAI（兼容） API Key。如需获取新的API Key，请点击下方链接:",
            on_submit=self.update_openai_api_key,
            # on_cancel=lambda: print("[yellow4]取消修改 API Key[/]"),
            default=old_value,
            placeholder="请输入API Key",
            show_link=True,
            link_text="访问 硅基流动 官网获取 API Key",
            link_url="https://cloud.siliconflow.cn/me/account/ak",
        )

    def show_unsupported_provider_warning(self, provider):
        """显示不支持的 AI 提供商警告"""
        # 显示自定义通知
        self.show_notification(
            "不支持的 AI 提供商",
            f"当前配置的 AI 提供商 '{provider}' 不支持\n请修改 config.toml 文件中的 ai_provider 设置",
            3000,
            "warning",
        )

        # 同时记录到日志
        self.logger.warning(f"不支持的 AI 提供商：{provider}")

    def update_zhipuai_api_key(self, new_value):
        # print(f"[green4]更新 API Key: {new_value}[/]")
        # 更新内存配置并保存到文件
        if self.set_config_value("client.zhipuai.api_key", new_value):
            if self.save_config():
                pass
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def update_openai_api_key(self, new_value):
        # print(f"[green4]更新 API Key: {new_value}[/]")
        # 更新内存配置并保存到文件
        if self.set_config_value("client.openai.api_key", new_value):
            if self.save_config():
                pass
            else:
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def switch_ai_provider(self):
        # 获取新值
        new_value: str = ""
        if self.ai_provider_openai_action.isChecked():
            new_value = "openai"
        elif self.ai_provider_zhipuai_action.isChecked():
            new_value = "zhipuai"
        else:
            new_value = ""

        # 更新内存配置并保存到文件
        if self.set_config_value("client.ai_provider", new_value):
            if not self.save_config():
                self.logger.error("保存配置文件失败")
        else:
            self.logger.error("更新内存配置失败")

    def switch_prompt_style_selection(self):
        # 获取新值
        new_value: str = ""
        if self.prompt_official_action.isChecked():
            new_value = "official"
        elif self.prompt_sweetheart_action.isChecked():
            new_value = "sweetheart"
        elif self.prompt_social_action.isChecked():
            new_value = "social"
        elif self.prompt_poetry_action.isChecked():
            new_value = "poetry"
        elif self.prompt_english_action.isChecked():
            new_value = "english"
        elif self.prompt_academic_action.isChecked():
            new_value = "academic"
        elif self.prompt_customer_service_action.isChecked():
            new_value = "customer_service"
        elif self.prompt_creative_writing_action.isChecked():
            new_value = "creative_writing"
        else:
            new_value = ""

        # 获取当前的配置值
        current_config_value = self.get_config_value(
            "client.prompt_style_selection", "official"
        )

        # 只有在值真正改变时才更新配置和显示通知
        if current_config_value != new_value:
            # 更新内存配置并保存到文件
            if self.set_config_value("client.prompt_style_selection", new_value):
                if self.save_config():
                    # 手动更新托盘菜单，这将显示通知（因为值确实改变了）
                    self.update_prompt_style_menu(new_value)
                else:
                    self.logger.error("保存配置文件失败")
            else:
                self.logger.error("更新内存配置失败")

    def restart_client(self):
        subprocess.Popen(
            [".\\runtime\\python.exe", ".\\util\\client\\restart.py"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding="utf-8",
        )

    def cloudy_paste(self):
        text = self.text_box_client.toPlainText()
        subprocess.Popen(
            [
                ".\\runtime\\pythonw.exe",
                ".\\util\\client\\cloud_clipboard_show_qrcode.py",
                text,
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding="utf-8",
        )

    def clear_text_box(self):
        # Clear the content of the client text box
        self.text_box_client.clear()
        # Resize Window
        self.resize(425, 425)

    def on_monitor_toggled(self, state):
        # 检查复选框的选中状态
        try:
            if state == 2:  # 2 表示选中状态
                self.update_timer.start(100)
            else:
                self.update_timer.stop()
        except AttributeError:
            pass  # 'GUI' object has no attribute 'update_timer' # 忽略该错误，因为初始化时还没有创建update_timer

    def window_stay_on_top_toggled(self):
        # 切换窗口置顶状态
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
            self.original_stays_on_top = False  # 更新原始状态
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.original_stays_on_top = True  # 更新原始状态
            global gui
        window_is_on_top = bool(gui.windowFlags() & Qt.WindowStaysOnTopHint)
        if window_is_on_top:
            pin_char = chr(0xE840)
            self.stay_on_top_button.setText(pin_char)
        else:
            unpin_char = " "
            self.stay_on_top_button.setText(unpin_char)
        self.show()  # 重新显示窗口以应用更改

    def show_time_label_button_toggled(self):
        # 切换是否在鼠标离开客户端界面时 显示数字时钟 以代替 客户端界面
        old_value_show_time_label = self.get_config_value(
            "client.show_time_label", False
        )
        show_char = chr(0xF43A)
        hide_char = chr(0xEAAE)
        match old_value_show_time_label:
            case True:
                if self.set_config_value("client.show_time_label", False):
                    if self.save_config():
                        self.show_time_label_button.setText(hide_char)
            case False:
                if self.set_config_value("client.show_time_label", True):
                    if self.save_config():
                        self.show_time_label_button.setText(show_char)

    def update_word_count_toggled(self):
        select_text_count = len(self.text_box_client.textCursor().selectedText())
        select_text_bytes = len(
            self.text_box_client.textCursor().selectedText().encode("utf-8")
        )
        total_text_count = len(self.text_box_client.toPlainText())
        total_text_bytes = len(self.text_box_client.toPlainText().encode("utf-8"))
        unselect_text_count = total_text_count - select_text_count
        unselect_text_bytes = total_text_bytes - select_text_bytes
        self.text_box_wordCountLabel.setText(
            f"{select_text_count} + {unselect_text_count} = {total_text_count} Words |  {select_text_bytes} + {unselect_text_bytes} = {total_text_bytes} Bytes"
        )
        if total_text_count > 10000:  # 字符数过多时自动清空
            self.text_box_client.clear()

    def edit_hot_en(self):
        os.startfile("hot-en.txt")

    def edit_hot_rule(self):
        os.startfile("hot-rule.txt")

    def edit_hot_zh(self):
        os.startfile("hot-zh.txt")

    def edit_keyword(self):
        os.startfile("keywords.txt")

    def explore_home_folder(self):
        current_directory = os.getcwd()
        os.startfile(current_directory)

    def vscode_home_folder(self):
        current_directory = os.getcwd()
        vscode_exe_path = Config.vscode_exe_path
        subprocess.Popen([vscode_exe_path, current_directory])

    def open_chatglm_website(self):
        QDesktopServices.openUrl(QUrl("https://chatglm.cn/main/alltoolsdetail"))

    def open_github_website(self):
        QDesktopServices.openUrl(
            QUrl("https://github.com/H1DDENADM1N/CapsWriter-Offline")
        )

    def open_config_selector(self):
        config_selector_path = Path("config_selector.exe")
        if config_selector_path.exists():
            subprocess.Popen(
                [str(config_selector_path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True,
                encoding="utf-8",
            )

    def transcribe_file(self):
        """转录音频/视频文件 - 修复版本"""
        try:
            download_path = QStandardPaths.writableLocation(
                QStandardPaths.DownloadLocation
            )
            media_filter = "媒体文件 (*.mp4 *.avi *.mkv *.mov *.wav *.mp3)"
            files, _ = QFileDialog.getOpenFileNames(
                self,  # 改为 self，而不是 None
                "选择媒体文件",
                download_path,
                f"{media_filter};;所有文件 (*.*)",
            )

            if not files:
                return

            self.logger.info(f"选择了 {len(files)} 个文件进行转录:")
            for file in files:
                self.logger.info(f"  - {file}")

            # 显示通知
            self.show_notification(
                "开始转录",
                f"已选择 {len(files)} 个文件，正在启动处理...",
                2000,
                "info",
            )

            # 启动文件处理，但不要退出当前进程
            self.start_batch_transcription(files)

        except Exception as e:
            self.logger.error(f"选择文件时出错: {e}")
            self.show_notification("错误", f"处理文件时出错: {str(e)}", 3000, "error")

    def start_batch_transcription(self, files):
        """启动批量转录"""
        try:
            CapsWriter_path = Path(__file__).parent
            script_path = CapsWriter_path / "core_client.py"
            python_exe_path = CapsWriter_path / "runtime" / "python.exe"
            files_quoted = [str(file) for file in files]
            command = [str(python_exe_path), str(script_path)] + files_quoted
            subprocess.Popen(command, cwd=str(CapsWriter_path))
        except Exception as e:
            self.logger.error(f"启动转录进程失败: {e}")

    def hideEvent(self, event):
        """当窗口被隐藏时停止时间标签计时器"""
        if self.get_config_value("client.show_time_label", False) and hasattr(
            self, "time_label"
        ):
            self.time_label.stop_timer()
        super().hideEvent(event)

    def showEvent(self, event):
        """当窗口显示时不显示时间标签而是显示客户端界面，并滚动到最下行"""
        self.show_client_interface()
        super().showEvent(event)

    def closeEvent(self, event):
        # Minimize to system tray instead of closing the window when the user clicks the close button
        self.hide()  # Hide the window
        event.ignore()  # Ignore the close event

    def show_client_interface(self):
        """不显示时间标签，显示客户端界面，并滚动到最下行"""
        if self.get_config_value("client.show_time_label", False) and hasattr(
            self, "time_label"
        ):
            self.time_label.stop_timer()
            self.time_label.hide()  # 隐藏时间标签
        self.resize(425, 425)
        self.text_box_client.setStyleSheet("background-color: rgba(35, 38, 41, 255);")
        self.setStyleSheet("background-color: rgba(49, 54, 59, 255);")
        self.text_box_client.setVisible(True)  # 显示文本框
        for i in range(self.title_bar.count()):  # 显示标题栏
            widget = self.title_bar.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(True)
        for i in range(self.layout2.count()):  # 显示操作栏
            widget = self.layout2.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(True)
        self.text_box_client.moveCursor(QTextCursor.End)  # 滚动到最下行

    def quit_app(self):
        # Terminate core_client.py process
        if hasattr(self, "core_client_process") and self.core_client_process:
            self.core_client_process.terminate()
            self.core_client_process.kill()

        # 停止文件监控器
        if hasattr(self, "file_watcher"):
            self.file_watcher.removePaths(self.file_watcher.files())
            self.config_update_timer.stop()

        # Hide the system tray icon
        self.tray_icon.setVisible(False)

        # Quit the application
        QApplication.quit()

        try:
            proc = subprocess.Popen(
                "taskkill /IM start_client_gui_admin.exe /IM start_client_gui.exe /IM python_CapsWriter_Client.exe /IM hint_while_recording.exe /F",
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
            )
            stdout, stderr = proc.communicate()
            self.logger.debug(f"Taskkill output: {stdout}")
            if stderr:
                self.logger.error(f"Taskkill errors: {stderr}")
        except Exception as e:
            self.logger.error(f"Error occurred while quitting the application: {e}")

    def on_tray_icon_activated(self, reason):
        # Called when the system tray icon is activated
        if reason == QSystemTrayIcon.DoubleClick:
            # 如果窗口是时钟状态且不再中心位置，从时钟状态切换为客户端界面
            if self.is_clock() and not self.is_centered():
                self.show_client_interface()
                return
            # 如果窗口已经可见且在中心位置，则隐藏它
            if self.isVisible() and self.is_centered():
                self.hide()
            else:
                self.show_window_centered()  # Show the main window centered

    def is_clock(self):
        """检查窗口是否是时钟状态"""
        if not self.get_config_value("client.show_time_label", False):
            return False
        if not hasattr(self, "time_label"):
            return False
        if not self.isVisible():
            return False
        if self.time_label.isVisible():  # 时间标签显示状态
            return True

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

    def show_window_centered(self):
        """显示窗口并居中"""
        # 激活窗口
        self.showNormal()
        self.activateWindow()
        self.show_client_interface()

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

        # 恢复原始的置顶状态
        if not self.original_stays_on_top and was_on_top:
            # 如果原始状态不是置顶，但现在是置顶的，则取消置顶
            self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
            self.show()
        elif self.original_stays_on_top and not was_on_top:
            # 如果原始状态是置顶，但现在不是置顶的，则设置为置顶
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()  # Press ESC to hide main window

    def start_script(self):
        # Start core_client.py and redirect output to the client queue
        self.core_client_process = subprocess.Popen(
            [".\\runtime\\python_CapsWriter_Client.exe", "core_client.py"],
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
            args=(self.core_client_process.stdout, self.output_queue_client),
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
        # Update client text box
        while not self.output_queue_client.empty():
            try:
                line = self.output_queue_client.get()
                self.text_box_client.append(line)
            except Exception as e:
                self.text_box_client.append(e)
                break

    def checkWindowActive(self):
        # 检查窗口是否处于活跃状态
        if self.isActiveWindow():
            pass
        else:
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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPosition().toPoint() - self.old_pos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.get_config_value("client.show_time_label", False):
            self.adjust_time_label_position()

    def adjust_time_label_position(self):
        """调整时间标签的位置，使其显示在文本框的中心，宽度与文本框相同"""
        if not self.get_config_value("client.show_time_label", False) or not hasattr(
            self, "time_label"
        ):
            return

        # 获取文本框的尺寸
        container_size = self.text_box_client.size()
        label_width = container_size.width()  # 宽度与文本框相同
        label_height = container_size.height()  # 高度与文本框相同

        # 设置时间标签位置（相对于父容器），覆盖整个文本框区域
        x = 7  # 从左边开始
        y = -100  # 从顶部开始

        self.time_label.setGeometry(x, y, label_width, label_height)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.logger.trace("[enterEvent] 鼠标进入窗口")
        if self.get_config_value("client.show_time_label", False):
            self.create_time_label()  # 确保时间标签存在
            self.time_label.stop_timer()  # 停止定时器
            self.text_box_client.setVisible(True)
            self.text_box_client.setStyleSheet(
                "background-color: rgba(35, 38, 41, 255);"
            )
            self.time_label.setVisible(False)
            self.adjust_time_label_position()
            self.setStyleSheet("background-color: rgba(49, 54, 59, 255);")
        # 添加诊断日志：记录resize前的窗口大小
        geometry_before = self.geometry()
        self.logger.trace(
            f"[enterEvent] resize前窗口大小: width={geometry_before.width()}, height={geometry_before.height()}"
        )
        self.resize(425, 425)
        # 添加诊断日志：记录resize后的窗口大小
        geometry_after = self.geometry()
        self.logger.trace(
            f"[enterEvent] resize后窗口大小: width={geometry_after.width()}, height={geometry_after.height()}"
        )
        for i in range(self.title_bar.count()):  # 鼠标进入时显示标题栏
            widget = self.title_bar.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(True)
        for i in range(self.layout2.count()):  # 鼠标进入时显示操作栏
            widget = self.layout2.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(True)
        self.text_box_client.moveCursor(QTextCursor.End)  # 滚动到最下行
        x, y, width, height, screenWidth, screenHeight, currentScreen = (
            self.checkWindowInfo()
        )
        currentScreenRect = currentScreen.geometry()
        self.logger.trace(
            f"[enterEvent] 窗口位置: x={x}, y={y}, width={width}, height={height}"
        )
        self.logger.trace(
            f"[enterEvent] 当前屏幕: left={currentScreenRect.left()}, right={currentScreenRect.right()}, width={screenWidth}, height={screenHeight}"
        )
        self.logger.trace(
            f"[enterEvent] isBerthLeft={self.isBerthLeft}, isBerthRight={self.isBerthRight}"
        )

        if self.isBerthLeft:  # 已停靠在左边
            target_x = currentScreenRect.left()
            self.logger.trace(f"[enterEvent] 从左边弹出，移动到 ({target_x}, {y})")
            self.move(target_x, y)  # 从左边弹出，使用当前屏幕的左边界
            self.isBerthLeft = False
        elif self.isBerthRight:  # 已停靠在右边
            target_x = currentScreenRect.right() - width
            self.logger.trace(f"[enterEvent] 从右边弹出，移动到 ({target_x}, {y})")
            self.move(target_x, y)  # 从右边弹出，使用当前屏幕的右边界
            self.isBerthRight = False
        else:
            self.logger.trace("[enterEvent] 窗口未停靠")
            # print("窗口未停靠")
            pass

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.logger.trace("[leaveEvent] 鼠标离开窗口")
        if self.get_config_value("client.show_time_label", False):
            self.create_time_label()  # 确保时间标签存在
            self.time_label.start_timer()  # 启动定时器
            self.text_box_client.setVisible(False)
            self.text_box_client.setStyleSheet("background-color: rgba(35, 38, 41, 0);")
            self.time_label.setVisible(True)
            self.adjust_time_label_position()
            self.setStyleSheet("background-color: rgba(49, 54, 59, 0);")
        # 添加诊断日志：记录resize前的窗口大小
        geometry_before = self.geometry()
        self.logger.trace(
            f"[leaveEvent] resize前窗口大小: width={geometry_before.width()}, height={geometry_before.height()}"
        )
        self.resize(425, 425)
        # 添加诊断日志：记录resize后的窗口大小
        geometry_after = self.geometry()
        self.logger.trace(
            f"[leaveEvent] resize后窗口大小: width={geometry_after.width()}, height={geometry_after.height()}"
        )
        for i in range(self.title_bar.count()):  # 鼠标离开时隐藏标题栏
            widget = self.title_bar.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(False)
        for i in range(self.layout2.count()):  # 鼠标离开时隐藏操作栏
            widget = self.layout2.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(False)
        x, y, width, height, screenWidth, screenHeight, currentScreen = (
            self.checkWindowInfo()
        )
        currentScreenRect = currentScreen.geometry()
        self.logger.trace(
            f"[leaveEvent] 窗口位置: x={x}, y={y}, width={width}, height={height}"
        )
        self.logger.trace(
            f"[leaveEvent] 当前屏幕: left={currentScreenRect.left()}, right={currentScreenRect.right()}, width={screenWidth}, height={screenHeight}"
        )
        # 计算窗口的边界坐标
        window_left = x
        window_right = x + width
        currentScreenRect = currentScreen.geometry()

        # 检查窗口是否超出当前屏幕的边界
        is_out_left = window_left < currentScreenRect.left() - width / 2
        is_out_right = window_right > currentScreenRect.right() + width / 2

        self.logger.trace(
            f"[leaveEvent] 边界检查: window_left={window_left}, window_right={window_right}, screen_left={currentScreenRect.left()}, screen_right={currentScreenRect.right()}"
        )
        self.logger.trace(
            f"[leaveEvent] 边界检查: is_out_left={is_out_left}, is_out_right={is_out_right}"
        )
        self.logger.trace(f"[leaveEvent] 窗口活跃状态: {self.isActiveWindow()}")

        if self.isActiveWindow():  # 窗口活跃状态，用户点击了窗口，则不恢复继续停靠
            self.logger.trace("[leaveEvent] 窗口活跃状态")
            if is_out_left:
                self.logger.trace(
                    "[leaveEvent] 活跃状态，窗口的一半已超出屏幕左边界，将窗口停靠在左边"
                )
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif is_out_right:
                self.logger.trace(
                    "[leaveEvent] 活跃状态，窗口的一半已超出屏幕右边界，将窗口停靠在右边"
                )
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            else:
                self.logger.trace("[leaveEvent] 活跃状态，无需停靠")
                # print("窗口活跃状态，无需停靠")
                pass
        else:  # 窗口非活跃状态，用户可能只是鼠标划过看一眼，失去焦点时恢复继续停靠
            self.logger.trace("[leaveEvent] 窗口不活跃状态")
            if is_out_left:
                self.logger.trace("[leaveEvent] 窗口的一半已超出屏幕左边界")
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif is_out_right:
                self.logger.trace("[leaveEvent] 窗口的一半已超出屏幕右边界")
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif (
                x == currentScreenRect.left()
            ):  # 窗口非活跃状态，从左边弹出的，恢复继续停靠在左边
                self.logger.trace(
                    "[leaveEvent] 窗口非活跃状态，从左边弹出的，恢复继续停靠在左边"
                )
                self.berthToLeft(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            elif (
                x == currentScreenRect.right() - width
            ):  # 窗口非活跃状态，从右边弹出的，恢复继续停靠在右边
                self.logger.trace(
                    "[leaveEvent] 窗口非活跃状态，从右边弹出的，恢复继续停靠在右边"
                )
                self.berthToRight(
                    x, y, width, height, screenWidth, screenHeight, currentScreen
                )
            else:
                self.logger.trace("[leaveEvent] 窗口未超出屏幕边界")
                # print("窗口未超出屏幕边界")
                pass

    def berthToLeft(
        self, x, y, width, height, screenWidth, screenHeight, currentScreen
    ):
        self.logger.debug("[berthToLeft] 开始停靠到左边")
        if self.get_config_value("client.show_time_label", False):
            self.logger.trace("[berthToLeft] show_time_label为True，不进行停靠")
            return  # 不停靠
        # 检测是否在屏幕交界处，如果是则不应用贴边隐藏
        is_at_boundary = self.isAtScreenBoundary(
            x, y, width, height, currentScreen, is_left=True
        )
        self.logger.trace(f"[berthToLeft] isAtScreenBoundary结果: {is_at_boundary}")
        if is_at_boundary:
            self.logger.trace("[berthToLeft] 在屏幕交界处，不进行停靠")
            return
        # 使用当前屏幕的绝对坐标，确保在副屏上也能正确停靠
        currentScreenRect = currentScreen.geometry()
        target_x = currentScreenRect.left() - width + self.edgeMargin
        self.logger.trace(f"[berthToLeft] 停靠位置: x={target_x}, y={y}")
        self.logger.trace(
            f"[berthToLeft] 当前屏幕左边界: {currentScreenRect.left()}, 窗口宽度: {width}, edgeMargin: {self.edgeMargin}"
        )
        self.move(target_x, y)  # 停靠到左边，31是标题栏高度
        self.isBerthLeft = True

    def berthToRight(
        self, x, y, width, height, screenWidth, screenHeight, currentScreen
    ):
        self.logger.debug("[berthToRight] 开始停靠到右边")
        if self.get_config_value("client.show_time_label", False):
            self.logger.trace("[berthToRight] show_time_label为True，不进行停靠")
            return  # 不停靠
        # 检测是否在屏幕交界处，如果是则不应用贴边隐藏
        is_at_boundary = self.isAtScreenBoundary(
            x, y, width, height, currentScreen, is_left=False
        )
        self.logger.trace(f"[berthToRight] isAtScreenBoundary结果: {is_at_boundary}")
        if is_at_boundary:
            self.logger.trace("[berthToRight] 在屏幕交界处，不进行停靠")
            return
        # 使用当前屏幕的绝对坐标，确保在副屏上也能正确停靠
        currentScreenRect = currentScreen.geometry()
        target_x = currentScreenRect.right() - self.edgeMargin
        self.logger.trace(f"[berthToRight] 停靠位置: x={target_x}, y={y}")
        self.logger.trace(
            f"[berthToRight] 当前屏幕右边界: {currentScreenRect.right()}, edgeMargin: {self.edgeMargin}"
        )
        self.move(target_x, y)  # 停靠到右边，31是标题栏高度
        self.isBerthRight = True

    def checkWindowInfo(self):
        geometry = self.geometry()
        x = geometry.x()
        y = geometry.y()
        width = geometry.width()
        height = geometry.height()
        # 添加诊断日志：记录窗口几何信息
        self.logger.trace(
            f"[checkWindowInfo] 获取窗口几何信息: x={x}, y={y}, width={width}, height={height}"
        )
        # 获取窗口中心点，用于确定窗口所在的屏幕
        center_point = QPoint(x + width // 2, y + height // 2)
        self.logger.trace(
            f"[checkWindowInfo] 窗口中心点: ({center_point.x()}, {center_point.y()})"
        )
        # 获取所有屏幕信息（诊断日志）
        screens = QApplication.instance().screens()
        self.logger.trace(f"[checkWindowInfo] 所有屏幕数量: {len(screens)}")
        for i, screen in enumerate(screens):
            rect = screen.geometry()
            self.logger.trace(
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

                self.logger.trace(
                    f"[checkWindowInfo] 屏幕{screenRect.left()}-{screenRect.right()}: 重叠面积={overlap_area}"
                )

                if overlap_area > max_overlap:
                    max_overlap = overlap_area
                    best_screen = screen

            if best_screen is not None:
                currentScreen = best_screen
                self.logger.trace(
                    f"[checkWindowInfo] 找到最佳屏幕: left={currentScreen.geometry().left()}, right={currentScreen.geometry().right()}"
                )
            else:
                # 如果仍然找不到，使用主屏幕作为后备
                self.logger.debug("[checkWindowInfo] 未找到重叠屏幕，使用主屏幕")
                currentScreen = QApplication.instance().primaryScreen()
        screenRect = currentScreen.geometry()
        screenWidth = screenRect.width()
        screenHeight = screenRect.height()
        self.logger.trace(
            f"[checkWindowInfo] 当前屏幕: left={screenRect.left()}, right={screenRect.right()}, width={screenWidth}, height={screenHeight}"
        )
        return x, y, width, height, screenWidth, screenHeight, currentScreen

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
        screens = QApplication.instance().screens()
        self.logger.trace(f"[isAtScreenBoundary] 屏幕数量: {len(screens)}")
        if len(screens) <= 1:
            # 只有一个屏幕，不存在交界处问题
            self.logger.trace("[isAtScreenBoundary] 只有一个屏幕，不存在交界处")
            return False

        # 获取当前屏幕的几何信息（绝对坐标）
        currentScreenRect = currentScreen.geometry()
        self.logger.trace(
            f"[isAtScreenBoundary] 当前屏幕: left={currentScreenRect.left()}, right={currentScreenRect.right()}"
        )

        # 计算窗口的边界坐标（绝对坐标）
        if is_left:
            window_edge_x = x
        else:
            window_edge_x = x + width

        self.logger.trace(f"[isAtScreenBoundary] 窗口边缘x坐标: {window_edge_x}")

        # 检查窗口边缘是否与当前屏幕的边缘重合（使用绝对坐标）
        if is_left:
            # 检查左边界是否与当前屏幕的左边界重合
            diff = abs(window_edge_x - currentScreenRect.left())
            self.logger.trace(f"[isAtScreenBoundary] 左边界差值: {diff}")
            if diff < 5:  # 5像素容差
                self.logger.trace("[isAtScreenBoundary] 在当前屏幕的左边界")
                return True  # 在当前屏幕的左边界
        else:
            # 检查右边界是否与当前屏幕的右边界重合
            diff = abs(window_edge_x - currentScreenRect.right())
            self.logger.trace(f"[isAtScreenBoundary] 右边界差值: {diff}")
            if diff < 5:  # 5像素容差
                self.logger.trace("[isAtScreenBoundary] 在当前屏幕的右边界")
                return True  # 在当前屏幕的右边界

        self.logger.trace("[isAtScreenBoundary] 不在屏幕交界处")
        return False

    def wheelEvent(self, event: QWheelEvent):
        # 设置初始缩放因子
        self.scale_factor = 1.0
        # 设置缩放因子的最小和最大值
        self.min_scale = 0.5
        self.max_scale = 2.0
        # 检测Ctrl键是否被按下
        if event.modifiers() == Qt.ControlModifier:
            # 计算缩放因子
            # print(event.angleDelta().y())
            if event.angleDelta().y() > 0:
                self.scale_factor *= 1.1  # 放大
            elif event.angleDelta().y() < 0:
                self.scale_factor *= 0.9  # 缩小
            # 限制缩放因子的范围
            self.scale_factor = max(
                self.min_scale, min(self.max_scale, self.scale_factor)
            )
            # 应用缩放因子到所有控件
            self.apply_scale_factor()
        else:
            super().wheelEvent(event)

    def apply_scale_factor(self):
        # 应用缩放因子
        for widget in [self.text_box_client]:
            # 检查字体大小是否已设置，如果没有设置，则使用一个默认值
            current_font = widget.font()
            if current_font.pointSizeF() < 9:
                current_font.setPointSizeF(9)  # 设置一个默认字体大小
            current_font.setPointSizeF(current_font.pointSizeF() * self.scale_factor)
            widget.setFont(current_font)


def start_client_gui(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    Print_Screen_Scale(logger=_logger)
    if Config.only_run_once and check_process(
        "python_CapsWriter_Client.exe", logger=_logger
    ):
        raise Exception(
            "已经有一个客户端在运行了！（用户配置了 只允许运行一次，禁止多开；而且检测到 python_CapsWriter_Client.exe 进程已在运行。如果你确定需要启动多个客户端同时运行，请先修改 config.py  class ClientConfig:  Only_run_once = False 。）"
        )
    if (
        Config.hint_while_recording_at_edit_position_powered_by_ahk
        and not check_process("hint_while_recording.exe", logger=_logger)
        and Path("hint_while_recording.exe").exists()
    ):
        try:
            # 降权运行 AHK 提示
            downgraded_via_explorer_token(
                "hint_while_recording.exe", working_directory=str(Path.cwd())
            )
        except Exception:
            subprocess.Popen(
                ["hint_while_recording.exe"], creationflags=subprocess.CREATE_NO_WINDOW
            )
    app = QApplication(sys.argv)
    if Config.hint_while_recording_at_cursor_position:
        tooltip = Hint_While_Recording_At_Cursor_Position()
        tooltip.show()
    apply_stylesheet(
        app, theme="dark_teal.xml", css_file="util\\client\\gui_theme_custom.css"
    )
    global gui
    gui = GUI(logger=_logger)
    if not Config.shrink_automatically_to_tray:
        gui.show()
    sys.exit(app.exec())


def Print_Screen_Scale(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    # 获取屏幕的宽度和高度
    hDC = win32gui.GetDC(0)
    screen_width = win32print.GetDeviceCaps(hDC, win32con.DESKTOPHORZRES)
    screen_height = win32print.GetDeviceCaps(hDC, win32con.DESKTOPVERTRES)
    _logger.debug(f"屏幕尺寸: {screen_width}x{screen_height}")
    # 获取逻辑的宽度和高度
    logical_width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    logical_height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    _logger.debug(f"逻辑尺寸: {logical_width}x{logical_height}")
    # 计算缩放比例
    global scale_x, scale_y
    scale_x = screen_width / logical_width
    scale_y = screen_height / logical_height
    _logger.debug(f"屏幕缩放比例: {scale_x}, {scale_y}")


def read_file_list(file_list_path: Path):
    """读取文件列表文件，返回文件路径列表"""
    with open(file_list_path, "r", encoding="utf-8") as f:
        return [Path(line.strip()) for line in f if line.strip()]


if __name__ == "__main__":
    ctx = mul.get_context("spawn")
    SafeLogger(mp_context=ctx)
    default_logger.add(
        sink=sys.stderr,
        level=DebugConfig.logger_level,
        catch=True,
    )
    default_logger.info("启动 CapsWriter 客户端 GUI...")
    parser = argparse.ArgumentParser(description="处理文件")
    parser.add_argument("files", nargs="*", type=Path, help="要处理的文件")
    parser.add_argument("--file-list", type=Path, help="包含文件列表的文本文件")
    args = parser.parse_args()

    if args.file_list:  # 如果传递了 --file-list 参数
        default_logger.debug(f"读取文件列表: {args.file_list}")
        try:
            files = read_file_list(args.file_list)
        except Exception as e:
            default_logger.error(f"读取文件列表失败: {e}")
            sys.exit(1)
    else:
        files = args.files  # 直接传递的文件列表

    if files:  # 如果有文件需要处理
        default_logger.debug(f"处理文件: {files}")
        CapsWriter_path = Path(__file__).parent
        script_path = CapsWriter_path / "core_client.py"
        python_exe_path = CapsWriter_path / "runtime" / "python.exe"
        files_quoted = [str(file) for file in files]
        command = [str(python_exe_path), str(script_path)] + files_quoted
        try:
            subprocess.Popen(command, cwd=str(CapsWriter_path))
        except Exception as e:
            default_logger.error(f"启动进程失败: {e}")
    else:
        # GUI
        default_logger.debug("没有文件需要处理，启动 GUI")
        start_client_gui(logger=default_logger)
