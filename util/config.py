import re
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table
from tomlkit import parse

# 加载TOML配置文件
config_toml_path = Path(__file__).parent.parent / "config.toml"
with config_toml_path.open("r", encoding="utf-8") as f:
    config_str = f.read()
    config = parse(config_str)


# 调试配置
class DebugConfig:
    logger_level: str = config["debug"]["logger_level"]


# 服务端配置
class ServerConfig:
    model: str = config["server"]["model"]
    expand_funasr_hotwords: bool = config["server"]["expand_funasr_hotwords"]
    addr: str = config["server"]["addr"]
    speech_recognition_port: str = config["server"]["speech_recognition_port"]
    check_port_usage_before_start: bool = config["server"][
        "check_port_usage_before_start"
    ]
    start_online_translate_server: bool = config["server"][
        "start_online_translate_server"
    ]
    start_offline_translate_server: bool = config["server"][
        "start_offline_translate_server"
    ]
    offline_translate_port: str = config["server"]["offline_translate_port"]
    format_num: bool = config["server"]["format_num"]
    format_punc: bool = config["server"]["format_punc"]
    format_spell: bool = config["server"]["format_spell"]
    shrink_automatically_to_tray: bool = config["server"][
        "shrink_automatically_to_tray"
    ]
    only_run_once: bool = config["server"]["only_run_once"]
    in_the_meantime_start_the_client: bool = config["server"][
        "in_the_meantime_start_the_client"
    ]
    in_the_meantime_start_the_client_and_run_as_admin: bool = config["server"][
        "in_the_meantime_start_the_client_and_run_as_admin"
    ]


