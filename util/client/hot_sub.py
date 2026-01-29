from util.client import hot_sub_en, hot_sub_rag, hot_sub_rule, hot_sub_year, hot_sub_zh
from util.config import ClientConfig as Config
from util.config import DebugConfig


def hot_sub(text: str, debug: bool = False) -> str:
    # 热词替换
    if Config.hot_rag:
        if debug is True and DebugConfig.logger_level not in ("ERROR", "CRITICAL"):
            text = hot_sub_rag.热词替换(text, debug=True)
        else:
            text = hot_sub_rag.热词替换(text, debug=False)
    if Config.hot_zh:
        text = hot_sub_zh.热词替换(text)
    if Config.hot_en:
        text = hot_sub_en.热词替换(text)
    if Config.hot_rule:
        text = hot_sub_rule.热词替换(text)
    if Config.arabic_year_number:
        text = hot_sub_year.热词替换(text)
    return text
