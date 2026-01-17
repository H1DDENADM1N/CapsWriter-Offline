import os

# 导入配置相关模块
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from util.client import hot_kwds, hot_sub_en, hot_sub_rule, hot_sub_zh
from util.client.cosmic import Cosmic, console

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tomlkit import parse

from util.config import ClientConfig as Config

path_zh = Path() / "hot-zh.txt"
path_en = Path() / "hot-en.txt"
path_rule = Path() / "hot-rule.txt"
path_kwds = Path() / "keywords.txt"
path_rag = Path() / "hot-rag.txt"
config_toml_path = Path() / "config.toml"


def update_hot_zh():
    if not path_zh.exists():
        with open(path_zh, "w", encoding="utf-8") as f:
            f.write("# 在此文件放置中文热词，每行一个，开头带井号表示注释，会被省略")
    with open(path_zh, "r", encoding="utf-8") as f:
        num_hot_zh = hot_sub_zh.更新热词词典(f.read())
    console.print(f"已载入 [green4]{num_hot_zh:5}[/] 条中文热词")


def update_hot_en():
    if not path_en.exists():
        with open(path_en, "w", encoding="utf-8") as f:
            f.write(
                "# 在此文件放置英文热词 \n# Put English hot words here, one per line. Line starts with # will be ignored. "
            )
    with open(path_en, "r", encoding="utf-8") as f:
        num_hot_en = hot_sub_en.更新热词词典(f.read())
    console.print(f"已载入 [green4]{num_hot_en:5}[/] 条英文热词")


def update_hot_rule():
    if not path_rule.exists():
        with open(path_rule, "w", encoding="utf-8") as f:
            f.write(
                r"""# 在此文件放置自定义规则，每行一条正则表达式，
# 左边是查找模式，右边是替换式，中间用带空格的等号分开
# 以 # 开头的会被忽略，将查找和匹配用等号隔开，文本两边的空格会被省略。例如：

毫安时     =      mAh
赫兹      =      Hz
伏特      =        V
二、      =        二
负一      =    -1
(艾特)\s*(QQ)\s*点\s*            =     @qq.
(艾特)\s*([一幺]六三)\s*点\s*     =     @163.
(艾特)\s*(\w+)\s*(点)\s*(\w+)    =     @\2.\4
"""
            )
    with open(path_rule, "r", encoding="utf-8") as f:
        num_hot_rule = hot_sub_rule.更新热词词典(f.read())
    console.print(f"已载入 [green4]{num_hot_rule:5}[/] 条自定义替换规则")


def update_hot_kwds():
    if not path_kwds.exists():
        with open(path_kwds, "w", encoding="utf-8") as f:
            f.write(
                "# 在此文件放置日记关键词，每行一个，开头带井号表示注释，会被省略\n# 当识别结果以关键词开头时，会被记录到 「年份/月份/关键词-日期.md」文件中\n重要\n健康\n学习"
            )
    with open(path_kwds, "r", encoding="utf-8") as f:
        num_kwd = hot_kwds.do_updata_kwd(f.read())
    console.print(f"已载入 [green4]{num_kwd:5}[/] 条日记关键词")


def update_hot_rag():
    if not path_rag.exists():
        with open(path_rag, "w", encoding="utf-8") as f:
            f.write(
                """
# 热词文件
# 每行一个热词，井号开头的行为注释，会被忽略
# 使用音素 RAG 匹配，支持中英文混合
"""
            )
    # Cosmic.corrector.load_hotwords_file(path_rag, append_mode=False)
    Cosmic.corrector.load_hotwords_file(path_zh, append_mode=True)
    Cosmic.corrector.load_hotwords_file(path_en, append_mode=True)


def update_config():
    """更新配置文件"""
    try:
        # 重新加载配置文件
        with config_toml_path.open("r", encoding="utf-8") as f:
            config_str = f.read()
            new_config = parse(config_str)
            update_save_audio(new_config)
            update_save_markdown(new_config)
            update_save_non_kwd_markdown(new_config)
            update_convert_to_traditional_chinese(new_config)
            update_enable_ai_optimize_language_expression(new_config)
            update_ai_provider(new_config)
            update_prompt_style_selection(new_config)
            update_openai_api_key(new_config)
            update_openai_model(new_config)
            update_openai_base_url(new_config)
            update_zhipuai_api_key(new_config)
            update_zhipuai_model(new_config)
        return True
    except Exception as e:
        console.print(f"[red]配置热更新失败: {e}[/]")
        return False


def update_save_audio(new_config):
    """更新保存音频配置"""
    old_value: bool = Config.save_audio
    new_value: bool = new_config["client"]["save_audio"]

    if old_value != new_value:
        Config.save_audio = new_value
        console.print(f"[green4]保存音频配置已更新，保存音频为 {new_value} [/]")


def update_save_markdown(new_config):
    """更新保存日记配置"""
    old_value: bool = Config.save_markdown
    new_value: bool = new_config["client"]["save_markdown"]

    if old_value != new_value:
        Config.save_markdown = new_value
        console.print(f"[green4]保存日记配置已更新，保存日记为 {new_value} [/]")