# 客户端配置
class ClientConfig:
    addr: str = config["client"]["addr"]
    speech_recognition_port: str = config["client"]["speech_recognition_port"]
    offline_translate_port: str = config["client"]["offline_translate_port"]
    offline_translate_port_gemma2b: str = config["client"][
        "offline_translate_port_gemma2b"
    ]
    speech_recognition_shortcut: str = config["client"]["speech_recognition_shortcut"]
    disable_exe_list_on_focus: list[str] = config["client"]["disable_exe_list_on_focus"]
    disable_exe_list: list[str] = config["client"]["disable_exe_list"]
    use_offline_translate_function: bool = config["client"][
        "use_offline_translate_function"
    ]
    offline_translate_shortcut: str = config["client"]["offline_translate_shortcut"]
    use_online_translate_function: bool = config["client"][
        "use_online_translate_function"
    ]
    online_translate_shortcut: str = config["client"]["online_translate_shortcut"]
    online_translate_target_languages_libretranslate: str = config["client"][
        "online_translate_target_languages_libretranslate"
    ]
    online_translate_target_languages: str = config["client"][
        "online_translate_target_languages"
    ]
    hold_mode: bool = config["client"]["hold_mode"]
    suppress: bool = config["client"]["suppress"]
    restore_key: bool = config["client"]["restore_key"]
    threshold: float = config["client"]["threshold"]
    paste: bool = config["client"]["paste"]
    restore_clipboard_after_paste: bool = config["client"][
        "restore_clipboard_after_paste"
    ]
    save_audio: bool = config["client"]["save_audio"]
    save_markdown: bool = config["client"]["save_markdown"]
    save_non_kwd_markdown: bool = config["client"]["save_non_kwd_markdown"]
    audio_name_len: int = config["client"]["audio_name_len"]
    reduce_audio_files: bool = config["client"]["reduce_audio_files"]
    trash_punc: str = config["client"]["trash_punc"]
    hot_zh: bool = config["client"]["hot_zh"]
    多音字: bool = config["client"]["多音字"]
    声调: bool = config["client"]["声调"]
    hot_en: bool = config["client"]["hot_en"]
    hot_rule: bool = config["client"]["hot_rule"]
    hot_kwd: bool = config["client"]["hot_kwd"]
    hot_rag: bool = config["client"]["hot_rag"]
    use_hot_sub_when_transcribe_file: bool = config["client"][
        "use_hot_sub_when_transcribe_file"
    ]
    mic_seg_duration: int = config["client"]["mic_seg_duration"]
    mic_seg_overlap: int = config["client"]["mic_seg_overlap"]
    realtime_paste_interval: int = config["client"]["realtime_paste_interval"]
    file_seg_duration: int = config["client"]["file_seg_duration"]
    file_seg_overlap: int = config["client"]["file_seg_overlap"]
    file_save_srt: bool = config["client"]["file_save_srt"]
    file_save_txt: bool = config["client"]["file_save_txt"]
    file_save_json: bool = config["client"]["file_save_json"]
    file_save_merge: bool = config["client"]["file_save_merge"]
    mute_other_audio: bool = config["client"]["mute_other_audio"]
    pause_other_audio: bool = config["client"]["pause_other_audio"]
    QQMusic_global_pause_hotkey: str = config["client"]["QQMusic_global_pause_hotkey"]
    CloudMusic_global_pause_hotkey: str = config["client"][
        "CloudMusic_global_pause_hotkey"
    ]
    PotPlayer_global_pause_hotkey: str = config["client"][
        "PotPlayer_global_pause_hotkey"
    ]
    foobar2000_global_pause_hotkey: str = config["client"][
        "foobar2000_global_pause_hotkey"
    ]
    additional_special_apps: dict[str, dict[str, str]] = config["client"][
        "additional_special_apps"
    ]
    arabic_year_number: bool = config["client"]["arabic_year_number"]
    shrink_automatically_to_tray: bool = config["client"][
        "shrink_automatically_to_tray"
    ]
    only_run_once: bool = config["client"]["only_run_once"]
    only_enable_microphones_when_pressed_record_shortcut: bool = config["client"][
        "only_enable_microphones_when_pressed_record_shortcut"
    ]
    vscode_exe_path: str = config["client"]["vscode_exe_path"]
    play_start_music: bool = config["client"]["play_start_music"]
    start_music_path: Path = Path(config["client"]["start_music_path"])
    start_music_volume: str = config["client"]["start_music_volume"]
    play_stop_music: bool = config["client"]["play_stop_music"]
    stop_music_path: Path = Path(config["client"]["stop_music_path"])
    stop_music_volume: str = config["client"]["stop_music_volume"]
    hint_while_recording_at_edit_position_powered_by_ahk: bool = config["client"][
        "hint_while_recording_at_edit_position_powered_by_ahk"
    ]
    hint_while_recording_at_cursor_position: bool = config["client"][
        "hint_while_recording_at_cursor_position"
    ]
    check_microphone_usage_by: str = config["client"]["check_microphone_usage_by"]
    enable_double_click_opposite_state: bool = config["client"][
        "enable_double_click_opposite_state"
    ]
    convert_to_traditional_chinese_main: Literal["简", "繁"] = config["client"][
        "convert_to_traditional_chinese_main"
    ]
    opencc_converter: str = config["client"]["opencc_converter"]
    enable_ai_optimize_language_expression: bool = config["client"][
        "enable_ai_optimize_language_expression"
    ]
    ai_provider: Literal["zhipuai", "openai"] = config["client"]["ai_provider"]
    prompt_style_selection: str = config["client"]["prompt_style_selection"]
    show_prompt_style_changed_notification: bool = config["client"][
        "show_prompt_style_changed_notification"
    ]
    show_time_label: bool = config["client"]["show_time_label"]
    zhipuai_api_key: str = config["client"]["zhipuai"]["api_key"]
    zhipuai_model: str = config["client"]["zhipuai"]["model"]
    openai_api_key: str = config["client"]["openai"]["api_key"]
    openai_base_url: str = config["client"]["openai"]["base_url"]
    openai_model: str = config["client"]["openai"]["model"]
    prompt_official_shortcut: str = config["client"]["prompt_style"][
        "prompt_official_shortcut"
    ]
    prompt_official: str = config["client"]["prompt_style"]["prompt_official"]
    prompt_sweetheart_shortcut: str = config["client"]["prompt_style"][
        "prompt_sweetheart_shortcut"
    ]
    prompt_sweetheart: str = config["client"]["prompt_style"]["prompt_sweetheart"]
    prompt_social_shortcut: str = config["client"]["prompt_style"][
        "prompt_social_shortcut"
    ]
    prompt_social: str = config["client"]["prompt_style"]["prompt_social"]
    prompt_poetry_shortcut: str = config["client"]["prompt_style"][
        "prompt_poetry_shortcut"
    ]
    prompt_poetry: str = config["client"]["prompt_style"]["prompt_poetry"]
    prompt_english_shortcut: str = config["client"]["prompt_style"][
        "prompt_english_shortcut"
    ]
    prompt_english: str = config["client"]["prompt_style"]["prompt_english"]
    prompt_academic_shortcut: str = config["client"]["prompt_style"][
        "prompt_academic_shortcut"
    ]
    prompt_academic: str = config["client"]["prompt_style"]["prompt_academic"]
    prompt_customer_service_shortcut: str = config["client"]["prompt_style"][
        "prompt_customer_service_shortcut"
    ]
    prompt_customer_service: str = config["client"]["prompt_style"][
        "prompt_customer_service"
    ]
    prompt_creative_writing_shortcut: str = config["client"]["prompt_style"][
        "prompt_creative_writing_shortcut"
    ]
    prompt_creative_writing: str = config["client"]["prompt_style"][
        "prompt_creative_writing"
    ]


# LibreTranslate 配置
class LibreTranslateConfig:
    api: str = config["libretranslate"]["api"]


# DeepLX 配置
class DeepLXConfig:
    online_translate_port: str = config["deeplx"]["online_translate_port"]
    exe_path: Path = Path(config["deeplx"]["exe_path"])
    api: str = config["deeplx"]["api"]


