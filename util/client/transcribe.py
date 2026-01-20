import asyncio
import base64
import json
import re
import sys
import time
import traceback
import uuid
from pathlib import Path

import websockets
from loguru import logger

from util.client import srt_from_txt
from util.client.check_websocket import check_websocket
from util.client.cosmic import Cosmic, console
from util.client.hot_sub import hot_sub
from util.client.hot_update import observe_hot, update_hot_all
from util.client.welcome import handle_welcome_message
from util.config import ClientConfig as Config
from util.safe_logger import init_logging


async def transcribe_check(file: Path):
    init_logging()
    # 检查连接
    if not await check_websocket():
        console.print("无法连接到服务端", style="bright_red")
        logger.error("无法连接到服务端")
        sys.exit()

    if not file.exists():
        console.print(f"文件不存在：{file}", style="bright_red")
        logger.error(f"文件不存在：{file}")
        return False


async def transcribe_send(file: Path):
    init_logging()
    websocket = Cosmic.websocket  # 获取连接

    # 生成任务id
    task_id = str(uuid.uuid1())
    console.print(f"\n任务标识：{task_id}")
    logger.debug(f"任务标识：{task_id}")
    console.print(f"    处理文件：{file}")
    logger.debug(f"    处理文件：{file}")

    # 获取音频数据，ffmpeg输出采样率16000，单声道，float32格式
    ffmpeg_cmd = [
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

    process = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    console.print("    正在提取音频", end="\r")
    logger.debug("    正在提取音频")

    # 计算音频总长度
    audio_data = await process.stdout.read()
    audio_duration = len(audio_data) / 4 / 16000
    console.print(f"    音频长度：{audio_duration:.2f}s")
    logger.debug(f"    音频长度：{audio_duration:.2f}s")

    # 分块大小，例如60秒
    chunk_size = 16000 * 4 * 60  # 16000采样率，4字节每个样本，60秒

    offset = 0
    time_start = time.time()
    while offset < len(audio_data):
        chunk_end = offset + chunk_size
        if chunk_end > len(audio_data):
            chunk_end = len(audio_data)
        is_final = True if chunk_end >= len(audio_data) else False
        data_chunk = audio_data[offset:chunk_end]
        time_frame = time_start + (offset / 4 / 16000)
        message = {
            "task_id": task_id,  # 任务ID
            "seg_duration": Config.file_seg_duration,  # 分段长度
            "seg_overlap": Config.file_seg_overlap,  # 分段重叠
            "is_final": is_final,  # 是否结束
            "time_start": time_start,  # 录音起始时间
            "time_frame": time_frame,  # 该帧时间
            "source": "file",  # 数据来源：从文件读的数据
            "data": base64.b64encode(data_chunk).decode("utf-8"),
        }
        offset = chunk_end
        progress = min(offset / 4 / 16000, audio_duration)
        try:
            await websocket.send(json.dumps(message))
            console.print(f"    发送进度：{progress:.2f}s", end="\r")
        except websockets.exceptions.ConnectionClosed as e:
            console.print(f"    连接断开，错误：{e}")
            logger.error(f"连接断开，错误：{e}")
            # 处理连接断开的情况，例如重新连接或终止任务
            break
        if is_final:
            logger.debug("    音频数据发送完毕")
            break

    # 等待ffmpeg进程结束
    await process.wait()


async def transcribe_recv(file: Path):
    init_logging()

    # 检查连接是否有效
    if Cosmic.websocket is None:
        console.print("[red]WebSocket连接不存在，无法接收结果[/red]")
        logger.error("WebSocket连接不存在，无法接收结果")
        return

    # 更新热词
    update_hot_all()
    # 实时更新热词
    observer = observe_hot()

    try:
        # 先接收服务端的欢迎消息
        if not await handle_welcome_message():
            console.print("[bold red]无法建立连接或接收欢迎消息[/bold red]")
            return

        # 接收结果
        async for message in Cosmic.websocket:
            message = json.loads(message)
            console.print(f"    转录进度: {message['duration']:.2f}s", end="\r")
            if message["is_final"]:
                logger.debug("    收到最终转录结果")
                break

        # 解析结果
        text_merge = message["text"]
        # 热词替换
        text_merge = hot_sub(text_merge)
        # text_split = re.sub("[，。？]", "\n", text_merge)
        text_split = re.sub("([，。？])", r"\1\n", text_merge)
        timestamps = message["timestamps"]
        tokens = message["tokens"]

        # 得到文件名
        json_filename = Path(file).with_suffix(".json")
        txt_filename = Path(file).with_suffix(".txt")
        merge_filename = Path(file).with_suffix(".merge.txt")

        # 写入结果
        with open(merge_filename, "w", encoding="utf-8") as f:
            f.write(text_merge)
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(text_split)
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(
                {"timestamps": timestamps, "tokens": tokens}, f, ensure_ascii=False
            )
        srt_from_txt.one_task(txt_filename)

        process_duration = message["time_complete"] - message["time_start"]
        console.print(f"\033[K    处理耗时：{process_duration:.2f}s")
        logger.debug(f"    处理耗时：{process_duration:.2f}s")
        console.print(f"    识别结果：\n[green]{text_merge}")
        logger.debug(f"    识别结果：\n{message['text']}")

    except websockets.exceptions.ConnectionClosed as e:
        console.print(f"[red]连接已关闭，无法接收文件 {file.name} 的结果: {e}[/red]")
        logger.error(f"连接已关闭，无法接收文件 {file.name} 的结果: {e}")
    except Exception as e:
        console.print(f"[red]接收文件 {file.name} 的结果时出错: {e}[/red]")
        logger.error(f"接收文件 {file.name} 的结果时出错: {e}")
        traceback.print_exc()
    finally:
        # 确保停止文件观察器
        if observer:
            observer.stop()
            observer.join()
