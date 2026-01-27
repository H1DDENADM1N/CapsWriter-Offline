import multiprocessing as mul
import shutil
import sys
from pathlib import Path
from typing import Optional

from loguru import logger as default_logger
from loguru._logger import Logger
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qt_material import apply_stylesheet

from util.client.restart import stop_client
from util.config import DebugConfig
from util.explorer_token_downgrade import downgraded_via_explorer_token
from util.safe_logger import SafeLogger
from util.server.restart import stop_server


class ConfigSelector(QDialog):
    def __init__(self, logger: Optional[Logger] = None):
        super().__init__()
        self.logger = logger if logger is not None else default_logger

        self.current_dir = Path.cwd()
        self.configs_dir = self.current_dir / "configs"
        self.target_config = self.current_dir / "config.toml"

        self.init_ui()
        self.load_configs()

    def init_ui(self):
        self.setFixedSize(520, 220)
        self.setWindowTitle("配置选择器")
        self.setWindowIcon(QIcon("assets/icon/config-selector-icon.ico"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self.label = QLabel(
            '请在切换配置前，<font color="#f44336">手动关闭</font> 服务端和客户端！<br><br>请选择一个配置文件:'
        )
        main_layout.addWidget(self.label)

        self.combo_box = QComboBox()
        self.combo_box.setMinimumHeight(50)
        main_layout.addWidget(self.combo_box)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        self.confirm_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")

        self.confirm_btn.setMinimumWidth(80)
        self.cancel_btn.setMinimumWidth(80)
        self.confirm_btn.setMinimumHeight(50)
        self.cancel_btn.setMinimumHeight(50)

        self.confirm_btn.setStyleSheet("""
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

        self.cancel_btn.setStyleSheet("""
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

        button_layout.addStretch()
        button_layout.addWidget(self.confirm_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()

        main_layout.addLayout(button_layout)

        # 连接事件
        self.confirm_btn.clicked.connect(self.on_confirm)
        self.cancel_btn.clicked.connect(self.reject)

    def load_configs(self):
        """
        加载配置文件列表
        从 configs 文件夹中读取 .toml 文件名称，并添加到 combo_box 中
        """
        self.combo_box.clear()

        if not self.configs_dir.exists():
            QMessageBox.warning(
                self, "错误", f"未找到 configs 文件夹:\n{self.configs_dir}"
            )
            self.confirm_btn.setEnabled(False)
            return

        toml_files = list(self.configs_dir.glob("*.toml"))

        if not toml_files:
            QMessageBox.information(self, "提示", "configs 文件夹下没有找到 .toml 文件")
            self.confirm_btn.setEnabled(False)
            return

        for file_path in toml_files:
            self.combo_box.addItem(file_path.stem)

        self.confirm_btn.setEnabled(True)

    def on_confirm(self):
        selected_filename = self.combo_box.currentText()

        if not selected_filename:
            QMessageBox.warning(self, "警告", "未选择任何文件")
            return

        source_file = self.configs_dir / f"{selected_filename}.toml"

        if not source_file.exists():
            QMessageBox.critical(self, "错误", f"源文件不存在: {source_file}")
            self.logger.error(f"源文件不存在: {source_file}")
            return

        try:
            if self.target_config.exists():
                try:
                    self.target_config.unlink()
                    self.logger.info("已删除旧的 config.toml")
                except Exception as e:
                    QMessageBox.critical(
                        self, "错误", f"无法删除当前的 config.toml:\n{e}"
                    )
                    self.logger.error(f"无法删除当前的 config.toml:\n{e}")
                    return

            shutil.copy(source_file, self.target_config)

            self.logger.info(f"成功应用配置: {selected_filename}.toml")

            # 显示新的OK/Cancel弹窗
            reply = QMessageBox.question(
                self,
                "配置已切换",
                f'🎉 配置已切换为: {selected_filename}.toml<br><br>是否立即重启服务以生效新配置？<br><br><font color="#f44336">注意：这将会关闭客户端和服务端。</font>',
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok,
            )

            if reply == QMessageBox.Ok:
                self.on_restart_to_enable_new_config()

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作过程中发生未知错误:\n{e}")
            self.logger.error(f"操作过程中发生未知错误:\n{e}")

    def on_restart_to_enable_new_config(self):
        stop_client(logger=self.logger)
        stop_server(logger=self.logger)
        downgraded_via_explorer_token(
            "start_server_gui.exe", working_directory=str(self.current_dir)
        )


if __name__ == "__main__":
    ctx = mul.get_context("spawn")
    SafeLogger(mp_context=ctx)
    default_logger.add(
        sink=sys.stderr,
        level=DebugConfig.logger_level,
        catch=True,
    )
    default_logger.info("Starting config selector...")
    app = QApplication(sys.argv)
    apply_stylesheet(
        app, theme="dark_blue.xml", css_file="util\\client\\gui_theme_custom.css"
    )

    dialog = ConfigSelector(logger=default_logger)
    dialog.show()

    dialog.activateWindow()

    sys.exit(app.exec())
