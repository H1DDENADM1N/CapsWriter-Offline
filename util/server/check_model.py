import sys
from pathlib import Path

from util.config import ModelPaths, QwenCTCArgs
from util.config import ServerConfig as Config
from util.server.cosmic import console


# 规格 §4.3 的下载命令。缺失文件时原样展示，命令本身一个字符都不要改写。
QWEN_DOWNLOAD_COMMANDS = """\
# 1.7B 解码器
curl -4 -L -C - -o models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf \\
  "https://modelscope.cn/models/luciacx/Qwen3-ASR-GGUF-1.7B-mixed/resolve/master/qwen3_asr_llm.q4_k.gguf"

# 0.6B 全套
mkdir -p models/qwen-ctc-aiinfra4-06b
for f in qwen3_asr_encoder_frontend.int4.onnx qwen3_asr_encoder_backend.int4.onnx qwen3_asr_llm.q4_k.gguf; do
  curl -4 -L -C - -o "models/qwen-ctc-aiinfra4-06b/$f" \\
    "https://modelscope.cn/models/luciacx/Qwen3-ASR-GGUF-0.6B-mixed/resolve/master/$f"
done"""


def _configured(value) -> bool:
    """空字符串 / None 都视为「未配置」。

    `ModelPaths` 侧的可留空路径已归一为 `None`（避免 `Path("")` 变成 `Path(".")`）；
    `QwenCTCArgs` 侧是原始字符串，空串即未配置。
    """
    return value is not None and str(value).strip() != ""


def required_qwen_files(
    split_encoder: bool,
    has_decoder: bool,
    enable_ctc: bool,
    paths: dict,
) -> list[str]:
    """
    按已解析的模式返回 QwenCTC 必需文件列表（只含非空路径，顺序稳定）。

    顺序固定为：encoder 或 frontend/backend → ctc → tokens → preprocessor → decoder。

    - 融合 encoder（split_encoder=False）：启用 CTC 时要求 ctc + tokens；
      禁用 CTC 时只要求 encoder + preprocessor（+ 解码器）。
    - 拆分 encoder（split_encoder=True）：0.6B 没有 CTC 头，永远不要 ctc / tokens，
      只要 frontend + backend + preprocessor（+ 解码器）。
    - `decoder` 为空字符串（或 None）是合法的纯 CTC，不能进列表。

    Args:
        split_encoder: 是否使用 0.6B 前后端拆分编码器
        has_decoder: 配置里是否给出了非空解码器路径
        enable_ctc: 配置里的 `enable_ctc`
        paths: 键为 encoder/frontend/backend/ctc/tokens/preprocessor/decoder 的路径字典

    Returns:
        非空路径组成的列表，顺序稳定可断言
    """
    required: list[str] = []
    if split_encoder:
        for key in ("frontend", "backend"):
            path = paths.get(key)
            if _configured(path):
                required.append(str(path))
    else:
        encoder = paths.get("encoder")
        if _configured(encoder):
            required.append(str(encoder))
        if enable_ctc:
            for key in ("ctc", "tokens"):
                path = paths.get(key)
                if _configured(path):
                    required.append(str(path))

    preprocessor = paths.get("preprocessor")
    if _configured(preprocessor):
        required.append(str(preprocessor))

    decoder = paths.get("decoder")
    if has_decoder and _configured(decoder):
        required.append(str(decoder))

    return required


def qwen_mode_errors(
    has_frontend: bool,
    has_backend: bool,
    has_decoder: bool,
    enable_ctc: bool,
    *,
    ctc_configured: bool = True,
    tokens_configured: bool = True,
) -> list[str]:
    """
    模式层面（与文件是否存在无关）的硬错误，必须在加载引擎之前就暴露。

    **错误顺序本身是语义的一部分**：0.6B 前后端的「没有 CTC 头」必须排在
    「既未配置解码器又禁用了 CTC」之前，与引擎 `resolve_mode()` 的判定顺序一致；
    两者同时命中时，拆分那条更具体、更可执行。

    `ctc_configured` / `tokens_configured` 只在「纯 CTC（无解码器且启用 CTC）」
    时才有意义：那时缺 CTC 头 / 词表就没有推理路径。默认 `True` 表示调用方
    未提供该项信息时不额外判定；`_qwen_plan()` 会显式传入真实配置。

    文案要能直接照着做，并包含规格 §7.2 的关键句。返回空列表表示模式合法。
    """
    errors: list[str] = []

    # ① 0.6B 拆分编码器没有 CTC 头：没配解码器就一条推理路径都没有。
    #    不看 enable_ctc —— 这条路径上 CTC 头必然不可用（引擎 resolve_mode 同样
    #    先判这一条再判下面的「既无解码器又禁 CTC」）。
    if has_frontend and has_backend and not has_decoder:
        errors.append(
            "0.6B 编码器（前后端拆分）没有 CTC 头，无推理路径：请在 config.toml 的"
            " model_paths 段填写 qwen_llm_path 以配置解码器，或把"
            " qwen_ctc_encoder_frontend_path 与 qwen_ctc_encoder_backend_path"
            " 留空，改用 1.7B 融合编码器"
        )

    # ② 既没解码器又禁用 CTC
    if not has_decoder and not enable_ctc:
        errors.append(
            "既未配置解码器又禁用了 CTC，无推理路径：请在 config.toml 的 model_paths 段"
            "填写 qwen_llm_path，或在 qwen_ctc_args 段把 enable_ctc 设为 true"
        )

    # ③ 0.6B 前后端只配一端
    if has_frontend != has_backend:
        errors.append(
            "0.6B 编码器前后端必须成对配置：请在 config.toml 的 model_paths 段同时填写"
            " qwen_ctc_encoder_frontend_path 与 qwen_ctc_encoder_backend_path，"
            "或两者都留空改用 1.7B 融合编码器"
        )

    # ④ 纯 CTC（无解码器 + 启用 CTC）但缺 CTC 头 / 词表：引擎初始化时硬失败。
    #    有解码器时缺 CTC 头是合法的（引擎 WARNING 降级为纯 LLM），不在这里报。
    if not has_decoder and enable_ctc and not (
        ctc_configured and tokens_configured
    ):
        errors.append(
            "纯 CTC 模式必须配置 ctc_onnx_path 与 tokens_path：请在 config.toml 的"
            " qwen_ctc_args 段填写 ctc_onnx_path 与 tokens_path（CTC 头与紧凑词表），"
            "或填写 model_paths.qwen_llm_path 配置解码器改用两遍 / 纯 LLM"
        )

    return errors


