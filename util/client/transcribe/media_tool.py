# coding: utf-8
import asyncio
import shutil
from pathlib import Path
from typing import List, Optional

from loguru import logger as default_logger
from loguru._logger import Logger

from util.client.cosmic import console


class MediaTool:
    """媒体工具类：负责 FFmpeg 相关操作"""

    @staticmethod
    def check_environment(logger: Optional[Logger] = None) -> bool:
        """检查 FFmpeg 和 ffprobe 环境"""
        _logger = logger if logger is not None else default_logger
        ffmpeg_path = shutil.which("ffmpeg")

        if ffmpeg_path is None:
            console.print("\n[bold red]错误：未检测到 FFmpeg 环境[/bold red]")
            console.print("    文件转录功能依赖 FFmpeg 来提取音视频中的音频。")
            console.print("    [cyan]建议处理方案：[/cyan]")
            console.print(
                "    1. 请确保已安装 FFmpeg 并将其 [bold]bin[/bold] 目录添加到系统环境变量 [bold]Path[/bold] 中。"
            )
            console.print("    2. 或者将 [bold]ffmpeg.exe[/bold] 放置在程序根目录下。")
            console.print(
                "    3. 也可以前往官方下载：[u]https://ffmpeg.org/download.html[/u]\n"
            )
            _logger.error("未检测到 FFmpeg 环境，无法进行文件转录")
            return False

        return True

    @staticmethod
    async def get_audio_duration(file: Path, logger: Optional[Logger] = None) -> float:
        """获取音视频文件时长"""
        _logger = logger if logger is not None else default_logger
        cmd = ["ffmpeg", "-i", str(file), "-f", "null", "-y", "nul"]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            # 从stderr输出中解析持续时间
            output_text = stderr.decode()
            duration_line = None

            for line in output_text.splitlines():
                if "Duration:" in line:
                    duration_line = line.strip()
                    break

            if duration_line:
                # 解析格式: Duration: 00:01:23.45, start: 0.000000, bitrate: 128 kb/s
                parts = duration_line.split("Duration:")
                if len(parts) > 1:
                    time_str = parts[1].split(",")[0].strip()
                    # 将 HH:MM:SS.ms 转换为秒数
                    time_parts = time_str.split(":")
                    if len(time_parts) == 3:
                        hours = int(time_parts[0])
                        minutes = int(time_parts[1])
                        seconds = float(time_parts[2])
                        total_seconds = hours * 3600 + minutes * 60 + seconds
                        return total_seconds

        except Exception as e:
            _logger.warning(f"无法通过 ffmpeg 获取时长: {e}")

        return 0.0

    @staticmethod
    def build_ffmpeg_cmd(file: Path) -> List[str]:
        """构建提取音频的 FFmpeg 命令"""
        return [
            "ffmpeg",
            "-i",
            str(file),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-",
        ]
