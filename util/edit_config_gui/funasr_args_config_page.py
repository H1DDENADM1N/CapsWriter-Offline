from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from rich.console import Console
from rich.table import Table
from siui.components import (
    SiDenseVContainer,
    SiTitledWidgetGroup,
)
from siui.components.button import (
    SiLongPressButtonRefactor,
)
from siui.components.option_card import SiOptionCardLinear
from siui.components.page import SiPage
from siui.components.spinbox.spinbox import SiDoubleSpinBox, SiIntSpinBox
from siui.components.titled_widget_group import SiTitledWidgetGroup
from siui.components.widgets import (
    SiDenseVContainer,
    SiSwitch,
)
from siui.core import SiGlobal

from util.edit_config_gui.clearly_type import clearly_type
from util.edit_config_gui.write_toml import write_toml

from .set_default_button import SetDefaultButton


class FunASRArgsConfigPage(SiPage):
    def __init__(self, config, config_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.config_path = config_path
        self.init_ui()
        self.n_threads_set_default.clicked.connect(lambda: self.n_threads.setValue(0))
        self.n_predict_set_default.clicked.connect(lambda: self.n_predict.setValue(512))
        self.similar_threshold_set_default.clicked.connect(
            lambda: self.similar_threshold.setValue(0.6)
        )
        self.max_hotwords_set_default.clicked.connect(
            lambda: self.max_hotwords.setValue(20)
        )
        self.save.longPressed.connect(self.save_config)

    def init_ui(self):
        self.setPadding(64)
        self.setScrollMaximumWidth(1000)
        self.setScrollAlignment(Qt.AlignLeft)
        self.setTitle("FunASR 语音识别模型参数配置")

        # 创建控件组
        self.titled_widgets_group = SiTitledWidgetGroup(self)
        self.titled_widgets_group.setSpacing(32)
        self.titled_widgets_group.setAdjustWidgetsSize(True)

        # 保存配置按钮
        with self.titled_widgets_group as group:
            self.save = SiLongPressButtonRefactor(self)
            self.save.setSvgIcon(SiGlobal.siui.iconpack.get("ic_fluent_save_filled"))
            self.save.setIconSize(QSize(32, 32))
            self.save.setText("\t保存 FunASR 配置")
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

            # enable_ctc
            self.enable_ctc = SiSwitch(self)
            self.enable_ctc.setChecked(self.config["funasr_args"]["enable_ctc"])
            self.enable_ctc_linear_attaching = SiOptionCardLinear(self)
            self.enable_ctc_linear_attaching.setTitle("是否启用 CTC 快速预识别")
            self.enable_ctc_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_checkmark_circle_regular")
            )
            self.enable_ctc_linear_attaching.addWidget(self.enable_ctc)

            # n_predict
            self.n_predict = SiIntSpinBox(self)
            self.n_predict.resize(256, 32)
            self.n_predict.setMinimum(1)
            self.n_predict.setMaximum(2048)
            self.n_predict.setValue(self.config["funasr_args"]["n_predict"])
            self.n_predict_set_default = SetDefaultButton(self)
            self.n_predict_linear_attaching = SiOptionCardLinear(self)
            self.n_predict_linear_attaching.setTitle(
                "LLM 最大生成 token 数", '默认值："512"'
            )
            self.n_predict_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.n_predict_linear_attaching.addWidget(self.n_predict_set_default)
            self.n_predict_linear_attaching.addWidget(self.n_predict)

            # n_threads
            self.n_threads = SiIntSpinBox(self)
            self.n_threads.resize(256, 32)
            self.n_threads.setMinimum(0)
            self.n_threads.setMaximum(32)
            self.n_threads.setValue(self.config["funasr_args"]["n_threads"])
            self.n_threads_set_default = SetDefaultButton(self)
            self.n_threads_linear_attaching = SiOptionCardLinear(self)
            self.n_threads_linear_attaching.setTitle("线程数", '默认值："0"（自动）')
            self.n_threads_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.n_threads_linear_attaching.addWidget(self.n_threads_set_default)
            self.n_threads_linear_attaching.addWidget(self.n_threads)

            # similar_threshold
            self.similar_threshold = SiDoubleSpinBox(self)
            self.similar_threshold.resize(256, 32)
            self.similar_threshold.setMinimum(0.3)
            self.similar_threshold.setMaximum(1.0)
            self.similar_threshold.setSingleStep(0.1)
            self.similar_threshold.setValue(
                self.config["funasr_args"]["similar_threshold"]
            )
            self.similar_threshold_set_default = SetDefaultButton(self)
            self.similar_threshold_linear_attaching = SiOptionCardLinear(self)
            self.similar_threshold_linear_attaching.setTitle(
                "热词相似度阈值", '默认值："0.6'
            )
            self.similar_threshold_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.similar_threshold_linear_attaching.addWidget(
                self.similar_threshold_set_default
            )
            self.similar_threshold_linear_attaching.addWidget(self.similar_threshold)

            # max_hotwords
            self.max_hotwords = SiIntSpinBox(self)
            self.max_hotwords.resize(256, 32)
            self.max_hotwords.setMinimum(1)
            self.max_hotwords.setMaximum(100)
            self.max_hotwords.setValue(self.config["funasr_args"]["max_hotwords"])
            self.max_hotwords_set_default = SetDefaultButton(self)
            self.max_hotwords_linear_attaching = SiOptionCardLinear(self)
            self.max_hotwords_linear_attaching.setTitle(
                "每次替换的最大热词数", '默认值："20"'
            )
            self.max_hotwords_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.max_hotwords_linear_attaching.addWidget(self.max_hotwords_set_default)
            self.max_hotwords_linear_attaching.addWidget(self.max_hotwords)

            # 是否启用 DirectML 加速 GPU 推理
            self.directml_enable = SiSwitch(self)
            self.directml_enable.setChecked(
                self.config["funasr_args"]["directml_enable"]
            )
            self.directml_enable_linear_attaching = SiOptionCardLinear(self)
            self.directml_enable_linear_attaching.setTitle(
                "是否启用 DirectML 加速 GPU 推理",
                "默认禁用，兼顾 AMD 显卡 用户\n建议非 AMD 显卡 用户自行手动启用",
            )
            self.directml_enable_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.directml_enable_linear_attaching.addWidget(self.directml_enable)

            # 是否启用 Vulkan 加速 GPU 推理
            self.vulkan_enable = SiSwitch(self)
            self.vulkan_enable.setChecked(self.config["funasr_args"]["vulkan_enable"])
            self.vulkan_enable_linear_attaching = SiOptionCardLinear(self)
            self.vulkan_enable_linear_attaching.setTitle(
                "是否启用 Vulkan 加速 GPU 推理"
            )
            self.vulkan_enable_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.vulkan_enable_linear_attaching.addWidget(self.vulkan_enable)

            # 是否强制 FP32 计算（如果 GPU 是 Intel 集显且出现精度溢出，可设为 true）
            self.vulkan_force_fp32 = SiSwitch(self)
            self.vulkan_force_fp32.setChecked(
                self.config["funasr_args"]["vulkan_force_fp32"]
            )
            self.vulkan_force_fp32_linear_attaching = SiOptionCardLinear(self)
            self.vulkan_force_fp32_linear_attaching.setTitle("是否强制 FP32 计算")
            self.vulkan_force_fp32_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_settings_light")
            )
            self.vulkan_force_fp32_linear_attaching.addWidget(self.vulkan_force_fp32)

            # verbose
            self.verbose = SiSwitch(self)
            self.verbose.setChecked(self.config["funasr_args"]["verbose"])
            self.verbose_linear_attaching = SiOptionCardLinear(self)
            self.verbose_linear_attaching.setTitle("是否输出详细日志")
            self.verbose_linear_attaching.load(
                SiGlobal.siui.iconpack.get("ic_fluent_bug_regular")
            )
            self.verbose_linear_attaching.addWidget(self.verbose)

            # 参数设置项容器
            self.params_container = SiDenseVContainer(self)
            self.params_container.setFixedWidth(700)
            self.params_container.setAdjustWidgetsSize(True)
            self.params_container.addWidget(self.enable_ctc_linear_attaching)
            self.params_container.addWidget(self.n_predict_linear_attaching)
            self.params_container.addWidget(self.n_threads_linear_attaching)
            self.params_container.addWidget(self.similar_threshold_linear_attaching)
            self.params_container.addWidget(self.max_hotwords_linear_attaching)
            self.params_container.addWidget(self.directml_enable_linear_attaching)
            self.params_container.addWidget(self.vulkan_enable_linear_attaching)
            self.params_container.addWidget(self.vulkan_force_fp32_linear_attaching)
            self.params_container.addWidget(self.verbose_linear_attaching)

            group.addWidget(self.params_container)

        # 添加页脚的空白以增加美观性
        self.titled_widgets_group.addPlaceholder(64)

        # 设置控件组为页面对象
        self.setAttachment(self.titled_widgets_group)

    def save_config(self):
        def get_value_from_gui():
            self.config["funasr_args"]["enable_ctc"] = self.enable_ctc.isChecked()
            self.config["funasr_args"]["n_predict"] = self.n_predict.value()
            self.config["funasr_args"]["n_threads"] = self.n_threads.value()
            self.config["funasr_args"]["similar_threshold"] = (
                self.similar_threshold.value()
            )
            self.config["funasr_args"]["max_hotwords"] = self.max_hotwords.value()
            self.config["funasr_args"]["directml_enable"] = (
                self.directml_enable.isChecked()
            )
            self.config["funasr_args"]["vulkan_enable"] = self.vulkan_enable.isChecked()
            self.config["funasr_args"]["vulkan_force_fp32"] = (
                self.vulkan_force_fp32.isChecked()
            )
            self.config["funasr_args"]["verbose"] = self.verbose.isChecked()

        def print_config():
            console = Console()
            table = Table(title="保存 FunASR 语音识别模型参数配置")
            table.add_column("属性名", style="cyan")
            table.add_column("类型", style="magenta")
            table.add_column("值", style="green")
            table.add_row(
                "enable_ctc",
                clearly_type(self.config["funasr_args"]["enable_ctc"]),
                str(self.config["funasr_args"]["enable_ctc"]),
            )
            table.add_row(
                "n_predict",
                clearly_type(self.config["funasr_args"]["n_predict"]),
                str(self.config["funasr_args"]["n_predict"]),
            )
            table.add_row(
                "n_threads",
                clearly_type(self.config["funasr_args"]["n_threads"]),
                str(self.config["funasr_args"]["n_threads"]),
            )
            table.add_row(
                "similar_threshold",
                clearly_type(self.config["funasr_args"]["similar_threshold"]),
                str(self.config["funasr_args"]["similar_threshold"]),
            )
            table.add_row(
                "max_hotwords",
                clearly_type(self.config["funasr_args"]["max_hotwords"]),
                str(self.config["funasr_args"]["max_hotwords"]),
            )
            table.add_row(
                "directml_enable",
                clearly_type(self.config["funasr_args"]["directml_enable"]),
                str(self.config["funasr_args"]["directml_enable"]),
            )
            table.add_row(
                "vulkan_enable",
                clearly_type(self.config["funasr_args"]["vulkan_enable"]),
                str(self.config["funasr_args"]["vulkan_enable"]),
            )
            table.add_row(
                "vulkan_force_fp32",
                clearly_type(self.config["funasr_args"]["vulkan_force_fp32"]),
                str(self.config["funasr_args"]["vulkan_force_fp32"]),
            )
            table.add_row(
                "verbose",
                clearly_type(self.config["funasr_args"]["verbose"]),
                str(self.config["funasr_args"]["verbose"]),
            )
            console.print(table)

        try:
            get_value_from_gui()
            print_config()
            write_toml(self.config, self.config_path)
            SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                "保存 FunASR 配置成功！\n手动重启服务端以加载新配置。",
                msg_type=1,
                fold_after=2000,
            )
        except Exception as e:
            SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                f"保存 FunASR 配置失败！\n错误信息：{e}",
                msg_type=4,
            )
