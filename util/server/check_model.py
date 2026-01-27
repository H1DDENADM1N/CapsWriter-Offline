import sys

from util.config import ModelPaths
from util.config import ServerConfig as Config
from util.server.cosmic import console


def check_model(passed_logger) -> None:
    """
    根据配置的模型类型检查所需的模型文件是否存在
    如果模型文件不存在，显示错误信息后退出程序。
    """
    model = Config.model
    passed_logger.debug(f"检查模型文件, 类型: {model}")

    # 根据模型类型确定需要检查的文件
    if model == "FunASR":
        required_files = {
            "Fun-ASR-Nano-GGUF 模型文件": [
                ModelPaths.funasr_encoder_adaptor_path,
                ModelPaths.funasr_ctc_path,
                ModelPaths.funasr_llm_path,
                ModelPaths.funasr_tokens_path,
                ModelPaths.funasr_hotwords_path,
            ]
        }
    elif model == "Sensevoice":
        required_files = {
            "SenseVoice 模型文件": [
                ModelPaths.sensevoice_path,
                ModelPaths.sensevoice_tokens_path,
            ]
        }
    elif model == "Paraformer":
        required_files = {
            "Paraformer 模型文件": [
                ModelPaths.paraformer_path,
                ModelPaths.paraformer_tokens_path,
            ],
            "标点模型文件": [
                ModelPaths.punc_model_dir,
            ],
        }
    else:
        error_msg = f"不支持的模型类型: {Config.model}"
        passed_logger.error(error_msg)
        console.print(
            f"""
    [bold red]不支持的模型类型：{Config.model}[/bold red]

    请在 config.toml 中将 model 设置为：
    - 'FunASR'
    - 'Sensevoice'
    - 'Paraformer'

        """,
            style="bright_red",
        )
        input("按回车退出")
        sys.exit(1)

    # 检查所有必需的文件
    missing_files = []
    for category, files in required_files.items():
        for file_path in files:
            if not file_path.exists():
                missing_files.append((category, file_path))
                passed_logger.warning(f"模型文件缺失: {file_path}")

    # 如果有缺失的文件，显示错误信息并提供下载链接
    if missing_files:
        error_msg = "\n    [bold red]未能找到模型文件[/bold red]\n\n"
        for category, file_path in missing_files:
            error_msg += f"    [{category}]\n"
            error_msg += f"    未找到：{file_path}\n\n"

        error_msg += f"    当前配置的模型类型：[bold yellow]{model}[/bold yellow]\n\n"

        error_msg += (
            f"    下载后请根据发布页说明，解压到：[cyan]{ModelPaths.model_dir}[/cyan]\n"
        )
        error_msg += "    \n"

        passed_logger.error(f"模型文件检查失败，共 {len(missing_files)} 个文件缺失")
        console.print(error_msg)
        input("按回车退出")
        sys.exit(1)

    # 所有检查通过
    passed_logger.info(f"模型文件检查通过 ({model})")
    console.print(f"[green4]模型文件检查通过 ({model})", end="\n\n")


def check_model_gui(passed_logger) -> None:
    """
    GUI版本的模型检查函数，根据配置的模型类型检查所需的模型文件是否存在
    如果模型文件不存在，抛出异常。
    """
    model = Config.model

    # 根据模型类型确定需要检查的文件
    if model == "FunASR":
        required_files = {
            "Fun-ASR-Nano-GGUF 模型文件": [
                ModelPaths.funasr_encoder_adaptor_path,
                ModelPaths.funasr_ctc_path,
                ModelPaths.funasr_llm_path,
                ModelPaths.funasr_tokens_path,
                ModelPaths.funasr_hotwords_path,
            ]
        }
    elif model == "Sensevoice":
        required_files = {
            "SenseVoice 模型文件": [
                ModelPaths.sensevoice_path,
                ModelPaths.sensevoice_tokens_path,
            ]
        }
    elif model == "Paraformer":
        required_files = {
            "Paraformer 模型文件": [
                ModelPaths.paraformer_path,
                ModelPaths.paraformer_tokens_path,
            ],
            "标点模型文件": [
                ModelPaths.punc_model_dir,
            ],
        }
    else:
        error_msg = f"""
    [bold red]不支持的模型类型：{Config.model}[/bold red]

    请在 config.toml 中将 model 设置为：
    - 'FunASR'
    - 'Sensevoice'
    - 'Paraformer'
        """
        raise Exception(error_msg)

    # 检查所有必需的文件
    missing_files = []
    for category, files in required_files.items():
        for file_path in files:
            if not file_path.exists():
                missing_files.append((category, file_path))

    # 如果有缺失的文件，抛出异常
    if missing_files:
        error_msg = "\n    [bold red]未能找到模型文件[/bold red]\n\n"
        for category, file_path in missing_files:
            error_msg += f"    [{category}]\n"
            error_msg += f"    未找到：{file_path}\n\n"

        error_msg += f"    当前配置的模型类型：[bold yellow]{model}[/bold yellow]\n\n"
        error_msg += (
            f"    下载后请根据发布页说明，解压到：[cyan]{ModelPaths.model_dir}[/cyan]\n"
        )

        raise Exception(error_msg)

    # 所有检查通过
    passed_logger.info(f"GUI模式 - 模型文件检查通过 ({model})")