def _qwen_plan() -> tuple[dict, list[str]]:
    """按 `QwenCTCArgs`（= 引擎真正收到的配置）生成必需文件与模式错误。

    两个变体共用，避免 CLI / GUI 两处再次不同步。
    注意：不能用 `ModelPaths.qwen_llm_path` 取解码器路径——老配置缺键时它的回退值
    是 1.7B 默认路径，而引擎侧 `QwenCTCArgs.decoder_gguf_path` 回退为空串（纯 CTC）。
    """
    paths = {
        "encoder": QwenCTCArgs.encoder_onnx_path,
        "frontend": QwenCTCArgs.encoder_frontend_path,
        "backend": QwenCTCArgs.encoder_backend_path,
        "ctc": QwenCTCArgs.ctc_onnx_path,
        "tokens": QwenCTCArgs.tokens_path,
        "preprocessor": QwenCTCArgs.preprocessor_path,
        "decoder": QwenCTCArgs.decoder_gguf_path,
    }
    has_frontend = _configured(paths["frontend"])
    has_backend = _configured(paths["backend"])
    has_decoder = _configured(paths["decoder"])
    split_encoder = has_frontend and has_backend

    errors = qwen_mode_errors(
        has_frontend,
        has_backend,
        has_decoder,
        QwenCTCArgs.enable_ctc,
        ctc_configured=_configured(paths["ctc"]),
        tokens_configured=_configured(paths["tokens"]),
    )
    files = required_qwen_files(
        split_encoder, has_decoder, QwenCTCArgs.enable_ctc, paths
    )
    return {"Qwen3-ASR 模型文件（按当前配置解析）": files}, errors


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
    elif model == "QwenCTC":
        required_files, mode_errors = _qwen_plan()
        if mode_errors:
            for msg in mode_errors:
                passed_logger.error(msg)
            error_msg = "\n    [bold red]QwenCTC 配置无法确定推理模式[/bold red]\n\n"
            for msg in mode_errors:
                error_msg += f"    {msg}\n"
            console.print(error_msg)
            input("按回车退出")
            sys.exit(1)
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
    - 'QwenCTC'

        """,
            style="bright_red",
        )
        input("按回车退出")
        sys.exit(1)

    # 检查所有必需的文件
    missing_files = []
    for category, files in required_files.items():
        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                missing_files.append((category, path))
                passed_logger.warning(f"模型文件缺失: {path}")

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
        if model == "QwenCTC":
            error_msg += "\n    [bold]Qwen 模型下载命令（在仓库根目录执行）[/bold]\n\n"
            error_msg += QWEN_DOWNLOAD_COMMANDS
            error_msg += "\n"
        error_msg += "    \n"

        passed_logger.error(f"模型文件检查失败，共 {len(missing_files)} 个文件缺失")
        # soft_wrap：下载命令里有 `for f in ...; do` 这种长行，默认按终端宽度折行
        # 后用户复制粘贴会拿到断成两截的命令，必须让 rich 原样单行输出。
        console.print(error_msg, soft_wrap=True)
        input("按回车退出")
        sys.exit(1)

    # 所有检查通过
    passed_logger.info(f"模型文件检查通过 ({model})")
    # console.print(f"[green4]模型文件检查通过 ({model})", end="\n\n")


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
    elif model == "QwenCTC":
        required_files, mode_errors = _qwen_plan()
        if mode_errors:
            for msg in mode_errors:
                passed_logger.error(msg)
            raise Exception(
                "QwenCTC 配置无法确定推理模式：\n" + "\n".join(mode_errors)
            )
    else:
        error_msg = f"""
    [bold red]不支持的模型类型：{Config.model}[/bold red]

    请在 config.toml 中将 model 设置为：
    - 'FunASR'
    - 'Sensevoice'
    - 'Paraformer'
    - 'QwenCTC'
        """
        raise Exception(error_msg)

    # 检查所有必需的文件
    missing_files = []
    for category, files in required_files.items():
        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                missing_files.append((category, path))

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
        if model == "QwenCTC":
            error_msg += "\n    [bold]Qwen 模型下载命令（在仓库根目录执行）[/bold]\n\n"
            error_msg += QWEN_DOWNLOAD_COMMANDS
            error_msg += "\n"

        raise Exception(error_msg)

    # 所有检查通过
    passed_logger.info(f"GUI模式 - 模型文件检查通过 ({model})")
