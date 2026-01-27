import re
import time
from pathlib import Path
from typing import Union

from loguru import logger

from util.client.cosmic import Cosmic, console
from util.config import ClientConfig as Config


def rename_audio(task_id, text, time_start) -> Union[Path, None]:
    # 获取旧文件名
    file_path = Path(Cosmic.audio_files.pop(task_id))

    # 确保旧文件存在
    if not file_path.exists():
        console.print(f"    文件不存在：{file_path}")

        logger.error(f"文件不存在：{file_path}")
        return

    # 构建新文件名
    time_year = time.strftime("%Y", time.localtime(time_start))
    time_month = time.strftime("%m", time.localtime(time_start))
    time_ymdhms = time.strftime("%Y%m%d-%H%M%S", time.localtime(time_start))
    file_stem = f"({time_ymdhms}){text[: Config.audio_name_len]}"
    file_stem = re.sub(r'[\\/:"*?<>|]', " ", file_stem)
    file_stem = re.sub(r"\r\n", " ", file_stem)

    # 重命名
    file_path_new = file_path.with_name(file_stem + file_path.suffix)
    try:
        file_path.rename(file_path_new)
        # 返回新的录音文件路径
        return file_path_new
    except Exception as e:
        console.print(f"重命名录音文件时出错: {e}")

        logger.error(f"重命名录音文件时出错: {e}")
