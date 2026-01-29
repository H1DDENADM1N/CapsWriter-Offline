# https://gitee.com/xiaolixi/qt_ui/blob/master/notice/notice.py


import sys
import time
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DesktopNotification(QWidget):
    """桌面通知窗口"""

    notification_closed = Signal()  # 发送通知ID或标题

    def __init__(
        self,
        title: str = "通知",
        message: str = "",
        duration: int = 3000,
        notification_type: str = "info",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        # 窗口设置
        self.setWindowFlags(
            Qt.FramelessWindowHint  # 无边框
            | Qt.Tool  # 工具窗口
            | Qt.WindowStaysOnTopHint  # 置顶
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # 透明背景
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # 显示但不激活
        # 存储参数
        self.duration = duration
        self.notification_type = notification_type
        self.current_opacity = 1.0

        # 初始化UI
        self.init_ui(title, message)

        # 根据类型设置样式
        self.set_style_by_type()

    def init_ui(self, title: str, message: str):
        """初始化用户界面"""
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(8)

        # 标题栏
        title_layout = QHBoxLayout()

        # 图标和标题
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(20, 20)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        title_layout.addWidget(self.icon_label)
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()

        # 关闭按钮
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.clicked.connect(self.close_notification)

        title_layout.addWidget(self.close_btn)

        # 消息内容
        self.message_label = QLabel(message)
        self.message_label.setObjectName("message")
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(350)

        # 时间标签
        self.time_label = QLabel()
        self.time_label.setObjectName("time")
        self.update_time()

        # 添加到主布局
        layout.addLayout(title_layout)
        layout.addWidget(self.message_label)
        layout.addWidget(self.time_label)

        self.setLayout(layout)
        self.adjustSize()
        # 设置固定宽度，确保所有通知宽度一致
        self.setFixedWidth(400)

    def set_style_by_type(self):
        """根据通知类型设置样式"""
        # 定义不同类型颜色
        type_colors = {
            "info": {
                "bg": "#E3F2FD",  # 浅蓝
                "border": "#2196F3",  # 蓝色
                "icon": "ℹ️",
                "title": "#1565C0",
            },
            "success": {
                "bg": "#E8F5E9",  # 浅绿
                "border": "#4CAF50",  # 绿色
                "icon": "✅",
                "title": "#2E7D32",
            },
            "warning": {
                "bg": "#FFF3E0",  # 浅橙
                "border": "#FF9800",  # 橙色
                "icon": "⚠️",
                "title": "#EF6C00",
            },
            "error": {
                "bg": "#FFEBEE",  # 浅红
                "border": "#F44336",  # 红色
                "icon": "❌",
                "title": "#C62828",
            },
        }

        # 获取当前类型的颜色
        colors = type_colors.get(self.notification_type, type_colors["info"])

        # 设置图标
        self.icon_label.setText(colors["icon"])
        self.icon_label.setStyleSheet(f"font-size: 16px; color: {colors['border']};")

        # 设置标题颜色
        self.title_label.setStyleSheet(f"""
            font-weight: bold; 
            font-size: 14px; 
            color: {colors["title"]};
            padding: 0px;
        """)

        # 设置整体样式
        self.setStyleSheet(f"""
            DesktopNotification {{
                background-color: {colors["bg"]};
                border: 2px solid {colors["border"]};
                border-radius: 12px;
            }}
            
            QLabel#message {{
                font-size: 13px;
                color: #333333;
                padding: 0px;
                line-height: 1.4;
            }}
            
            QLabel#time {{
                font-size: 11px;
                color: #666666;
                padding: 0px;
            }}
            
            QPushButton#closeBtn {{
                background-color: transparent;
                color: #999999;
                border: none;
                font-size: 16px;
                font-weight: bold;
                border-radius: 10px;
            }}
            
            QPushButton#closeBtn:hover {{
                color: #666666;
                background-color: rgba(0, 0, 0, 0.1);
            }}
        """)

    def update_time(self):
        """更新时间显示"""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.setText(f"发布于 {current_time}")

    def show_notification(self, position: QPoint):
        """显示通知（带动画）"""
        self.show()
        self.move(position)

        # 淡入动画
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(400)
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.setEasingCurve(QEasingCurve.OutBack)
        self.animation.start()

        # 自动关闭定时器
        if self.duration > 0:
            QTimer.singleShot(self.duration, self.close_notification)

    def close_notification(self):
        """关闭通知（带动画）"""
        if hasattr(self, "animation") and self.animation:
            self.animation.stop()

        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.InCubic)

        def close_():
            self.notification_closed.emit()
            self.close()

        self.animation.finished.connect(close_)
        self.animation.start()

    def paintEvent(self, event):
        """绘制圆角和阴影效果"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制阴影
        painter.setBrush(QBrush(QColor(0, 0, 0, 30)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect().translated(2, 2), 12, 12)

        # 绘制背景
        painter.setBrush(self.palette().window())
        painter.setPen(self.palette().window().color().darker(150))
        painter.drawRoundedRect(self.rect(), 10, 10)

    def enterEvent(self, event):
        """鼠标进入时暂停自动关闭"""
        if hasattr(self, "timer") and self.timer.isActive():
            self.timer.stop()

    def leaveEvent(self, event):
        """鼠标离开时恢复自动关闭"""
        if hasattr(self, "timer") and not self.timer.isActive() and self.duration > 0:
            QTimer.singleShot(self.duration, self.close_notification)


class NotificationPanel(QWidget):
    """通知管理面板"""

    def __init__(self):
        super().__init__()
        self.notifications: List[DesktopNotification] = []
        self.init_ui()
        self.setup_notification_positions()

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("桌面通知系统")
        self.setGeometry(100, 100, 800, 600)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 标题
        title_label = QLabel("桌面通知演示系统")
        title_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: #2196F3;
            padding: 10px;
        """)
        title_label.setAlignment(Qt.AlignCenter)

        # 快速发送通知区域
        quick_send_group = QGroupBox("快速发送通知")
        quick_layout = QGridLayout()

        # 创建不同类型的快速通知按钮
        notification_types = [
            ("info", "普通通知", "发送普通信息通知"),
            ("success", "成功通知", "发送成功状态通知"),
            ("warning", "警告通知", "发送警告信息通知"),
            ("error", "错误通知", "发送错误信息通知"),
        ]

        for i, (n_type, text, tooltip) in enumerate(notification_types):
            btn = QPushButton(text)
            btn.setObjectName(f"{n_type}Btn")
            btn.setToolTip(tooltip)
            btn.clicked.connect(
                lambda checked, t=n_type: self.send_quick_notification(t)
            )
            quick_layout.addWidget(btn, i // 2, i % 2)

        quick_send_group.setLayout(quick_layout)

        # 自定义通知区域
        custom_group = QGroupBox("自定义通知")
        custom_layout = QFormLayout()

        # 标题输入
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("请输入通知标题")
        self.title_input.setText("这是一个自定义通知")
        custom_layout.addRow("标题:", self.title_input)

        # 消息输入
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("请输入通知内容")
        self.message_input.setMaximumHeight(80)
        self.message_input.setText("这是通知的详细内容，可以包含多行文本。")
        custom_layout.addRow("内容:", self.message_input)

        # 类型选择
        self.type_combo = QComboBox()
        self.type_combo.addItems(["info", "success", "warning", "error"])
        custom_layout.addRow("类型:", self.type_combo)

        # 持续时间
        duration_layout = QHBoxLayout()
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1000, 10000)
        self.duration_spin.setValue(3000)
        self.duration_spin.setSuffix(" 毫秒")
        duration_layout.addWidget(self.duration_spin)

        self.auto_close_check = QCheckBox("自动关闭")
        self.auto_close_check.setChecked(True)
        duration_layout.addWidget(self.auto_close_check)
        duration_layout.addStretch()

        custom_layout.addRow("持续时间:", duration_layout)

        # 发送按钮
        self.send_custom_btn = QPushButton("发送自定义通知")
        self.send_custom_btn.setObjectName("customBtn")
        self.send_custom_btn.clicked.connect(self.send_custom_notification)
        custom_layout.addRow("", self.send_custom_btn)

        custom_group.setLayout(custom_layout)

        # 控制按钮区域
        control_layout = QHBoxLayout()

        self.clear_btn = QPushButton("清除所有通知")
        self.clear_btn.setObjectName("clearBtn")
        self.clear_btn.clicked.connect(self.clear_all_notifications)

        self.demo_btn = QPushButton("演示模式")
        self.demo_btn.setObjectName("demoBtn")
        self.demo_btn.clicked.connect(self.start_demo_mode)

        control_layout.addWidget(self.clear_btn)
        control_layout.addWidget(self.demo_btn)
        control_layout.addStretch()

        # 添加到主布局
        main_layout.addWidget(title_label)
        main_layout.addWidget(quick_send_group)
        main_layout.addWidget(custom_group)
        main_layout.addLayout(control_layout)
        main_layout.addStretch()

        self.setLayout(main_layout)

        # 设置样式
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            
            QPushButton {
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                border: 2px solid transparent;
                font-size: 14px;
            }
            
            QPushButton#infoBtn {
                background-color: #2196F3;
                color: white;
            }
            
            QPushButton#infoBtn:hover {
                background-color: #1976D2;
            }
            
            QPushButton#successBtn {
                background-color: #4CAF50;
                color: white;
            }
            
            QPushButton#successBtn:hover {
                background-color: #388E3C;
            }
            
            QPushButton#warningBtn {
                background-color: #FF9800;
                color: white;
            }
            
            QPushButton#warningBtn:hover {
                background-color: #F57C00;
            }
            
            QPushButton#errorBtn {
                background-color: #F44336;
                color: white;
            }
            
            QPushButton#errorBtn:hover {
                background-color: #D32F2F;
            }
            
            QPushButton#customBtn {
                background-color: #9C27B0;
                color: white;
                font-size: 16px;
                padding: 12px;
            }
            
            QPushButton#customBtn:hover {
                background-color: #7B1FA2;
            }
            
            QPushButton#clearBtn {
                background-color: #607D8B;
                color: white;
            }
            
            QPushButton#clearBtn:hover {
                background-color: #455A64;
            }
            
            QPushButton#demoBtn {
                background-color: #FF5722;
                color: white;
            }
            
            QPushButton#demoBtn:hover {
                background-color: #E64A19;
            }
            
            QLineEdit, QTextEdit, QComboBox, QSpinBox {
                padding: 8px;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                font-size: 14px;
            }
            
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 2px solid #2196F3;
            }
        """)

    def setup_notification_positions(self):
        """设置通知显示位置"""
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        self.notification_x = screen_geometry.width() - 420  # 右上角x坐标
        self.notification_start_y = 40  # 起始y坐标
        self.notification_spacing = 15  # 通知间距

    def calculate_position(self, notification_index: int) -> QPoint:
        """计算新通知的位置"""
        y_offset = self.notification_start_y + (
            notification_index
            * (120 + self.notification_spacing)  # 120是通知的估计高度
        )

        # 如果超出屏幕高度，重置位置
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        if y_offset > screen_height - 150:
            y_offset = self.notification_start_y

        return QPoint(self.notification_x, y_offset)

    def send_notification(
        self,
        title: str,
        message: str,
        duration: int = 3000,
        notification_type: str = "info",
    ):
        """发送通知"""
        # 创建通知
        notification = DesktopNotification(
            title=title,
            message=message,
            duration=duration if self.auto_close_check.isChecked() else 0,
            notification_type=notification_type,
        )

        # 计算位置
        position = self.calculate_position(len(self.notifications))
        notification.show_notification(position)

        # 添加到列表
        self.notifications.append(notification)
        print("send_notification", len(self.notifications), time.time())

        def rvmove_s():
            self.notifications.remove(
                notification
            ) if notification in self.notifications else None
            print(
                notification in self.notifications, len(self.notifications), time.time()
            )

        # 清理已关闭的通知
        notification.notification_closed.connect(rvmove_s)

    def send_quick_notification(self, notification_type: str):
        """发送快速通知"""
        notifications = {
            "info": ("系统通知", "您的应用程序已准备就绪。"),
            "success": ("任务完成", "文件上传成功！"),
            "warning": ("存储警告", "磁盘空间不足，请及时清理。"),
            "error": ("连接错误", "无法连接到服务器，请检查网络。"),
        }

        title, message = notifications.get(notification_type, ("通知", "默认消息"))
        self.send_notification(title, message, 3000, notification_type)

    def send_custom_notification(self):
        """发送自定义通知"""
        title = self.title_input.text() or "自定义通知"
        message = self.message_input.toPlainText() or "这是自定义通知内容"
        duration = self.duration_spin.value()
        notification_type = self.type_combo.currentText()

        self.send_notification(title, message, duration, notification_type)

    def clear_all_notifications(self):
        """清除所有通知"""
        for notification in self.notifications[:]:
            notification.close_notification()
        self.notifications.clear()

    def start_demo_mode(self):
        """开始演示模式"""
        demo_messages = [
            ("欢迎使用", "这是一个桌面通知系统的演示。", "info"),
            ("操作成功", "您的设置已保存成功！", "success"),
            ("重要提醒", "您的密码将在7天后过期。", "warning"),
            ("发生错误", "保存文件时遇到问题。", "error"),
            ("新消息", "您有3条未读消息。", "info"),
        ]

        # 禁用演示按钮防止重复点击
        self.demo_btn.setText("演示中...")
        self.demo_btn.setEnabled(False)

        # 发送演示通知
        for i, (title, message, n_type) in enumerate(demo_messages):
            QTimer.singleShot(
                i * 1500,
                lambda t=title, m=message, nt=n_type: self.send_notification(
                    t, m, 2500, nt
                ),
            )

        # 重新启用按钮
        def my_function():
            self.demo_btn.setEnabled(True)
            self.demo_btn.setText("演示模式")

        QTimer.singleShot(len(demo_messages) * 1500 + 3000, my_function)

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.clear_all_notifications()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName("桌面通知系统")
    app.setApplicationDisplayName("桌面通知系统")

    # 设置全局字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    # 创建并显示主窗口
    window = NotificationPanel()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
