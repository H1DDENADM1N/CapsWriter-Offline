from typing import Optional

from loguru import logger as default_logger
from loguru._logger import Logger

from util.client import hot_sub_en, hot_sub_rag, hot_sub_rule, hot_sub_year, hot_sub_zh
from util.config import ClientConfig as Config
from util.config import DebugConfig


def hot_sub(text: str, debug: bool = False, logger: Optional[Logger] = None) -> str:
    _logger = logger if logger is not None else default_logger
    # ported from upstream bf16001 热词黑名单：黑名单词不做替换。
    # 本方为根目录 hot-blacklist.txt（一行一词，# 开头为注释）的全局黑名单，随文件变更自动重载：
    # RAG 路径在 corrector 匹配阶段拦截（hot_sub_rag._resolve_and_replace）；
    # zh/en 路径由各替换器读取同一黑名单，跳过会命中黑名单词的替换。
    # 热词替换
    if Config.hot_rag:
        if debug is True and DebugConfig.logger_level not in ("ERROR", "CRITICAL"):
            text = hot_sub_rag.热词替换(text, debug=True, logger=_logger)
        else:
            text = hot_sub_rag.热词替换(text, debug=False, logger=_logger)
    if Config.hot_zh:
        text = hot_sub_zh.热词替换(text)
    if Config.hot_en:
        text = hot_sub_en.热词替换(text)
    if Config.hot_rule:
        text = hot_sub_rule.热词替换(text)
    if Config.arabic_year_number:
        text = hot_sub_year.热词替换(text)
    return text