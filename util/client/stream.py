import asyncio
import sys
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd
from loguru import logger as default_logger
from loguru._logger import Logger

from util.client.cosmic import Cosmic, console
from util.config import ClientConfig as Config


def record_callback(
    indata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags
) -> None:
    if not Cosmic.on:
        return
    asyncio.run_coroutine_threadsafe(
        Cosmic.queue_in.put(
            {
                "type": "data",
                "time": time.time(),
                "data": indata.copy(),
            },
        ),
        Cosmic.loop,
    )


def stream_close(signum, frame):
    Cosmic.stream.close()


def drain_queue_in(logger: Optional[Logger] = None) -> int:
    """
    排空 Cosmic.queue_in 中残留的脏数据（只清 pending，不动正在处理的数据）。

    ported from upstream 4e3505f：取消录音后，本会话 begin 以及阈值前积攒的
    data 可能还残留在全局 queue_in 中（该队列由所有录音会话共用），若不清理,
    下一次录音会读到带旧任务语义的脏数据，导致「前文丢失/旧结果混入」的串线问题。
    """
    _logger = logger if logger is not None else default_logger
    drained = 0
    while True:
        try:
            Cosmic.queue_in.get_nowait()
            Cosmic.queue_in.task_done()
            drained += 1
        except asyncio.QueueEmpty:
            break
    if drained:
        _logger.debug(f"已排空 queue_in 残留 {drained} 条")
    return drained


def stream_reopen(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    if not threading.main_thread().is_alive():
        return
    console.print("重启音频流")
    _logger.trace("重启音频流")

    # 关闭旧流
    Cosmic.stream.close()

    # 重载 PortAudio，更新设备列表
    sd._terminate()
    sd._ffi.dlclose(sd._lib)
    sd._lib = sd._ffi.dlopen(sd._libname)
    sd._initialize()

    # 打开新流
    time.sleep(0.1)
    Cosmic.stream = stream_open(logger=_logger)


def stream_open(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    # 显示录音所用的音频设备

    channels = 1
    try:
        device = sd.query_devices(kind="input")
        device_name = device["name"]
        channels = min(2, device["max_input_channels"])
        console.print(
            f"使用默认音频设备：[italic]{device_name}，声道数：{channels}", end="\n\n"
        )
        _logger.debug(f"使用默认音频设备：{device_name}，声道数：{channels}")
    except UnicodeDecodeError:
        console.print(
            "由于编码问题，暂时无法获得麦克风设备名字", end="\n\n", style="bright_red"
        )
        _logger.error("由于编码问题，暂时无法获得麦克风设备名字")
    except sd.PortAudioError:
        console.print("没有找到麦克风设备", end="\n\n", style="bright_red")
        _logger.error("没有找到麦克风设备")
        input("按回车键退出")
        sys.exit()

    if Config.only_enable_microphones_when_pressed_record_shortcut:
        stream = sd.InputStream(
            samplerate=48000,
            blocksize=int(0.05 * 48000),  # 0.05 seconds
            device=None,
            dtype="float32",
            channels=channels,
            callback=record_callback,
            # finished_callback=stream_reopen,
        )  # stream.start()
    else:
        stream = sd.InputStream(
            samplerate=48000,
            blocksize=int(0.05 * 48000),  # 0.05 seconds
            device=None,
            dtype="float32",
            channels=channels,
            callback=record_callback,
            finished_callback=lambda: stream_reopen(logger=_logger),
        )
        stream.start()

    return stream
