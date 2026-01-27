# coding: utf-8

import asyncio
import multiprocessing as mul
import os
import signal
import sys
from pathlib import Path
from platform import system
from typing import List, Optional

import typer
from loguru import logger as default_logger
from loguru._logger import Logger

from util.client.cosmic import Cosmic, console
from util.config import ClientConfig as Config
from util.safe_logger import SafeLogger

if sys.argv[1:]:
    Cosmic.transcribe_subtitles = True
else:
    Cosmic.transcribe_subtitles = False
from util.client.adjust_srt import adjust_srt
from util.client.hot_update import observe_hot, update_hot_all
from util.client.recv_result import recv_result
from util.client.shortcut_handler import bond_shortcut
from util.client.show_tips import show_file_tips, show_mic_tips
from util.client.stream import stream_close, stream_open
from util.client.transcribe import transcribe_check, transcribe_recv, transcribe_send
from util.empty_working_set import empty_current_working_set

# 确保根目录位置正确，用相对路径加载模型
BASE_DIR = os.getcwd()
os.chdir(BASE_DIR)
# BASE_DIR = os.path.dirname(__file__); os.chdir(BASE_DIR)

# MacOS 的权限设置
if system() == "Darwin" and not sys.argv[1:]:
    if os.getuid() != 0:
        console.print("在 MacOS 上需要以管理员启动客户端才能监听键盘活动，请 sudo 启动")
        input("按回车退出")
        sys.exit()
    else:
        os.umask(0o000)


async def main_mic(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    Cosmic.loop = asyncio.get_event_loop()
    Cosmic.queue_in = asyncio.Queue()
    Cosmic.queue_out = asyncio.Queue()

    show_mic_tips()

    # 更新热词
    update_hot_all()

    # 实时更新热词
    observer = observe_hot()

    # 打开音频流
    Cosmic.stream = stream_open(logger=_logger)

    # Ctrl-C 关闭音频流，触发自动重启
    signal.signal(signal.SIGINT, stream_close)

    # 绑定按键
    bond_shortcut()

    # 清空物理内存工作集
    if system() == "Windows":
        empty_current_working_set()

    # 接收结果
    console.print(
        f"连接服务端...  （服务端载入模块时长约 50 秒，请耐心等待。若好几分钟了还无响应 -> 服务端软件 start_server_gui.exe 启动了吗？ 服务端地址当前设置 {Config.addr}:{Config.speech_recognition_port} 是正确的吗？）\n"
    )
    while True:
        try:
            await recv_result(logger=_logger)
        except Exception as e:
            if e.args[0] == "'ClientConnection' object has no attribute 'closed'":
                console.print(
                    "[bold red]连接已关闭，请检查服务端是否正常启动[/bold red]"
                )
            else:
                console.print(f"[bold red]连接服务端时出错: {e}[/bold red]")
            Cosmic.websocket = None
            console.print("[bold red]正在尝试重连...[/bold red]\n")


async def main_file(files: List[Path], logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    show_file_tips()

    for file in files:
        try:
            if file.suffix in [".txt", ".json", ".srt"]:
                adjust_srt(file)
            else:
                # 为每个文件重新建立连接
                await transcribe_check(file, logger=_logger)
                await asyncio.gather(
                    transcribe_send(file, logger=_logger),
                    transcribe_recv(file, logger=_logger),
                )
                console.print(f"[bold green]已完成转录: {file.name}[/bold green]")

                # 处理完成后关闭连接，为下一个文件做准备
                if Cosmic.websocket:
                    try:
                        await Cosmic.websocket.close()
                    except:
                        pass
                    Cosmic.websocket = None

        except Exception as e:
            console.print(f"[bold red]处理文件 {file.name} 时出错: {e}[/bold red]")

            _logger.error(f"处理文件 {file.name} 时出错: {e}")
            # 确保出错时重置连接
            if Cosmic.websocket:
                try:
                    await Cosmic.websocket.close()
                except:
                    pass
                Cosmic.websocket = None
            continue

    # 最终清理
    if Cosmic.websocket:
        try:
            await Cosmic.websocket.close()
        except:
            pass
    input("\n所有文件处理完成，按回车退出\n")


def init_mic(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    _logger.info("开始从麦克风转录")
    try:
        asyncio.run(main_mic(logger=_logger))
    except KeyboardInterrupt:
        console.print("再见！")
    finally:
        console.print("...")
        sys.exit()


def init_file(files: List[Path], logger: Optional[Logger] = None):
    """
    用 CapsWriter Server 转录音视频文件，生成 srt 字幕
    """
    _logger = logger if logger is not None else default_logger
    _logger.info(f"开始转录文件，参数：{files}")
    try:
        asyncio.run(main_file(files))
    except KeyboardInterrupt:
        console.print("再见！")
        _logger.info("用户中断，退出程序")
    finally:
        sys.exit()


if __name__ == "__main__":
    # 如果参数传入文件，那就转录文件
    # 如果没有多余参数，就从麦克风输入
    ctx = mul.get_context("spawn")
    SafeLogger(mp_context=ctx)
    default_logger.info("Starting core client...")
    default_logger.trace(f"argv: {sys.argv}")
    if sys.argv[1:]:
        typer.run(
            init_file(files=[Path(f) for f in sys.argv[1:]], logger=default_logger)
        )
    else:
        init_mic(logger=default_logger)