def update_save_non_kwd_markdown(new_config):
    """更新保存非关键词日记配置"""
    old_value: bool = Config.save_non_kwd_markdown
    new_value: bool = new_config["client"]["save_non_kwd_markdown"]

    if old_value != new_value:
        Config.save_non_kwd_markdown = new_value
        console.print(
            f"[green4]保存非关键词日记配置已更新，保存非关键词日记为 {new_value} [/]"
        )


def update_convert_to_traditional_chinese(new_config):
    """更新繁简体转换配置"""
    old_value: Literal["简", "繁"] = Config.convert_to_traditional_chinese_main
    new_value: Literal["简", "繁"] = new_config["client"][
        "convert_to_traditional_chinese_main"
    ]

    if old_value != new_value:
        Config.convert_to_traditional_chinese_main = new_value
        console.print(f"[green4]繁简体转换配置已更新，单键输出 {new_value} 体[/]")


def update_enable_ai_optimize_language_expression(new_config):
    """更新启用AI语言优化配置"""
    old_value: bool = Config.enable_ai_optimize_language_expression
    new_value: bool = new_config["client"]["enable_ai_optimize_language_expression"]

    if old_value != new_value:
        Config.enable_ai_optimize_language_expression = new_value
        console.print(f"[green4]AI语言优化配置已更新，启用AI语言优化为 {new_value} [/]")


def update_ai_provider(new_config):
    """更新AI供应商"""
    old_value: str = Config.ai_provider
    new_value: str = new_config["client"]["ai_provider"]

    if old_value != new_value:
        Config.ai_provider = new_value
        console.print(f"[green4]AI供应商已更新，AI供应商为 {new_value} [/]")


def update_prompt_style_selection(new_config):
    """更新提示词样式选中"""
    old_value: str = Config.prompt_style_selection
    new_value: str = new_config["client"]["prompt_style_selection"]

    if old_value != new_value:
        Config.prompt_style_selection = new_value
        console.print(f"[green4]提示词样式已更新，提示词样式为 {new_value} [/]")


def update_openai_api_key(new_config):
    """更新 OpenAI API Key配置"""
    old_value: str = Config.openai_api_key
    new_value: str = new_config["client"]["openai"]["api_key"]

    if old_value != new_value:
        Config.openai_api_key = new_value
        console.print(
            f"[green4]API Key已更新， {mask_key(old_value)} -> {mask_key(new_value)} [/]"
        )


def update_openai_model(new_config):
    """更新 OpenAI 模型配置"""
    old_value: str = Config.openai_model
    new_value: str = new_config["client"]["openai"]["model"]

    if old_value != new_value:
        Config.openai_model = new_value
        console.print(f"[green4]模型已更新，模型为 {new_value} [/]")


def update_openai_base_url(new_config):
    """更新 OpenAI 基础 URL 配置"""
    old_value: str = Config.openai_base_url
    new_value: str = new_config["client"]["openai"]["base_url"]

    if old_value != new_value:
        Config.openai_base_url = new_value
        console.print(f"[green4]基础 URL 已更新，基础 URL 为 {new_value} [/]")


def update_zhipuai_api_key(new_config):
    """更新 智谱AI API Key配置"""
    old_value: str = Config.zhipuai_api_key
    new_value: str = new_config["client"]["zhipuai"]["api_key"]

    if old_value != new_value:
        Config.zhipuai_api_key = new_value
        console.print(
            f"[green4]API Key已更新， {mask_key(old_value)} -> {mask_key(new_value)} [/]"
        )


def update_zhipuai_model(new_config):
    """更新 智谱AI 模型配置"""
    old_value: str = Config.zhipuai_model
    new_value: str = new_config["client"]["zhipuai"]["model"]

    if old_value != new_value:
        Config.zhipuai_model = new_value
        console.print(f"[green4]模型已更新，模型为 {new_value} [/]")


def mask_key(key):
    if not key:
        return ""
    if len(key) <= 10:
        return key
    return f"{key[:5]}...{key[-5:]}"


def update_hot_all():
    update_hot_zh()
    update_hot_en()
    update_hot_rule()
    update_hot_kwds()
    update_hot_rag()
    console.line()


def observe_hot():
    observer = Observer()
    observer.schedule(HotHandler(), ".", recursive=False)
    observer.start()
    return observer


class HotHandler(FileSystemEventHandler):
    """用于动态更新热词和配置的处理器"""

    last_time = 0

    updates = {
        path_zh: update_hot_zh,
        path_en: update_hot_en,
        path_rule: update_hot_rule,
        path_kwds: update_hot_kwds,
        path_rag: update_hot_rag,
        config_toml_path: update_config,
    }

    def on_modified(self, event):
        # 事件间隔小于2秒就取消
        if time.time() - self.last_time < 2:
            return

        # 路径不对就取消
        event_path = Path(event.src_path)
        if event_path not in self.updates:
            return

        # 更新时间
        self.last_time = time.time()

        # 延迟0.2秒，避免编辑器还没有将文件更新完成导致读空
        time.sleep(0.2)

        if event_path == config_toml_path:
            console.print("[green4]检测到配置文件更新：[/]")
        else:
            console.print("[green4]检测到热词文件更新：[/]")

        # 更新
        try:
            self.updates[event_path]()
            console.line()
        except Exception as e:
            console.print(f"更新失败：{e}", style="bright_red")
