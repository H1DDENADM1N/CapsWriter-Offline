# coding: utf-8

import asyncio
import os
import signal
import sys
from pathlib import Path
from platform import system
from typing import List

import colorama
import typer

from util.client_cosmic import Cosmic, console
from util.config import ClientConfig as Config

if sys.argv[1:]:
    Cosmic.transcribe_subtitles = True
else:
    Cosmic.transcribe_subtitles = False
from util.client_adjust_srt import adjust_srt
from util.client_hot_update import observe_hot, update_hot_all
from util.client_recv_result import recv_result
from util.client_shortcut_handler import bond_shortcut
from util.client_show_tips import show_file_tips, show_mic_tips
from util.client_stream import stream_close, stream_open
from util.client_transcribe import transcribe_check, transcribe_recv, transcribe_send
from util.empty_working_set import empty_current_working_set

# 确保根目录位置正确，用相对路径加载模型
BASE_DIR = os.getcwd()
os.chdir(BASE_DIR)
# BASE_DIR = os.path.dirname(__file__); os.chdir(BASE_DIR)

# 确保终端能使用 ANSI 控制字符
colorama.init()

# MacOS 的权限设置
if system() == "Darwin" and not sys.argv[1:]:
    if os.getuid() != 0:
        print("在 MacOS 上需要以管理员启动客户端才能监听键盘活动，请 sudo 启动")
        input("按回车退出")
        sys.exit()
    else:
        os.umask(0o000)


async def main_mic():
    Cosmic.loop = asyncio.get_event_loop()
    Cosmic.queue_in = asyncio.Queue()
    Cosmic.queue_out = asyncio.Queue()

    show_mic_tips()

    # 更新热词
    update_hot_all()

    # 实时更新热词
    observer = observe_hot()

    # 打开音频流
    Cosmic.stream = stream_open()

    # Ctrl-C 关闭音频流，触发自动重启
    signal.signal(signal.SIGINT, stream_close)

    # 绑定按键
    bond_shortcut()

    # 清空物理内存工作集
    if system() == "Windows":
        empty_current_working_set()

    # 接收结果
    print(
        f"连接服务端...  （服务端载入模块时长约 50 秒，请耐心等待。若好几分钟了还无响应 -> 服务端软件 start_server_gui.exe 启动了吗？ 服务端地址当前设置 {Config.addr}:{Config.speech_recognition_port} 是正确的吗？）"
    )
    while True:
        await recv_result()


async def main_file(files: List[Path]):
    show_file_tips()

    for file in files:
        if file.suffix in [".txt", ".json", "srt"]:
            adjust_srt(file)
        else:
            await transcribe_check(file)
            await asyncio.gather(transcribe_send(file), transcribe_recv(file))

    if Cosmic.websocket:
        await Cosmic.websocket.close()
    input("\n按回车退出\n")


def init_mic():
    try:
        asyncio.run(main_mic())
    except KeyboardInterrupt:
        console.print("再见！")
    finally:
        print("...")


def init_file(files: List[Path]):
    """
    用 CapsWriter Server 转录音视频文件，生成 srt 字幕
    """
    try:
        asyncio.run(main_file(files))
    except KeyboardInterrupt:
        console.print("再见！")
        sys.exit()


if __name__ == "__main__":
    # 如果参数传入文件，那就转录文件
    # 如果没有多余参数，就从麦克风输入
    if sys.argv[1:]:
        typer.run(init_file)
    else:
        init_mic()
