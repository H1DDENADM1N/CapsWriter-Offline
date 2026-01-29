import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
)
from siui.core import SiGlobal
from siui.templates.application.application import SiliconApplication
from tomlkit import parse

from util.edit_config_gui.about_page import AboutPage
from util.edit_config_gui.client_config_page import ClientConfigPage
from util.edit_config_gui.deeplx_config_page import DeeplxConfigPage
from util.edit_config_gui.funasr_args_config_page import FunASRArgsConfigPage
from util.edit_config_gui.libretranslate_config_page import LibretranslateConfigPage
from util.edit_config_gui.model_paths_config_page import ModelPathsConfigPage
from util.edit_config_gui.paraformer_args_config_page import ParaformerArgsConfigPage
from util.edit_config_gui.sensevoice_args_config_page import SenseVoiceArgsConfigPage
from util.edit_config_gui.server_config_page import ServerConfigPage


class ConfigEditor(SiliconApplication):
    def __init__(self, config_path: Path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_path: Path = config_path
        self.config = self.load_config()
        self.init_ui()
        SiGlobal.siui.reloadAllWindowsStyleSheet()

    def init_ui(self):
        screen_geo = QGuiApplication.primaryScreen().geometry()
        self.setMinimumSize(888, 360)
        self.resize(888, 950)
        self.move(
            (screen_geo.width() - self.width()) // 2,
            (screen_geo.height() - self.height()) // 2,
        )
        self.layerMain().setTitle("配置编辑器")
        self.setWindowTitle("配置编辑器")
        self.setWindowIcon(QIcon("assets/icon/config-icon.ico"))
        self.layerMain().app_icon.load("assets/icon/config-icon.ico")

        # 添加页面
        self.layerMain().addPage(
            ServerConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_server_filled"),
            hint="服务端配置",
            side="top",
        )
        self.layerMain().addPage(
            ClientConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_person_filled"),
            hint="客户端配置",
            side="top",
        )
        self.layerMain().addPage(
            LibretranslateConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_translate_filled"),
            hint="Libretranslate 离/在线翻译配置",
            side="top",
        )
        self.layerMain().addPage(
            DeeplxConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_translate_filled"),
            hint="在线翻译 DeepLX 翻译配置",
            side="top",
        )
        self.layerMain().addPage(
            ModelPathsConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_folder_filled"),
            hint="模型路径配置",
            side="top",
        )
        self.layerMain().addPage(
            FunASRArgsConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_brain_circuit_filled"),
            hint="FunASR 语音识别模型参数配置",
            side="top",
        )
        self.layerMain().addPage(
            SenseVoiceArgsConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_brain_circuit_filled"),
            hint="SenseVoice 语音识别模型参数配置",
            side="top",
        )
        self.layerMain().addPage(
            ParaformerArgsConfigPage(self.config, self.config_path),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_brain_circuit_filled"),
            hint="Paraformer 语音识别模型参数配置",
            side="top",
        )
        self.layerMain().addPage(
            AboutPage(self),
            icon=SiGlobal.siui.iconpack.get("ic_fluent_info_filled"),
            hint="关于",
            side="bottom",
        )

        self.layerMain().setPage(0)

    def load_config(self):
        with Path(self.config_path).open("r", encoding="utf-8") as f:
            return parse(f.read())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ConfigEditor("config.toml")
    window.show()
    sys.exit(app.exec())
