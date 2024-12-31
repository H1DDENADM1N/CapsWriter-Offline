from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from siui.components import (
    SiDenseVContainer,
    SiLineEditWithDeletionButton,
    SiTitledWidgetGroup,
)
from siui.components.button import (
    SiLongPressButtonRefactor,
    SiToggleButtonRefactor,
)
from siui.components.combobox import SiComboBox
from siui.components.option_card import SiOptionCardLinear
from siui.components.page import SiPage
from siui.components.spinbox.spinbox import SiIntSpinBox
from siui.components.titled_widget_group import SiTitledWidgetGroup
from siui.components.widgets import (
    SiDenseVContainer,
    SiSwitch,
)
from siui.core import SiGlobal

from .set_default_button import SetDefaultButton


class ServerConfigPage(SiPage):
    def __init__(self, config, config_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.config_path = config_path
        self.init_ui()
        self.addr_set_default.clicked.connect(
            lambda: self.addr.lineEdit().setText("0.0.0.0")
        )
        self.model.valueChanged.connect(lambda: self.model_changed())
        self.start_offline_translate_server.toggled.connect(
            lambda: self.start_offline_translate_server_changed()
        )
        self.in_the_meantime_start_the_client.toggled.connect(
            lambda: self.in_the_meantime_start_the_client_changed()
        )
        self.speech_recognition_port_set_default.clicked.connect(
            lambda: self.speech_recognition_port.setValue(6016)
        )
        self.offline_translate_port_set_default.clicked.connect(
            lambda: self.offline_translate_port.setValue(6017)
        )
        self.save.clicked.connect(self.save_config)

    def init_ui(self):
        self.setPadding(64)
        self.setScrollMaximumWidth(1000)
        self.setScrollAlignment(Qt.AlignLeft)
        self.setTitle("服务端配置")

        # 创建控件组
        self.titled_widgets_group = SiTitledWidgetGroup(self)
        self.titled_widgets_group.setSpacing(32)
        self.titled_widgets_group.setAdjustWidgetsSize(True)

        with self.titled_widgets_group as group:
            group.addTitle("通用")

            # 服务端监听地址
            self.addr = SiLineEditWithDeletionButton(self)
            self.addr.resize(256, 32)
            self.addr.lineEdit().setText(self.config["server"]["addr"])
            self.addr_set_default = SetDefaultButton(self)
            self.addr_linear_attaching = SiOptionCardLinear(self)
            self.addr_linear_attaching.setTitle(
                "服务端监听地址", '默认值："0.0.0.0" 监听所有网络接口'
            )
            self.addr_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_globe_location_regular")
            )
            self.addr_linear_attaching.addWidget(self.addr_set_default)
            self.addr_linear_attaching.addWidget(self.addr)
            group.addWidget(self.addr_linear_attaching)

            # 启动后是否自动缩小至托盘
            self.shrink_automatically_to_tray = SiSwitch(self)
            self.shrink_automatically_to_tray.setChecked(
                self.config["server"]["shrink_automatically_to_tray"]
            )
            self.shrink_automatically_to_tray_linear_attaching = SiOptionCardLinear(
                self
            )
            self.shrink_automatically_to_tray_linear_attaching.setTitle(
                "启动后自动缩小至托盘"
            )
            self.shrink_automatically_to_tray_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_phone_footer_arrow_down_regular")
            )
            self.shrink_automatically_to_tray_linear_attaching.addWidget(
                self.shrink_automatically_to_tray
            )
            group.addWidget(self.shrink_automatically_to_tray_linear_attaching)

            # 只允许运行一次，禁止多开
            self.only_run_once = SiSwitch(self)
            self.only_run_once.setChecked(self.config["server"]["only_run_once"])
            self.only_run_once_linear_attaching = SiOptionCardLinear(self)
            self.only_run_once_linear_attaching.setTitle("禁止多开", "只允许运行一次")
            self.only_run_once_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_star_one_quarter_filled")
            )
            self.only_run_once_linear_attaching.addWidget(self.only_run_once)
            group.addWidget(self.only_run_once_linear_attaching)

            # 启动服务端时同时启动客户端
            self.in_the_meantime_start_the_client = SiSwitch(self)
            self.in_the_meantime_start_the_client.setChecked(
                self.config["server"]["in_the_meantime_start_the_client"]
            )
            self.in_the_meantime_start_the_client_and_run_as_admin = (
                SiToggleButtonRefactor(self)
            )
            self.in_the_meantime_start_the_client_and_run_as_admin.resize(32, 32)
            self.in_the_meantime_start_the_client_and_run_as_admin.setSvgIcon(
                SiGlobal.siui.iconpack.get("ic_fluent_shield_person_filled")
            )
            self.in_the_meantime_start_the_client_and_run_as_admin.setToolTip(
                "启动服务端的同时以管理员权限启动客户端"
            )
            self.in_the_meantime_start_the_client_linear_attaching = SiOptionCardLinear(
                self
            )
            self.in_the_meantime_start_the_client_linear_attaching.setTitle(
                "启动服务端时同时启动客户端"
            )
            self.in_the_meantime_start_the_client_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_person_clock_filled")
            )
            self.in_the_meantime_start_the_client_and_run_as_admin.setChecked(
                self.config["server"][
                    "in_the_meantime_start_the_client_and_run_as_admin"
                ]
            )
            self.in_the_meantime_start_the_client_linear_attaching.addWidget(
                self.in_the_meantime_start_the_client
            )
            self.in_the_meantime_start_the_client_linear_attaching.addWidget(
                self.in_the_meantime_start_the_client_and_run_as_admin
            )
            self.in_the_meantime_start_the_client_changed()
            group.addWidget(self.in_the_meantime_start_the_client_linear_attaching)

        with self.titled_widgets_group as group:
            group.addTitle("语音识别")

            # 选择语音识别模型
            self.model = SiComboBox(self)
            self.model.resize(325, 32)
            self.model.addOption("Paraformer")
            self.model.addOption("Sensevoice")
            self.model.menu().setShowIcon(False)
            if self.config["server"]["model"] == "Paraformer":
                self.model.menu().setIndex(0)
            else:
                self.model.menu().setIndex(1)
            self.model_linear_attaching = SiOptionCardLinear(self)
            self.model_linear_attaching.setTitle("语音识别模型")
            self.model_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_brain_circuit_regular")
            )
            self.model_linear_attaching.addWidget(self.model)
            group.addWidget(self.model_linear_attaching)

            # 语音识别服务端口
            self.speech_recognition_port = SiIntSpinBox(self)
            self.speech_recognition_port.resize(256, 32)
            self.speech_recognition_port.setMinimum(1024)
            self.speech_recognition_port.setMaximum(65535)
            self.speech_recognition_port.setValue(
                int(self.config["server"]["speech_recognition_port"])
            )
            self.speech_recognition_port_set_default = SetDefaultButton(self)
            self.speech_recognition_port_linear_attaching = SiOptionCardLinear(self)
            self.speech_recognition_port_linear_attaching.setTitle(
                "语音识别服务端口", '默认值："6016" 端口号范围 1024-65535'
            )
            self.speech_recognition_port_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_globe_location_regular")
            )
            self.speech_recognition_port_linear_attaching.addWidget(
                self.speech_recognition_port_set_default
            )
            self.speech_recognition_port_linear_attaching.addWidget(
                self.speech_recognition_port
            )
            group.addWidget(self.speech_recognition_port_linear_attaching)

            # 是否将中文数字转为阿拉伯数字
            self.format_num = SiSwitch(self)
            self.format_num.setChecked(self.config["server"]["format_num"])
            self.format_num_linear_attaching = SiOptionCardLinear(self)
            self.format_num_linear_attaching.setTitle("将中文数字转为阿拉伯数字")
            self.format_num_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.format_num_linear_attaching.addWidget(self.format_num)
            group.addWidget(self.format_num_linear_attaching)

            # 使用 'Paraformer' 模型时，输出时是否启用标点符号引擎
            self.format_punc = SiSwitch(self)
            self.format_punc.setChecked(self.config["server"]["format_punc"])
            self.format_punc_linear_attaching = SiOptionCardLinear(self)
            self.format_punc_linear_attaching.setTitle("启用标点符号引擎")
            self.format_punc_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_brain_circuit_regular")
            )
            self.format_punc_linear_attaching.addWidget(self.format_punc)
            self.model_changed()
            group.addWidget(self.format_punc_linear_attaching)

            # 是否调整中英之间的空格
            self.format_spell = SiSwitch(self)
            self.format_spell.setChecked(self.config["server"]["format_spell"])
            self.format_spell_linear_attaching = SiOptionCardLinear(self)
            self.format_spell_linear_attaching.setTitle("调整中英之间的空格")
            self.format_spell_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.format_spell_linear_attaching.addWidget(self.format_spell)
            group.addWidget(self.format_spell_linear_attaching)

        with self.titled_widgets_group as group:
            group.addTitle("翻译")
            # 是否启用在线翻译服务
            self.start_online_translate_server = SiSwitch(self)
            self.start_online_translate_server.setChecked(
                self.config["server"]["start_online_translate_server"]
            )
            self.start_online_translate_server_linear_attaching = SiOptionCardLinear(
                self
            )
            self.start_online_translate_server_linear_attaching.setTitle(
                "启用在线翻译服务"
            )
            self.start_online_translate_server_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_translate_filled")
            )
            self.start_online_translate_server_linear_attaching.addWidget(
                self.start_online_translate_server
            )
            group.addWidget(self.start_online_translate_server_linear_attaching)

            # 是否启用离线翻译服务
            self.start_offline_translate_server = SiSwitch(self)
            self.start_offline_translate_server.setChecked(
                self.config["server"]["start_offline_translate_server"]
            )
            self.start_offline_translate_server_linear_attaching = SiOptionCardLinear(
                self
            )
            self.start_offline_translate_server_linear_attaching.setTitle(
                "启用离线翻译服务"
            )
            self.start_offline_translate_server_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_translate_auto_regular")
            )
            self.start_offline_translate_server_linear_attaching.addWidget(
                self.start_offline_translate_server
            )
            group.addWidget(self.start_offline_translate_server_linear_attaching)
            # # 离线翻译服务端口
            self.offline_translate_port = SiIntSpinBox(self)
            self.offline_translate_port.resize(256, 32)
            self.offline_translate_port.setMinimum(1024)
            self.offline_translate_port.setMaximum(65535)
            self.offline_translate_port.setValue(
                int(self.config["server"]["offline_translate_port"])
            )
            self.offline_translate_port_set_default = SetDefaultButton(self)
            self.offline_translate_port_linear_attaching = SiOptionCardLinear(self)
            self.offline_translate_port_linear_attaching.setTitle(
                "离线翻译服务端口", '默认值："6017" 端口号范围 1024-65535'
            )
            self.offline_translate_port_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_globe_location_regular")
            )
            self.offline_translate_port_linear_attaching.addWidget(
                self.offline_translate_port_set_default
            )
            self.offline_translate_port_linear_attaching.addWidget(
                self.offline_translate_port
            )
            self.start_offline_translate_server_changed()
            group.addWidget(self.offline_translate_port_linear_attaching)

        with self.titled_widgets_group as group:
            # 保存配置
            self.save = SiLongPressButtonRefactor(self)
            self.save.setSvgIcon(SiGlobal.siui.iconpack.get("ic_fluent_save_filled"))
            self.save.setIconSize(QSize(32, 32))
            self.save.setText("\t保存 服务端 配置")
            self.save.setFont(QFont("Microsoft YaHei", 16))
            self.save.setToolTip("长按以确认")
            self.save.resize(420, 64)
            # 查看更多容器
            self.save_container = SiDenseVContainer(self)
            self.save_container.setAlignment(Qt.AlignCenter)
            self.save_container.addWidget(self.save)

            group.addWidget(self.save_container)

        # 添加页脚的空白以增加美观性
        self.titled_widgets_group.addPlaceholder(64)

        # 设置控件组为页面对象
        self.setAttachment(self.titled_widgets_group)

    def model_changed(self):
        if self.model.value_label.text() == "Paraformer":
            self.format_punc.show()
        else:
            self.format_punc.hide()

    def start_offline_translate_server_changed(self):
        if self.start_offline_translate_server.isChecked():
            self.offline_translate_port_linear_attaching.show()
        else:
            self.offline_translate_port_linear_attaching.hide()

    def in_the_meantime_start_the_client_changed(self):
        if self.in_the_meantime_start_the_client.isChecked():
            self.in_the_meantime_start_the_client_and_run_as_admin.show()
        else:
            self.in_the_meantime_start_the_client_and_run_as_admin.hide()

    def save_config(self):
        def get_value_from_gui():
            self.config["server"]["model"] = self.model.value_label.text()
            self.config["server"]["addr"] = self.addr.line_edit.text()
            self.config["server"]["speech_recognition_port"] = str(
                self.speech_recognition_port.value()
            )
            self.config["server"]["start_online_translate_server"] = (
                self.start_online_translate_server.isChecked()
            )
            self.config["server"]["start_offline_translate_server"] = (
                self.start_offline_translate_server.isChecked()
            )
            self.config["server"]["offline_translate_port"] = str(
                self.offline_translate_port.value()
            )
            self.config["server"]["format_num"] = self.format_num.isChecked()
            self.config["server"]["format_punc"] = self.format_punc.isChecked()
            self.config["server"]["format_spell"] = self.format_spell.isChecked()
            self.config["server"]["shrink_automatically_to_tray"] = (
                self.shrink_automatically_to_tray.isChecked()
            )
            self.config["server"]["only_run_once"] = self.only_run_once.isChecked()
            self.config["server"]["in_the_meantime_start_the_client"] = (
                self.in_the_meantime_start_the_client.isChecked()
            )
            self.config["server"][
                "in_the_meantime_start_the_client_and_run_as_admin"
            ] = self.in_the_meantime_start_the_client_and_run_as_admin.isChecked()

        def print_config():
            from rich.console import Console
            from rich.table import Table

            from util.edit_config_gui.clearly_type import clearly_type

            console = Console()
            table = Table(title="保存 Paraformer 语音识别模型参数配置")
            table.add_column("属性名", style="cyan")
            table.add_column("类型", style="magenta")
            table.add_column("值", style="green")
            table.add_row(
                "model",
                clearly_type(self.config["server"]["model"]),
                str(self.config["server"]["model"]),
            )
            table.add_row(
                "addr",
                clearly_type(self.config["server"]["addr"]),
                str(self.config["server"]["addr"]),
            )
            table.add_row(
                "speech_recognition_port",
                clearly_type(self.config["server"]["speech_recognition_port"]),
                str(self.config["server"]["speech_recognition_port"]),
            )
            table.add_row(
                "start_online_translate_server",
                clearly_type(self.config["server"]["start_online_translate_server"]),
                str(self.config["server"]["start_online_translate_server"]),
            )
            table.add_row(
                "start_offline_translate_server",
                clearly_type(self.config["server"]["start_offline_translate_server"]),
                str(self.config["server"]["start_offline_translate_server"]),
            )
            table.add_row(
                "offline_translate_port",
                clearly_type(self.config["server"]["offline_translate_port"]),
                str(self.config["server"]["offline_translate_port"]),
            )
            table.add_row(
                "format_num",
                clearly_type(self.config["server"]["format_num"]),
                str(self.config["server"]["format_num"]),
            )
            table.add_row(
                "format_punc",
                clearly_type(self.config["server"]["format_punc"]),
                str(self.config["server"]["format_punc"]),
            )
            table.add_row(
                "format_spell",
                clearly_type(self.config["server"]["format_spell"]),
                str(self.config["server"]["format_spell"]),
            )
            table.add_row(
                "shrink_automatically_to_tray",
                clearly_type(self.config["server"]["shrink_automatically_to_tray"]),
                str(self.config["server"]["shrink_automatically_to_tray"]),
            )
            table.add_row(
                "only_run_once",
                clearly_type(self.config["server"]["only_run_once"]),
                str(self.config["server"]["only_run_once"]),
            )
            table.add_row(
                "in_the_meantime_start_the_client",
                clearly_type(self.config["server"]["in_the_meantime_start_the_client"]),
                str(self.config["server"]["in_the_meantime_start_the_client"]),
            )
            table.add_row(
                "in_the_meantime_start_the_client_and_run_as_admin",
                clearly_type(
                    self.config["server"][
                        "in_the_meantime_start_the_client_and_run_as_admin"
                    ]
                ),
                str(
                    self.config["server"][
                        "in_the_meantime_start_the_client_and_run_as_admin"
                    ]
                ),
            )
            console.print(table)

        get_value_from_gui()
        print_config()
        from util.edit_config_gui.write_toml import write_toml

        write_toml(self.config, self.config_path)
