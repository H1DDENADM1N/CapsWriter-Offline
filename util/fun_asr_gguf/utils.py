"""
FunASR-GGUF 通用工具函数
"""

import loguru

# 使用模块变量 _logger，允许外部注入
_logger = loguru.logger


def set_utils_logger(logger_instance):
    """外部调用此函数注入 logger，用于多进程日志"""
    global _logger
    _logger = logger_instance


def vprint(message: str, verbose: bool = True):
    """条件输出：仅在 verbose=True 时输出到控制台，并始终记录到日志"""
    if verbose:
        # print 仍然保留，用于直接输出到 stdout（例如 Rich 进度条需要）
        print(message)

    # 始终记录到日志系统，通过注入的 logger 发送到主进程
    _logger.info(message)


def format_ms(seconds: float) -> str:
    """将秒转换为毫秒字符串"""
    return f"{seconds * 1000:5.0f}ms"
