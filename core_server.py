import asyncio
import multiprocessing as mul
import os
import sys
from multiprocessing import Manager, Process
from platform import system
from typing import Optional

import websockets
from loguru import logger as default_logger
from loguru._logger import Logger

from util.check_libretranslate_service import check_libretranslate_service
from util.config import ServerConfig as Config
from util.empty_working_set import empty_current_working_set
from util.safe_logger import SafeLogger
from util.server.check_model import check_model
from util.server.cosmic import Cosmic, console
from util.server.expand_funasr_hotwords import expand_funasr_hotwords
from util.server.init_recognizer import init_recognizer
from util.server.ws_recv import ws_recv
from util.server.ws_send import ws_send

if check_libretranslate_service():
    from util.server.run_online_translate_service_libretranslate import (
        run_online_translate_service,
    )
else:
    from util.server.run_online_translate_service import (
        run_online_translate_service,
    )

from util.server.run_offline_translate_service import (
    run_offline_translate_service,
)

# 确保 os.getcwd() 位置正确，用相对路径加载模型
BASE_DIR = os.getcwd()
os.chdir(BASE_DIR)
# BASE_DIR = os.path.dirname(__file__); os.chdir(BASE_DIR)


async def main(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    # 检查模型文件
    check_model(_logger)

    console.line(2)
    with console.resize(width=50):
        console.rule("[bold #d55252]CapsWriter Offline Server")
        console.line()
    console.print(
        "项目地址：[cyan underline]https://github.com/HaujetZhao/CapsWriter-Offline",
        end="\n\n",
    )
    console.print(f"当前基文件夹：[cyan underline]{BASE_DIR}", end="\n\n")
    console.print(
        f"绑定的服务地址：[cyan underline]{Config.addr}:{Config.speech_recognition_port}",
        end="\n\n",
    )

    console.print("载入模块中，载入时长约 50 秒，请耐心等待...")

    if Config.model == "FunASR" and Config.expand_funasr_hotwords:
        await expand_funasr_hotwords(_logger)  # Fun-ASR-Nano-GGUF 模型热词扩展功能

    # 跨进程列表，用于保存 socket 的 id，用于让识别进程查看连接是否中断
    Cosmic.sockets_id = Manager().list()

    # 负责识别的子进程
    recognize_process = Process(
        target=init_recognizer,
        args=(Cosmic.queue_in, Cosmic.queue_out, Cosmic.sockets_id, _logger),
        daemon=True,
    )
    recognize_process.start()
    Cosmic.queue_out.get()

    # 启动离线翻译 WebSocket服务器
    if Config.start_offline_translate_server:
        console.print("载入离线翻译模型中，载入时长约 20 秒，请耐心等待...")
        translate_offline_server_process = Process(
            target=run_offline_translate_service, args=(_logger,)
        )
        translate_offline_server_process.start()

    # 启动在线翻译服务器 LibreTranslate 或 DeepLX
    if Config.start_online_translate_server:
        if check_libretranslate_service():
            console.print("启动在线翻译 LibreTranslate 服务...")
        else:
            console.print("启动在线翻译 DeepLX 服务...")
        run_online_translate_service()
    with console.resize(width=44):
        console.rule("[green3]开始服务")
        console.line()

    # 清空物理内存工作集
    if system() == "Windows":
        empty_current_working_set()

    # 负责接收客户端数据的 coroutine
    recv = websockets.serve(
        ws_recv,
        Config.addr,
        Config.speech_recognition_port,
        subprotocols=["binary"],
        max_size=None,
    )

    # 负责发送结果的 coroutine
    send = ws_send()
    await asyncio.gather(recv, send)


def apply_vulkan_config(logger: Optional[Logger] = None):
    """根据配置应用 Vulkan 相关的环境变量"""
    _logger = logger if logger is not None else default_logger
    if not Config.vulkan_enable:
        # 强制禁用 Vulkan 推理
        os.environ["VK_ICD_FILENAMES"] = "none"
        _logger.info("GPU 加速: 已禁用 (vulkan_enable=False)")
    else:
        # 启用 Vulkan 并根据配置调整精度
        if Config.vulkan_force_fp32:
            os.environ["GGML_VK_DISABLE_F16"] = "1"
            _logger.info("GPU 加速: 已启用 Vulkan (强制 FP32 模式)")
        else:
            # 清理环境变量，确保不残留之前的设置
            os.environ.pop("GGML_VK_DISABLE_F16", None)
            _logger.info("GPU 加速: 已启用 Vulkan (自动精度模式)")


def init(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    try:
        if Config.model == "FunASR":
            apply_vulkan_config(logger=_logger)
        asyncio.run(main(logger=_logger))
    except KeyboardInterrupt:  # Ctrl-C 停止
        console.print("\n再见！")
        _logger.info("用户中断，退出程序")
    except OSError as e:  # 端口占用
        console.print(f"出错了：{e}", style="bright_red")
        _logger.error(f"核心服务器出错: {e}")
        console.input("...")
    except Exception as e:
        console.print(e)
        _logger.error(f"核心服务器出错: {e}")
    finally:
        Cosmic.queue_out.put(None)
        sys.exit(0)
        # os._exit(0)


if __name__ == "__main__":
    ctx = mul.get_context("spawn")
    SafeLogger(mp_context=ctx)
    default_logger.info("Starting core server...")
    init(logger=default_logger)
