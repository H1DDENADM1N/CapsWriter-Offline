# coding: utf-8
"""
SRT 调整模块

提供 SrtAdjuster 类用于调整 SRT 字幕时间轴。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from loguru import logger as default_logger
from loguru._logger import Logger

from util.client import srt_from_txt
from util.client.cosmic import console


class SrtAdjuster:
    """
    SRT 字幕调整器

    根据文本文件重新生成 SRT 字幕时间轴。
    """

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger if logger is not None else default_logger

    def adjust(self, file: Path) -> None:
        """
        调整 SRT 字幕时间轴

        Args:
            file: 文本文件路径
        """
        task_id = str(uuid.uuid1())
        console.print(f"\n任务标识：{task_id}")
        console.print(f"    处理文件：{file}")

        self.logger.info(f"开始调整 SRT: {file}")

        try:
            srt_from_txt.one_task(file)
            console.print("    [green]srt 调整完成")
            self.logger.info(f"SRT 调整完成: {file}")
        except Exception as e:
            console.print(f"    [red]srt 调整失败: {e}")
            self.logger.error(f"SRT 调整失败: {e}", exc_info=True)
