import subprocess
import threading
from pathlib import Path

from loguru import logger

from util.client.cosmic import console


def play_music(file_path: Path, volume_level: str = "50"):
    """
    调用ffplay播放WAV文件，并指定音量，且不显示控制台窗口，并在播放完毕后自动退出。
    """
    command = ["ffplay", "-volume", volume_level, "-autoexit", str(file_path)]
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        # Start the ffplay process in a separate thread to avoid blocking the main script
        # console.print(f"播放声音 {str(file_path)}")
        threading.Thread(
            target=lambda: subprocess.Popen(
                command,
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=startupinfo,
            )
        ).start()
    except FileNotFoundError:
        console.print("ffplay.exe未找到，请确保它在PATH中或提供完整路径。")

        logger.error("ffplay.exe未找到，请确保它在PATH中或提供完整路径。")
    except Exception as e:
        console.print(f"发生错误: {e}")

        logger.error(f"播放音乐时出错: {e}")


if __name__ == "__main__":
    from pathlib import Path
    from time import sleep

    mp3_file = Path.cwd() / "assets" / "start.mp3"
    play_music(mp3_file)
    sleep(1)
    mp3_file = Path.cwd() / "assets" / "stop.mp3"
    play_music(mp3_file)
