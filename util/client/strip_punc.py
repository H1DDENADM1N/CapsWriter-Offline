import re

from util.config import ClientConfig as Config


def strip_punc(text: str) -> str:
    """
    消除末尾最后一个标点

    ported from upstream fcc0325 口述标点规则配套：
    - 只去除末尾「最后一个」标点，而不是 rstrip 掉全部末尾标点。
    - 用 (?<=.) 断言保证被删的标点前至少有一个字符，避免整串被删空。

    Args:
        text: 原始文本

    Returns:
        去除末尾一个标点后的文本
    """
    if not text:
        return text
    clean_text = re.sub(f"(?<=.)[{Config.trash_punc}]$", "", text)
    return clean_text if clean_text else text
