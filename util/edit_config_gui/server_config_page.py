from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from rich import print
from rich.console import Console
from rich.table import Table
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

from util.edit_config_gui.clearly_type import clearly_type
from util.edit_config_gui.value_check import ValueCheck
from util.edit_config_gui.write_toml import write_toml

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
        self.save.longPressed.connect(self.save_config)
        # 数据校验绑定
        self.addr.lineEdit().editingFinished.connect(self.validate_addr)
        self.save.clicked.connect(self.validate_addr)
        self.save.clicked.connect(self.validate_speech_recognition_port)
        self.save.clicked.connect(self.validate_offline_translate_port)

    def validate_addr(self):
        ip: str = self.addr.lineEdit().text()
        is_valid, error = ValueCheck.is_local_listenable_ip(ip)

        if is_valid:
            print(f"[green]{ip}[/green]")
        else:
            print(f"[red]{ip} - {error if error else '无效'}[/red]")

        if error:
            self.addr.lineEdit().setText("0.0.0.0")
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="服务端监听地址格式错误",
                    text=f'{ip} - {error}\n已修改为默认值："0.0.0.0"',
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_speech_recognition_port(self):
        port: str = str(self.speech_recognition_port.value())
        is_valid, error = ValueCheck.is_local_listenable_port(port)

        if is_valid:
            print(f"[green]{port}[/green]")
        else:
            print(f"[red]{port} - {error if error else '无效'}[/red]")

        if error:
            self.speech_recognition_port.setValue(6016)
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="语音识别服务端口格式错误",
                    text=f'{port} - {error}\n已修改为默认值："6016"',
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_offline_translate_port(self):
        port: str = str(self.offline_translate_port.value())
        is_valid, error = ValueCheck.is_local_listenable_port(port)

        if is_valid:
            print(f"[green]{port}[/green]")
        else:
            print(f"[red]{port} - {error if error else '无效'}[/red]")

        if error:
            self.offline_translate_port.setValue(6017)
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="离线翻译服务端口格式错误",
                    text=f'{port} - {error}\n已修改为默认值："6017"',
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def init_ui(self):
        self.setPadding(64)
        self.setScrollMaximumWidth(1000)
        self.setScrollAlignment(Qt.AlignLeft)
        self.setTitle("服务端配置")

        # 创建控件组
        self.titled_widgets_group = SiTitledWidgetGroup(self)
        self.titled_widgets_group.setSpacing(32)
        self.titled_widgets_group.setAdjustWidgetsSize(True)

        # 保存配置按钮
        with self.titled_widgets_group as group:
            self.save = SiLongPressButtonRefactor(self)
            self.save.setSvgIcon(SiGlobal.siui.iconpack.get("ic_fluent_save_filled"))
            self.save.setIconSize(QSize(32, 32))
            self.save.setText("\t保存 服务端 配置")
            self.save.setFont(QFont("Microsoft YaHei", 16))
            self.save.setToolTip(
                "点击按钮进行数据格式检查\n长按以确认将数据写入配置文件\n保存配置后请手动重启 服务端/客户端 以加载新配置生效"
            )
            self.save.resize(420, 64)
            self.save_container = SiDenseVContainer(self)
            self.save_container.setAlignment(Qt.AlignCenter)
            self.save_container.addWidget(self.save)
            group.addWidget(self.save_container)

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
            # 只允许运行一次，禁止多开
            self.only_run_once = SiSwitch(self)
            self.only_run_once.setChecked(self.config["server"]["only_run_once"])
            self.only_run_once_linear_attaching = SiOptionCardLinear(self)
            self.only_run_once_linear_attaching.setTitle("禁止多开", "只允许运行一次")
            self.only_run_once_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_star_one_quarter_filled")
            )
            self.only_run_once_linear_attaching.addWidget(self.only_run_once)
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

            # 设置项
            self.general_container = SiDenseVContainer(self)
            self.general_container.setFixedWidth(700)
            self.general_container.setAdjustWidgetsSize(True)
            self.general_container.addWidget(self.addr_linear_attaching)
            self.general_container.addWidget(
                self.shrink_automatically_to_tray_linear_attaching
            )
            self.general_container.addWidget(self.only_run_once_linear_attaching)
            self.in_the_meantime_start_the_client_changed()
            self.general_container.addWidget(
                self.in_the_meantime_start_the_client_linear_attaching
            )
            group.addWidget(self.general_container)

        with self.titled_widgets_group as group:
            group.addTitle("语音识别")

            # 选择语音识别模型
            self.model = SiComboBox(self)
            self.model.resize(325, 32)
            self.model.addOption("Paraformer")
            self.model.addOption("Sensevoice")
            self.model.addOption("FunASR")
            self.model.menu().setShowIcon(False)
            if self.config["server"]["model"] == "Paraformer":
                self.model.menu().setIndex(0)
            elif self.config["server"]["model"] == "Sensevoice":
                self.model.menu().setIndex(1)
            else:
                self.model.menu().setIndex(2)
            self.model.valueChanged.connect(self.model_changed)
            self.model_linear_attaching = SiOptionCardLinear(self)
            self.model_linear_attaching.setTitle("语音识别模型")
            self.model_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_brain_circuit_regular")
            )
            self.model_linear_attaching.addWidget(self.model)

            # 是否启用 Fun-ASR-Nano-GGUF 模型 Vulkan 加速 GPU 推理
            self.vulkan_enable = SiSwitch(self)
            self.vulkan_enable.setChecked(self.config["server"]["vulkan_enable"])
            self.vulkan_enable_linear_attaching = SiOptionCardLinear(self)
            self.vulkan_enable_linear_attaching.setTitle(
                "是否启用 Fun-ASR-Nano-GGUF 模型 Vulkan 加速 GPU 推理"
            )
            self.vulkan_enable_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.vulkan_enable_linear_attaching.addWidget(self.vulkan_enable)

            # 是否强制 Fun-ASR-Nano-GGUF 模型 FP32 计算（如果 GPU 是 Intel 集显且出现精度溢出，可设为 true）
            self.vulkan_force_fp32 = SiSwitch(self)
            self.vulkan_force_fp32.setChecked(
                self.config["server"]["vulkan_force_fp32"]
            )
            self.vulkan_force_fp32_linear_attaching = SiOptionCardLinear(self)
            self.vulkan_force_fp32_linear_attaching.setTitle(
                "是否强制 Fun-ASR-Nano-GGUF 模型 FP32 计算"
            )
            self.vulkan_force_fp32_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.vulkan_force_fp32_linear_attaching.addWidget(self.vulkan_force_fp32)

            # 是否启用 Fun-ASR-Nano-GGUF 模型热词扩展功能
            # 将 .\hot-zh.txt 和 .\hot-en.txt 文件追加到 FunASR 模型热词列表中
            # .\models\Fun-ASR-Nano-GGUF\hot.txt
            # 不具有强制替换性，仅提供给 LLM 作为提示词
            self.expand_funasr_hotwords = SiSwitch(self)
            self.expand_funasr_hotwords.setChecked(
                self.config["server"]["expand_funasr_hotwords"]
            )
            self.expand_funasr_hotwords_linear_attaching = SiOptionCardLinear(self)
            self.expand_funasr_hotwords_linear_attaching.setTitle(
                "是否启用 Fun-ASR-Nano-GGUF 模型热词扩展功能"
            )
            self.expand_funasr_hotwords_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.expand_funasr_hotwords_linear_attaching.addWidget(
                self.expand_funasr_hotwords
            )

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

            # 是否将中文数字转为阿拉伯数字
            self.format_num = SiSwitch(self)
            self.format_num.setChecked(self.config["server"]["format_num"])
            self.format_num_linear_attaching = SiOptionCardLinear(self)
            self.format_num_linear_attaching.setTitle("将中文数字转为阿拉伯数字")
            self.format_num_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.format_num_linear_attaching.addWidget(self.format_num)

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

            # 是否调整中英之间的空格
            self.format_spell = SiSwitch(self)
            self.format_spell.setChecked(self.config["server"]["format_spell"])
            self.format_spell_linear_attaching = SiOptionCardLinear(self)
            self.format_spell_linear_attaching.setTitle("调整中英之间的空格")
            self.format_spell_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.format_spell_linear_attaching.addWidget(self.format_spell)

            # 设置项
            self.speech_recognition_container = SiDenseVContainer(self)
            self.speech_recognition_container.setFixedWidth(700)
            self.speech_recognition_container.setAdjustWidgetsSize(True)
            self.speech_recognition_container.addWidget(self.model_linear_attaching)
            self.speech_recognition_container.addWidget(
                self.vulkan_enable_linear_attaching
            )
            self.speech_recognition_container.addWidget(
                self.vulkan_force_fp32_linear_attaching
            )
            self.speech_recognition_container.addWidget(
                self.expand_funasr_hotwords_linear_attaching
            )
            self.speech_recognition_container.addWidget(
                self.speech_recognition_port_linear_attaching
            )
            self.speech_recognition_container.addWidget(
                self.format_num_linear_attaching
            )
            self.speech_recognition_container.addWidget(
                self.format_punc_linear_attaching
            )
            self.speech_recognition_container.addWidget(
                self.format_spell_linear_attaching
            )
            group.addWidget(self.speech_recognition_container)

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
            )  # # 离线翻译服务端口
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
            # 设置项
            self.translation_container = SiDenseVContainer(self)
            self.translation_container.setFixedWidth(700)
            self.translation_container.setAdjustWidgetsSize(True)
            self.translation_container.addWidget(
                self.start_online_translate_server_linear_attaching
            )
            self.translation_container.addWidget(
                self.start_offline_translate_server_linear_attaching
            )
            self.start_offline_translate_server_changed()
            self.translation_container.addWidget(
                self.offline_translate_port_linear_attaching
            )
            group.addWidget(self.translation_container)

        # 保存按钮
        # 添加页脚的空白以增加美观性
        self.titled_widgets_group.addPlaceholder(64)

        # 设置控件组为页面对象
        self.setAttachment(self.titled_widgets_group)

    def model_changed(self):
        if self.model.value_label.text() == "Paraformer":
            self.format_punc_linear_attaching.show()
            self.vulkan_enable_linear_attaching.hide()
            self.vulkan_force_fp32_linear_attaching.hide()
            self.expand_funasr_hotwords_linear_attaching.hide()
        elif self.model.value_label.text() == "Sensevoice":
            self.format_punc_linear_attaching.hide()
            self.vulkan_enable_linear_attaching.hide()
            self.vulkan_force_fp32_linear_attaching.hide()
            self.expand_funasr_hotwords_linear_attaching.hide()
        else:
            self.format_punc_linear_attaching.hide()
            self.vulkan_enable_linear_attaching.show()
            self.vulkan_force_fp32_linear_attaching.show()
            self.expand_funasr_hotwords_linear_attaching.show()

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
            self.config["server"]["vulkan_enable"] = self.vulkan_enable.isChecked()
            self.config["server"]["vulkan_force_fp32"] = (
                self.vulkan_force_fp32.isChecked()
            )
            self.config["server"]["expand_funasr_hotwords"] = (
                self.expand_funasr_hotwords.isChecked()
            )
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
                "vulkan_enable",
                clearly_type(self.config["server"]["vulkan_enable"]),
                str(self.config["server"]["vulkan_enable"]),
            )
            table.add_row(
                "vulkan_force_fp32",
                clearly_type(self.config["server"]["vulkan_force_fp32"]),
                str(self.config["server"]["vulkan_force_fp32"]),
            )
            table.add_row(
                "expand_funasr_hotwords",
                clearly_type(self.config["server"]["expand_funasr_hotwords"]),
                str(self.config["server"]["expand_funasr_hotwords"]),
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

        try:
            get_value_from_gui()
            print_config()
            write_toml(self.config, self.config_path)
            SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                "保存服务端配置成功！\n手动重启服务端以加载新配置。",
                msg_type=1,
                fold_after=2000,
            )
        except Exception as e:
            SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                f"保存服务端配置失败！\n错误信息：{e}",
                msg_type=4,
            )