# 模型路径配置
class ModelPaths:
    model_dir: Path = Path(config["model_paths"]["model_dir"])
    funasr_dir: Path = Path(config["model_paths"]["funasr_dir"])
    funasr_encoder_adaptor_path: Path = Path(
        config["model_paths"]["funasr_encoder_adaptor_path"]
    )
    funasr_ctc_path: Path = Path(config["model_paths"]["funasr_ctc_path"])
    funasr_llm_path: Path = Path(config["model_paths"]["funasr_llm_path"])
    funasr_tokens_path: Path = Path(config["model_paths"]["funasr_tokens_path"])
    funasr_hotwords_path: Path = Path(config["model_paths"]["funasr_hotwords_path"])
    sensevoice_path: Path = Path(config["model_paths"]["sensevoice_path"])
    sensevoice_tokens_path: Path = Path(config["model_paths"]["sensevoice_tokens_path"])
    paraformer_path: Path = Path(config["model_paths"]["paraformer_path"])
    paraformer_tokens_path: Path = Path(config["model_paths"]["paraformer_tokens_path"])
    punc_model_dir: Path = Path(config["model_paths"]["punc_model_dir"])
    opus_mt_dir: Path = Path(config["model_paths"]["opus_mt_dir"])


# FunASR 参数配置
class FunASRArgs:
    encoder_onnx_path: str = config["model_paths"]["funasr_encoder_adaptor_path"]
    ctc_onnx_path: str = config["model_paths"]["funasr_ctc_path"]
    decoder_gguf_path: str = config["model_paths"]["funasr_llm_path"]
    tokens_path: str = config["model_paths"]["funasr_tokens_path"]
    hotwords_path: str = config["model_paths"]["funasr_hotwords_path"]
    enable_ctc: bool = config["funasr_args"]["enable_ctc"]
    n_predict: int = config["funasr_args"]["n_predict"]
    n_threads: int = config["funasr_args"]["n_threads"]
    similar_threshold: float = config["funasr_args"]["similar_threshold"]
    max_hotwords: int = config["funasr_args"]["max_hotwords"]
    directml_enable: bool = config["funasr_args"]["directml_enable"]
    vulkan_enable: bool = config["funasr_args"]["vulkan_enable"]
    vulkan_force_fp32: bool = config["funasr_args"]["vulkan_force_fp32"]
    verbose: bool = config["funasr_args"]["verbose"]


# SenseVoice 参数配置
class SenseVoiceArgs:
    model: str = config["model_paths"]["sensevoice_path"]
    tokens: str = config["model_paths"]["sensevoice_tokens_path"]
    num_threads: int = config["sensevoice_args"]["num_threads"]
    sample_rate: int = config["sensevoice_args"]["sample_rate"]
    feature_dim: int = config["sensevoice_args"]["feature_dim"]
    decoding_method: str = config["sensevoice_args"]["decoding_method"]
    debug: bool = config["sensevoice_args"]["debug"]
    provider: str = config["sensevoice_args"]["provider"]
    language: str = config["sensevoice_args"]["language"]
    use_itn: bool = config["sensevoice_args"]["use_itn"]
    rule_fsts: str = config["sensevoice_args"]["rule_fsts"]
    rule_fars: str = config["sensevoice_args"]["rule_fars"]


# Paraformer 参数配置
class ParaformerArgs:
    paraformer: str = config["model_paths"]["paraformer_path"]
    tokens: str = config["model_paths"]["paraformer_tokens_path"]
    num_threads: int = config["paraformer_args"]["num_threads"]
    sample_rate: int = config["paraformer_args"]["sample_rate"]
    feature_dim: int = config["paraformer_args"]["feature_dim"]
    decoding_method: str = config["paraformer_args"]["decoding_method"]
    debug: bool = config["paraformer_args"]["debug"]


def print_config():
    """测试，打印所有配置信息"""

    def clearly_type(obj):
        result = type(obj).__name__
        match = re.search(r"'(.*?)'", result)
        if match:
            return match.group(1)
        else:
            return result

    console = Console()
    config_classes = [
        DebugConfig,
        ServerConfig,
        ClientConfig,
        LibreTranslateConfig,
        DeepLXConfig,
        ModelPaths,
        FunASRArgs,
        SenseVoiceArgs,
        ParaformerArgs,
    ]

    for config_class in config_classes:
        table = Table(title=f"{config_class.__name__} 配置")

        table.add_column("属性名", style="cyan")
        table.add_column("类型", style="magenta")
        table.add_column("值", style="green")

        for key, value in config_class.__dict__.items():
            if not key.startswith("_"):
                attr_type = clearly_type(value)
                attr_value = str(value)
                table.add_row(key, attr_type, attr_value)

        console.print(table)


if __name__ == "__main__":
    print_config()
