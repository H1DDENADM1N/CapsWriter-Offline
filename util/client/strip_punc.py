from util.config import ClientConfig as Config


def strip_punc(text: str) -> str:
    """
    消除末尾标点

    Args:
        text: 原始文本

    Returns:
        去除末尾标点后的文本
    """
    if not text:
        return text
    clean_text = text.rstrip(Config.trash_punc)
    return clean_text if clean_text else text
