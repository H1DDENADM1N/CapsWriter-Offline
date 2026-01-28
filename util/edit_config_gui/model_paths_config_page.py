from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from rich import print
from rich.console import Console
from rich.table import Table
from siui.components import (
    SiDenseVContainer,
    SiTitledWidgetGroup,
)
from siui.components.button import (
    SiLongPressButtonRefactor,
)
from siui.components.page import SiPage
from siui.components.titled_widget_group import SiTitledWidgetGroup
from siui.components.widgets import (
    SiDenseVContainer,
)
from siui.core import SiGlobal

from util.edit_config_gui.clearly_type import clearly_type
from util.edit_config_gui.value_check import ValueCheck
from util.edit_config_gui.write_toml import write_toml

from .select_path import SelectPath


class ModelPathsConfigPage(SiPage):
    def __init__(self, config, config_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.config_path = config_path
        self.model_dir: str = self.config["model_paths"]["model_dir"]
        self.funasr_dir: str = self.config["model_paths"]["funasr_dir"]
        self.funasr_encoder_adaptor_path: str = self.config["model_paths"][
            "funasr_encoder_adaptor_path"
        ]
        self.funasr_ctc_path: str = self.config["model_paths"]["funasr_ctc_path"]
        self.funasr_llm_path: str = self.config["model_paths"]["funasr_llm_path"]
        self.funasr_tokens_path: str = self.config["model_paths"]["funasr_tokens_path"]
        self.funasr_hotwords_path: str = self.config["model_paths"][
            "funasr_hotwords_path"
        ]

        self.sensevoice_path: str = self.config["model_paths"]["sensevoice_path"]
        self.sensevoice_tokens_path: str = self.config["model_paths"][
            "sensevoice_tokens_path"
        ]
        self.paraformer_path: str = self.config["model_paths"]["paraformer_path"]
        self.paraformer_tokens_path: str = self.config["model_paths"][
            "paraformer_tokens_path"
        ]
        self.punc_model_dir: str = self.config["model_paths"]["punc_model_dir"]
        self.opus_mt_dir: str = self.config["model_paths"]["opus_mt_dir"]
        self.init_ui()
        self.model_dir_path_selector.pathSelected.connect(
            self.on_model_dir_path_selected
        )
        self.model_dir_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_model_dir_path_selected(
                self.model_dir_path_selector.path_input.lineEdit().text()
            )
        )
        self.funasr_dir_path_selector.pathSelected.connect(
            self.on_funasr_dir_path_selected
        )
        self.funasr_dir_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_funasr_dir_path_selected(
                self.funasr_dir_path_selector.path_input.lineEdit().text()
            )
        )
        self.funasr_encoder_adaptor_path_selector.pathSelected.connect(
            self.on_funasr_encoder_adaptor_path_selected
        )
        self.funasr_encoder_adaptor_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_funasr_encoder_adaptor_path_selected(
                self.funasr_encoder_adaptor_path_selector.path_input.lineEdit().text()
            )
        )
        self.funasr_ctc_path_selector.pathSelected.connect(
            self.on_funasr_ctc_path_selected
        )
        self.funasr_ctc_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_funasr_ctc_path_selected(
                self.funasr_ctc_path_selector.path_input.lineEdit().text()
            )
        )
        self.funasr_llm_path_selector.pathSelected.connect(
            self.on_funasr_llm_path_selected
        )
        self.funasr_llm_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_funasr_llm_path_selected(
                self.funasr_llm_path_selector.path_input.lineEdit().text()
            )
        )
        self.funasr_tokens_path_selector.pathSelected.connect(
            self.on_funasr_tokens_path_selected
        )
        self.funasr_tokens_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_funasr_tokens_path_selected(
                self.funasr_tokens_path_selector.path_input.lineEdit().text()
            )
        )
        self.funasr_hotwords_path_selector.pathSelected.connect(
            self.on_funasr_hotwords_path_selected
        )
        self.funasr_hotwords_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_funasr_hotwords_path_selected(
                self.funasr_hotwords_path_selector.path_input.lineEdit().text()
            )
        )
        self.sensevoice_path_selector.pathSelected.connect(
            self.on_sensevoice_path_selected
        )
        self.sensevoice_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_sensevoice_path_selected(
                self.sensevoice_path_selector.path_input.lineEdit().text()
            )
        )
        self.sensevoice_tokens_path_selector.pathSelected.connect(
            self.on_sensevoice_tokens_path_selected
        )
        self.sensevoice_tokens_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_sensevoice_tokens_path_selected(
                self.sensevoice_tokens_path_selector.path_input.lineEdit().text()
            )
        )
        self.paraformer_path_selector.pathSelected.connect(
            self.on_paraformer_path_selected
        )
        self.paraformer_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_paraformer_path_selected(
                self.paraformer_path_selector.path_input.lineEdit().text()
            )
        )
        self.paraformer_tokens_path_selector.pathSelected.connect(
            self.on_paraformer_tokens_path_selected
        )
        self.paraformer_tokens_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_paraformer_tokens_path_selected(
                self.paraformer_tokens_path_selector.path_input.lineEdit().text()
            )
        )
        self.punc_model_dir_path_selector.pathSelected.connect(
            self.on_punc_model_dir_path_selected
        )
        self.punc_model_dir_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_punc_model_dir_path_selected(
                self.punc_model_dir_path_selector.path_input.lineEdit().text()
            )
        )
        self.opus_mt_dir_path_selector.pathSelected.connect(
            self.on_opus_mt_dir_path_selected
        )
        self.opus_mt_dir_path_selector.path_input.lineEdit().editingFinished.connect(
            lambda: self.on_opus_mt_dir_path_selected(
                self.opus_mt_dir_path_selector.path_input.lineEdit().text()
            )
        )
        self.save.longPressed.connect(self.save_config)
        # 数据校验绑定
        self.save.clicked.connect(lambda: self.validate_on_model_dir_path(on_save=True))
        self.save.clicked.connect(
            lambda: self.validate_on_sensevoice_path(on_save=True)
        )
        self.save.clicked.connect(
            lambda: self.validate_on_sensevoice_tokens_path(on_save=True)
        )
        self.save.clicked.connect(
            lambda: self.validate_on_paraformer_path(on_save=True)
        )
        self.save.clicked.connect(
            lambda: self.validate_on_paraformer_tokens_path(on_save=True)
        )
        self.save.clicked.connect(
            lambda: self.validate_on_punc_model_dir_path(on_save=True)
        )
        self.save.clicked.connect(
            lambda: self.validate_on_opus_mt_dir_path(on_save=True)
        )

    def validate_on_model_dir_path(self, on_save: bool = False):
        if not on_save:
            if not self.model_dir:
                return
        else:
            if not self.model_dir:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="模型文件总目录路径 路径不可为空",
                        text="已恢复默认值：models",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.model_dir_path_selector.path_input.lineEdit().setText("models")
                self.model_dir = "models"
        is_valid, error = ValueCheck.is_dir_exist(self.model_dir)

        if is_valid:
            print(f"[green]{self.model_dir}[/green]")
        else:
            print(f"[red]{self.model_dir} - {error if error else '无效'}[/red]")

        if error:
            self.model_dir_path_selector.path_input.lineEdit().setText("models")
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="模型文件总目录路径 路径位置错误",
                    text=f"{self.model_dir} - {error}\n已恢复默认值：models",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_funasr_dir(self, on_save: bool = False):
        if not on_save:
            if not self.funasr_dir:
                return
        else:
            if not self.funasr_dir:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="FunASR 路径 模型位置错误",
                        text=f"{self.funasr_dir} - {error}\n已恢复默认值：models/Fun-ASR-Nano-GGUF",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.funasr_dir_path_selector.path_input.lineEdit().setText(
                    "models/Fun-ASR-Nano-GGUF"
                )
                self.funasr_dir = "models/Fun-ASR-Nano-GGUF"
        is_valid, error = ValueCheck.is_dir_exist(self.funasr_dir)

        if is_valid:
            print(f"[green]{self.funasr_dir}[/green]")
        else:
            print(f"[red]{self.funasr_dir} - {error if error else '无效'}[/red]")

        if error:
            self.funasr_dir_path_selector.path_input.lineEdit().setText(
                "models/Fun-ASR-Nano-GGUF"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="FunASR 路径 模型位置错误",
                    text=f"{self.funasr_dir} - {error}\n已恢复默认值：models/Fun-ASR-Nano-GGUF",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_funasr_encoder_adaptor_path(self, on_save: bool = False):
        if not on_save:
            if not self.funasr_encoder_adaptor_path:
                return
        else:
            if not self.funasr_encoder_adaptor_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="FunASR encoder_adaptor 模型路径 模型位置错误",
                        text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.funasr_encoder_adaptor_path_selector.path_input.lineEdit().setText(
                    "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx"
                )
                self.funasr_encoder_adaptor_path = "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx"
        is_valid, error = ValueCheck.is_file_exist(self.funasr_encoder_adaptor_path)

        if is_valid:
            print(f"[green]{self.funasr_encoder_adaptor_path}[/green]")
        else:
            print(
                f"[red]{self.funasr_encoder_adaptor_path} - {error if error else '无效'}[/red]"
            )

        if error:
            self.funasr_encoder_adaptor_path_selector.path_input.lineEdit().setText(
                "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="FunASR encoder_adaptor 模型路径 模型位置错误",
                    text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_funasr_ctc_path(self, on_save: bool = False):
        if not on_save:
            if not self.funasr_ctc_path:
                return
        else:
            if not self.funasr_ctc_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="FunASR CTC 快速预识别 模型位置错误",
                        text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-CTC.int8.onnx",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.funasr_ctc_path_selector.path_input.lineEdit().setText(
                    "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-CTC.int8.onnx"
                )
                self.funasr_ctc_path = (
                    "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-CTC.int8.onnx"
                )
        is_valid, error = ValueCheck.is_file_exist(self.funasr_ctc_path)

        if is_valid:
            print(f"[green]{self.funasr_ctc_path}[/green]")
        else:
            print(f"[red]{self.funasr_ctc_path} - {error if error else '无效'}[/red]")

        if error:
            self.funasr_ctc_path_selector.path_input.lineEdit().setText(
                "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-CTC.int8.onnx"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="FunASR CTC 快速预识别 模型位置错误",
                    text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-CTC.int8.onnx",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_funasr_llm_path(self, on_save: bool = False):
        if not on_save:
            if not self.funasr_llm_path:
                return
        else:
            if not self.funasr_llm_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="FunASR llm 模型路径 模型位置错误",
                        text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Decoder.q8_0.gguf",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.funasr_llm_path_selector.path_input.lineEdit().setText(
                    "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Decoder.q8_0.gguf"
                )
                self.funasr_llm_path = (
                    "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Decoder.q8_0.gguf"
                )
        is_valid, error = ValueCheck.is_file_exist(self.funasr_llm_path)

        if is_valid:
            print(f"[green]{self.funasr_llm_path}[/green]")
        else:
            print(f"[red]{self.funasr_llm_path} - {error if error else '无效'}[/red]")

        if error:
            self.funasr_llm_path_selector.path_input.lineEdit().setText(
                "models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Decoder.q8_0.gguf"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="FunASR llm 模型路径 模型位置错误",
                    text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Decoder.q8_0.gguf",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_funasr_tokens_path(self, on_save: bool = False):
        if not on_save:
            if not self.funasr_tokens_path:
                return
        else:
            if not self.funasr_tokens_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="FunASR tokens 路径 模型位置错误",
                        text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/tokens.txt",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.funasr_tokens_path_selector.path_input.lineEdit().setText(
                    "models/Fun-ASR-Nano-GGUF/model/tokens.txt"
                )
                self.funasr_tokens_path = "models/Fun-ASR-Nano-GGUF/model/tokens.txt"
        is_valid, error = ValueCheck.is_file_exist(self.funasr_tokens_path)

        if is_valid:
            print(f"[green]{self.funasr_tokens_path}[/green]")
        else:
            print(
                f"[red]{self.funasr_tokens_path} - {error if error else '无效'}[/red]"
            )

        if error:
            self.funasr_tokens_path_selector.path_input.lineEdit().setText(
                "models/Fun-ASR-Nano-GGUF/model/tokens.txt"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="FunASR tokens 路径 模型位置错误",
                    text="已恢复默认值：models/Fun-ASR-Nano-GGUF/model/tokens.txt",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_funasr_hotwords_path(self, on_save: bool = False):
        if not on_save:
            if not self.funasr_hotwords_path:
                return
        else:
            if not self.funasr_hotwords_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="FunASR 热词文件路径 模型位置错误",
                        text="已恢复默认值：models/Fun-ASR-Nano-GGUF/hot.txt",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.funasr_hotwords_path_selector.path_input.lineEdit().setText(
                    "models/Fun-ASR-Nano-GGUF/hot.txt"
                )
                self.funasr_hotwords_path = "models/Fun-ASR-Nano-GGUF/hot.txt"
        is_valid, error = ValueCheck.is_file_exist(self.funasr_hotwords_path)

        if is_valid:
            print(f"[green]{self.funasr_hotwords_path}[/green]")
        else:
            print(
                f"[red]{self.funasr_hotwords_path} - {error if error else '无效'}[/red]"
            )

        if error:
            self.funasr_hotwords_path_selector.path_input.lineEdit().setText(
                "models/Fun-ASR-Nano-GGUF/hot.txt"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="FunASR 热词文件路径 模型位置错误",
                    text="已恢复默认值：models/Fun-ASR-Nano-GGUF/hot.txt",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_sensevoice_path(self, on_save: bool = False):
        if not on_save:
            if not self.sensevoice_path:
                return
        else:
            if not self.sensevoice_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="SenseVoice 模型路径 路径不可为空",
                        text="已恢复默认值：models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.sensevoice_path_selector.path_input.lineEdit().setText(
                    "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
                )
                self.sensevoice_path = "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
        is_valid, error = ValueCheck.is_file_exist(self.sensevoice_path)

        if is_valid:
            print(f"[green]{self.sensevoice_path}[/green]")
        else:
            print(f"[red]{self.sensevoice_path} - {error if error else '无效'}[/red]")

        if error:
            self.sensevoice_path_selector.path_input.lineEdit().setText(
                "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="SenseVoice 模型路径 路径位置错误",
                    text=f"{self.sensevoice_path} - {error}\n已恢复默认值：models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_sensevoice_tokens_path(self, on_save: bool = False):
        if not on_save:
            if not self.sensevoice_tokens_path:
                return
        else:
            if not self.sensevoice_tokens_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="SenseVoice tokens 路径 路径不可为空",
                        text="已恢复默认值：models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.sensevoice_tokens_path_selector.path_input.lineEdit().setText(
                    "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"
                )
                self.sensevoice_tokens_path = "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"
        is_valid, error = ValueCheck.is_file_exist(self.sensevoice_tokens_path)

        if is_valid:
            print(f"[green]{self.sensevoice_tokens_path}[/green]")
        else:
            print(
                f"[red]{self.sensevoice_tokens_path} - {error if error else '无效'}[/red]"
            )

        if error:
            self.sensevoice_tokens_path_selector.path_input.lineEdit().setText(
                "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="SenseVoice tokens 路径 路径位置错误",
                    text=f"{self.sensevoice_tokens_path} - {error}\n已恢复默认值：models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_paraformer_path(self, on_save: bool = False):
        if not on_save:
            if not self.paraformer_path:
                return
        else:
            if not self.paraformer_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="Paraformer 模型路径 路径不可为空",
                        text="已恢复默认值：models/paraformer-offline-zh/model.int8.onnx",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.paraformer_path_selector.path_input.lineEdit().setText(
                    "models/paraformer-offline-zh/model.int8.onnx"
                )
                self.paraformer_path = "models/paraformer-offline-zh/model.int8.onnx"
        is_valid, error = ValueCheck.is_file_exist(self.paraformer_path)

        if is_valid:
            print(f"[green]{self.paraformer_path}[/green]")
        else:
            print(f"[red]{self.paraformer_path} - {error if error else '无效'}[/red]")

        if error:
            self.paraformer_path_selector.path_input.lineEdit().setText(
                "models/paraformer-offline-zh/model.int8.onnx"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="Paraformer 模型路径 路径位置错误",
                    text=f"{self.paraformer_path} - {error}\n已恢复默认值：models/paraformer-offline-zh/model.int8.onnx",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_paraformer_tokens_path(self, on_save: bool = False):
        if not on_save:
            if not self.paraformer_tokens_path:
                return
        else:
            if not self.paraformer_tokens_path:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="Paraformer tokens 路径 路径不可为空",
                        text="已恢复默认值：models/paraformer-offline-zh/tokens.txt",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.paraformer_tokens_path_selector.path_input.lineEdit().setText(
                    "models/paraformer-offline-zh/tokens.txt"
                )
                self.paraformer_tokens_path = "models/paraformer-offline-zh/tokens.txt"
        is_valid, error = ValueCheck.is_file_exist(self.paraformer_tokens_path)

        if is_valid:
            print(f"[green]{self.paraformer_tokens_path}[/green]")
        else:
            print(
                f"[red]{self.paraformer_tokens_path} - {error if error else '无效'}[/red]"
            )

        if error:
            self.paraformer_tokens_path_selector.path_input.lineEdit().setText(
                "models/paraformer-offline-zh/tokens.txt"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="Paraformer tokens 路径 路径位置错误",
                    text=f"{self.paraformer_tokens_path} - {error}\n已恢复默认值：models/paraformer-offline-zh/tokens.txt",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_punc_model_dir_path(self, on_save: bool = False):
        if not on_save:
            if not self.punc_model_dir:
                return
        else:
            if not self.punc_model_dir:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="标点模型目录路径 路径不可为空",
                        text="已恢复默认值：models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.punc_model_dir_path_selector.path_input.lineEdit().setText(
                    "models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"
                )
                self.punc_model_dir = "models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"
        is_valid, error = ValueCheck.is_dir_exist(self.punc_model_dir)

        if is_valid:
            print(f"[green]{self.punc_model_dir}[/green]")
        else:
            print(f"[red]{self.punc_model_dir} - {error if error else '无效'}[/red]")

        if error:
            self.punc_model_dir_path_selector.path_input.lineEdit().setText(
                "models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="标点模型目录路径 路径位置错误",
                    text=f"{self.punc_model_dir} - {error}\n已恢复默认值：models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12",
                    msg_type=3,
                    icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                    fold_after=5000,
                )
            except ValueError:
                pass

    def validate_on_opus_mt_dir_path(self, on_save: bool = False):
        if not on_save:
            if not self.opus_mt_dir:
                return
        else:
            if not self.opus_mt_dir:
                try:
                    SiGlobal.siui.windows[
                        "MAIN_WINDOW"
                    ].LayerRightMessageSidebar().send(
                        title="Helsinki NLP--opus-mt-zh-en 翻译模型目录路径 路径不可为空",
                        text="已恢复默认值：models/Helsinki-NLP--opus-mt-zh-en",
                        msg_type=3,
                        icon=SiGlobal.siui.iconpack.get("ic_fluent_warning_regular"),
                        fold_after=5000,
                    )
                except ValueError:
                    pass
                self.opus_mt_dir_path_selector.path_input.lineEdit().setText(
                    "models/Helsinki-NLP--opus-mt-zh-en"
                )
                self.opus_mt_dir = "models/Helsinki-NLP--opus-mt-zh-en"
        is_valid, error = ValueCheck.is_dir_exist(self.opus_mt_dir)

        if is_valid:
            print(f"[green]{self.opus_mt_dir}[/green]")
        else:
            print(f"[red]{self.opus_mt_dir} - {error if error else '无效'}[/red]")

        if error:
            self.opus_mt_dir_path_selector.path_input.lineEdit().setText(
                "models/Helsinki-NLP--opus-mt-zh-en"
            )
            try:
                SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                    title="Helsinki NLP--opus-mt-zh-en 翻译模型目录路径 路径位置错误",
                    text=f"{self.opus_mt_dir} - {error}\n已恢复默认值：models/Helsinki-NLP--opus-mt-zh-en",
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
        self.setTitle("模型路径配置")

        # 创建控件组
        self.titled_widgets_group = SiTitledWidgetGroup(self)
        self.titled_widgets_group.setSpacing(32)
        self.titled_widgets_group.setAdjustWidgetsSize(True)

        # 保存配置按钮
        with self.titled_widgets_group as group:
            self.save = SiLongPressButtonRefactor(self)
            self.save.setSvgIcon(SiGlobal.siui.iconpack.get("ic_fluent_save_filled"))
            self.save.setIconSize(QSize(32, 32))
            self.save.setText("\t保存 模型路径 配置")
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

            # 模型文件目录
            self.model_dir_path_selector = SelectPath(
                self,
                title="模型文件总目录路径",
                label_text='默认值："models"\n本服务端需要 SenseVoice 模型、Paraformer语音模型、Helsinki-NLP--opus-mt-zh-en翻译模型\n请下载模型并放置到总目录对应的路径',
                default_path=self.config["model_paths"]["model_dir"],
                file_filter="",
                mode="directory",
            )
            self.general_container = SiDenseVContainer(self)
            self.general_container.setFixedWidth(700)
            self.general_container.setAdjustWidgetsSize(True)
            self.general_container.addWidget(self.model_dir_path_selector)
            group.addWidget(self.general_container)

        with self.titled_widgets_group as group:
            group.addTitle("FunASR 语音模型")

            # FunASR 路径
            self.funasr_dir_path_selector = SelectPath(
                self,
                title="FunASR 路径",
                label_text='默认值："models/Fun-ASR-Nano-GGUF"',
                default_path=self.config["model_paths"]["funasr_dir"],
                file_filter="",
                mode="directory",
            )
            # FunASR encoder_adaptor 模型路径
            self.funasr_encoder_adaptor_path_selector = SelectPath(
                self,
                title="FunASR encoder_adaptor 模型路径",
                label_text='默认值："models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx"',
                default_path=self.config["model_paths"]["funasr_encoder_adaptor_path"],
                file_filter="*.onnx",
                mode="file",
            )
            # CTC 快速预识别
            self.funasr_ctc_path_selector = SelectPath(
                self,
                title="CTC 快速预识别 模型路径",
                label_text='默认值："models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-CTC.fp32.onnx"',
                default_path=self.config["model_paths"]["funasr_ctc_path"],
                file_filter="*.onnx",
                mode="file",
            )
            # FunASR llm 模型路径
            self.funasr_llm_path_selector = SelectPath(
                self,
                title="FunASR llm 模型路径",
                label_text='默认值："models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Decoder.q8_0.gguf"',
                default_path=self.config["model_paths"]["funasr_llm_path"],
                file_filter="*.gguf",
                mode="file",
            )
            # FunASR tokens 路径
            self.funasr_tokens_path_selector = SelectPath(
                self,
                title="FunASR tokens 模型路径",
                label_text='默认值："models/Fun-ASR-Nano-GGUF/model/Fun-ASR-Nano-Tokens.txt"',
                default_path=self.config["model_paths"]["funasr_tokens_path"],
                file_filter="*.txt",
            )
            # FunASR 热词文件路径
            self.funasr_hotwords_path_selector = SelectPath(
                self,
                title="FunASR 热词文件路径",
                label_text='默认值："models/Fun-ASR-Nano-GGUF/hot.txt"',
                default_path=self.config["model_paths"]["funasr_hotwords_path"],
                file_filter="*.txt",
            )
            self.funasr_container = SiDenseVContainer(self)
            self.funasr_container.setFixedWidth(700)
            self.funasr_container.setAdjustWidgetsSize(True)
            self.funasr_container.addWidget(self.funasr_dir_path_selector)
            self.funasr_container.addWidget(self.funasr_encoder_adaptor_path_selector)
            self.funasr_container.addWidget(self.funasr_ctc_path_selector)
            self.funasr_container.addWidget(self.funasr_llm_path_selector)
            self.funasr_container.addWidget(self.funasr_tokens_path_selector)
            self.funasr_container.addWidget(self.funasr_hotwords_path_selector)
            group.addWidget(self.funasr_container)

        with self.titled_widgets_group as group:
            group.addTitle("SenseVoice 语音模型")

            # SenseVoice 模型路径
            self.sensevoice_path_selector = SelectPath(
                self,
                title="SenseVoice 模型路径",
                label_text='默认值："models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"',
                default_path=self.config["model_paths"]["sensevoice_path"],
                file_filter="*.onnx",
                mode="file",
            )

            # SenseVoice tokens 路径
            self.sensevoice_tokens_path_selector = SelectPath(
                self,
                title="SenseVoice tokens 路径",
                label_text='默认值："models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"',
                default_path=self.config["model_paths"]["sensevoice_tokens_path"],
                file_filter="*.txt",
                mode="file",
            )
            self.sensevoice_container = SiDenseVContainer(self)
            self.sensevoice_container.setFixedWidth(700)
            self.sensevoice_container.setAdjustWidgetsSize(True)
            self.sensevoice_container.addWidget(self.sensevoice_path_selector)
            self.sensevoice_container.addWidget(self.sensevoice_tokens_path_selector)
            group.addWidget(self.sensevoice_container)

        with self.titled_widgets_group as group:
            group.addTitle("Paraformer 语音模型")

            # Paraformer 模型路径
            self.paraformer_path_selector = SelectPath(
                self,
                title="Paraformer 模型路径",
                label_text='默认值："models/paraformer-offline-zh/model.int8.onnx"',
                default_path=self.config["model_paths"]["paraformer_path"],
                file_filter="*.onnx",
                mode="file",
            )

            # Paraformer tokens 路径
            self.paraformer_tokens_path_selector = SelectPath(
                self,
                title="Paraformer tokens 路径",
                label_text='默认值："models/paraformer-offline-zh/tokens.txt"',
                default_path=self.config["model_paths"]["paraformer_tokens_path"],
                file_filter="*.txt",
                mode="file",
            )

            # 标点模型目录
            self.punc_model_dir_path_selector = SelectPath(
                self,
                title="标点模型目录路径",
                label_text='默认值："models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"',
                default_path=self.config["model_paths"]["punc_model_dir"],
                file_filter="",
                mode="directory",
            )
            self.paraformer_container = SiDenseVContainer(self)
            self.paraformer_container.setFixedWidth(700)
            self.paraformer_container.setAdjustWidgetsSize(True)
            self.paraformer_container.addWidget(self.paraformer_path_selector)
            self.paraformer_container.addWidget(self.paraformer_tokens_path_selector)
            self.paraformer_container.addWidget(self.punc_model_dir_path_selector)
            group.addWidget(self.paraformer_container)

        with self.titled_widgets_group as group:
            group.addTitle("Helsinki NLP--opus-mt-zh-en 离线翻译模型")

            # 离线翻译模型目录
            self.opus_mt_dir_path_selector = SelectPath(
                self,
                title="离线翻译模型目录路径",
                label_text='默认值："models/Helsinki-NLP--opus-mt-zh-en"',
                default_path=self.config["model_paths"]["opus_mt_dir"],
                file_filter="",
                mode="directory",
            )
            self.opus_container = SiDenseVContainer(self)
            self.opus_container.setFixedWidth(700)
            self.opus_container.setAdjustWidgetsSize(True)
            self.opus_container.addWidget(self.opus_mt_dir_path_selector)
            group.addWidget(self.opus_container)

        # 添加页脚的空白以增加美观性
        self.titled_widgets_group.addPlaceholder(64)

        # 设置控件组为页面对象
        self.setAttachment(self.titled_widgets_group)

    def on_model_dir_path_selected(self, path: str):
        self.model_dir = path
        print(f"model_dir path selected: {self.model_dir}")
        self.validate_on_model_dir_path()

    def on_funasr_dir_path_selected(self, path: str):
        self.funasr_dir = path
        print(f"funasr_dir selected: {self.funasr_dir}")
        self.validate_on_funasr_dir()

    def on_funasr_encoder_adaptor_path_selected(self, path: str):
        self.funasr_encoder_adaptor_path = path
        print(
            f"funasr_encoder_adaptor_path selected: {self.funasr_encoder_adaptor_path}"
        )
        self.validate_on_funasr_encoder_adaptor_path()

    def on_funasr_ctc_path_selected(self, path: str):
        self.funasr_ctc_path = path
        print(f"funasr_ctc_path selected: {self.funasr_ctc_path}")
        self.validate_on_funasr_ctc_path()

    def on_funasr_llm_path_selected(self, path: str):
        self.funasr_llm_path = path
        print(f"funasr_llm_path selected: {self.funasr_llm_path}")
        self.validate_on_funasr_llm_path()

    def on_funasr_tokens_path_selected(self, path: str):
        self.funasr_tokens_path = path
        print(f"funasr_tokens_path selected: {self.funasr_tokens_path}")
        self.validate_on_funasr_tokens_path()

    def on_funasr_hotwords_path_selected(self, path: str):
        self.funasr_hotwords_path = path
        print(f"funasr_hotwords_path selected: {self.funasr_hotwords_path}")
        self.validate_on_funasr_hotwords_path()

    def on_sensevoice_path_selected(self, path: str):
        self.sensevoice_path = path
        print(f"sensevoice_path selected: {self.sensevoice_path}")
        self.validate_on_sensevoice_path()

    def on_sensevoice_tokens_path_selected(self, path: str):
        self.sensevoice_tokens_path = path
        print(f"sensevoice_tokens_path selected: {self.sensevoice_tokens_path}")
        self.validate_on_sensevoice_tokens_path()

    def on_paraformer_path_selected(self, path: str):
        self.paraformer_path = path
        print(f"paraformer_path selected: {self.paraformer_path}")
        self.validate_on_paraformer_path()

    def on_paraformer_tokens_path_selected(self, path: str):
        self.paraformer_tokens_path = path
        print(f"paraformer_tokens_path selected: {self.paraformer_tokens_path}")
        self.validate_on_paraformer_tokens_path()

    def on_punc_model_dir_path_selected(self, path: str):
        self.punc_model_dir = path
        print(f"punc_model_dir selected: {self.punc_model_dir}")
        self.validate_on_punc_model_dir_path()

    def on_opus_mt_dir_path_selected(self, path: str):
        self.opus_mt_dir = path
        print(f"opus_mt_dir selected: {self.opus_mt_dir}")
        self.validate_on_opus_mt_dir_path()

    def save_config(self):
        def get_value_from_gui():
            self.config["model_paths"]["model_dir"] = self.model_dir
            self.config["model_paths"]["funasr_dir"] = self.funasr_dir
            self.config["model_paths"]["funasr_encoder_adaptor_path"] = (
                self.funasr_encoder_adaptor_path
            )
            self.config["model_paths"]["funasr_ctc_path"] = self.funasr_ctc_path
            self.config["model_paths"]["funasr_llm_path"] = self.funasr_llm_path
            self.config["model_paths"]["funasr_tokens_path"] = self.funasr_tokens_path
            self.config["model_paths"]["funasr_hotwords_path"] = (
                self.funasr_hotwords_path
            )
            self.config["model_paths"]["sensevoice_path"] = self.sensevoice_path
            self.config["model_paths"]["sensevoice_tokens_path"] = (
                self.sensevoice_tokens_path
            )
            self.config["model_paths"]["paraformer_path"] = self.paraformer_path
            self.config["model_paths"]["paraformer_tokens_path"] = (
                self.paraformer_tokens_path
            )
            self.config["model_paths"]["punc_model_dir"] = self.punc_model_dir
            self.config["model_paths"]["opus_mt_dir"] = self.opus_mt_dir

        def print_config():
            console = Console()
            table = Table(title="保存 模型路径配置")
            table.add_column("属性名", style="cyan")
            table.add_column("类型", style="magenta")
            table.add_column("值", style="green")
            table.add_row(
                "model_dir",
                clearly_type(self.config["model_paths"]["model_dir"]),
                str(self.config["model_paths"]["model_dir"]),
            )
            table.add_row(
                "funasr_dir",
                clearly_type(self.config["model_paths"]["funasr_dir"]),
                str(self.config["model_paths"]["funasr_dir"]),
            )
            table.add_row(
                "funasr_encoder_adaptor_path",
                clearly_type(self.config["model_paths"]["funasr_encoder_adaptor_path"]),
                str(self.config["model_paths"]["funasr_encoder_adaptor_path"]),
            )
            table.add_row(
                "funasr_ctc_path",
                clearly_type(self.config["model_paths"]["funasr_ctc_path"]),
                str(self.config["model_paths"]["funasr_ctc_path"]),
            )
            table.add_row(
                "funasr_llm_path",
                clearly_type(self.config["model_paths"]["funasr_llm_path"]),
                str(self.config["model_paths"]["funasr_llm_path"]),
            )
            table.add_row(
                "funasr_tokens_path",
                clearly_type(self.config["model_paths"]["funasr_tokens_path"]),
                str(self.config["model_paths"]["funasr_tokens_path"]),
            )
            table.add_row(
                "funasr_hotwords_path",
                clearly_type(self.config["model_paths"]["funasr_hotwords_path"]),
                str(self.config["model_paths"]["funasr_hotwords_path"]),
            )
            table.add_row(
                "sensevoice_path",
                clearly_type(self.config["model_paths"]["sensevoice_path"]),
                str(self.config["model_paths"]["sensevoice_path"]),
            )
            table.add_row(
                "sensevoice_tokens_path",
                clearly_type(self.config["model_paths"]["sensevoice_tokens_path"]),
                str(self.config["model_paths"]["sensevoice_tokens_path"]),
            )
            table.add_row(
                "paraformer_path",
                clearly_type(self.config["model_paths"]["paraformer_path"]),
                str(self.config["model_paths"]["paraformer_path"]),
            )
            table.add_row(
                "paraformer_tokens_path",
                clearly_type(self.config["model_paths"]["paraformer_tokens_path"]),
                str(self.config["model_paths"]["paraformer_tokens_path"]),
            )
            table.add_row(
                "punc_model_dir",
                clearly_type(self.config["model_paths"]["punc_model_dir"]),
                str(self.config["model_paths"]["punc_model_dir"]),
            )
            table.add_row(
                "opus_mt_dir",
                clearly_type(self.config["model_paths"]["opus_mt_dir"]),
                str(self.config["model_paths"]["opus_mt_dir"]),
            )
            console.print(table)

        try:
            self.save.clicked.emit()
            get_value_from_gui()
            print_config()
            write_toml(self.config, self.config_path)
            SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                "保存 模型路径 配置成功！\n手动重启服务端以加载新配置。",
                msg_type=1,
                fold_after=2000,
            )
        except Exception as e:
            SiGlobal.siui.windows["MAIN_WINDOW"].LayerRightMessageSidebar().send(
                f"保存 模型路径 配置失败！\n错误信息：{e}",
                msg_type=4,
            )
