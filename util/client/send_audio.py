import asyncio
import base64
import json
import uuid

import numpy as np
import websockets
from loguru import logger
from websockets.protocol import State

from util.client.cosmic import Cosmic, console
from util.client.create_file import create_file
from util.client.finish_file import finish_file
from util.client.write_file import write_file
from util.config import ClientConfig as Config


async def send_message(message):
    # 发送数据
    if Cosmic.websocket is None or Cosmic.websocket.state in [
        State.CLOSED,
        State.CLOSING,
    ]:
        if message["is_final"]:
            task_id = message["task_id"]
            if task_id in Cosmic.audio_files:
                Cosmic.audio_files.pop(task_id)
                console.print("    服务端未连接，无法发送\n")
                logger.error(f"服务端未连接，任务ID：{task_id}，无法发送")
            else:
                console.print(f"    无法找到任务ID：{task_id}，无法移除\n")
                logger.error(f"无法找到任务ID：{task_id}，无法移除")
    else:
        try:
            await Cosmic.websocket.send(json.dumps(message))
        except websockets.ConnectionClosedError:
            if message["is_final"]:
                console.print("[red]连接中断了")
                logger.error("连接中断了，WebSocket连接关闭错误。is_final=True")
            logger.error("连接中断了，WebSocket连接关闭错误。is_final=False")
        except Exception as e:
            console.print("出错了")
            console.print(e)
            logger.error(f"发送消息时出错: {e}")


async def send_audio():
    try:
        # 生成唯一任务 ID
        task_id = str(uuid.uuid1())

        # 任务起始时间
        time_start = 0

        # 音频数据临时存放处
        cache = []
        duration = 0
        # 本任务是否已向服务端发送过音频帧。
        # 短于 threshold 的录音（误触短按 / 双击翻转）从未发出任何 data 帧，
        # finish/cancel 时不应再上传空片段：空片段会被服务端解码器熔斷成垃圾文本。
        has_sent_data = False

        # 保存音频文件
        file_path, file = "", None

        # 开始取数据
        # task: {'type', 'time', 'data'}
        while task := await Cosmic.queue_in.get():
            Cosmic.queue_in.task_done()
            if task["type"] == "begin":
                time_start = task["time"]
            elif task["type"] == "data":
                # 在阈值之前积攒音频数据
                if task["time"] - time_start < Config.threshold:
                    cache.append(task["data"])
                    continue

                # 创建音频文件
                if Config.save_audio and not file_path:
                    file_path, file = create_file(task["data"].shape[1], time_start)
                    Cosmic.audio_files[task_id] = file_path

                # 获取音频数据
                if cache:
                    data = np.concatenate(cache)
                    cache.clear()
                else:
                    data = task["data"]

                # 保存音频至本地文件
                duration += len(data) / 48000
                if Config.save_audio:
                    write_file(file, data)

                # 发送音频数据用于识别
                message = {
                    "task_id": task_id,  # 任务 ID
                    "seg_duration": Config.mic_seg_duration,  # 分段长度
                    "seg_overlap": Config.mic_seg_overlap,  # 分段重叠
                    "is_final": False,  # 是否结束
                    "time_start": time_start,  # 录音起始时间
                    "time_frame": task["time"],  # 该帧时间
                    "source": "mic",  # 数据来源：从麦克风收到的数据
                    "data": base64.b64encode(  # 数据
                        np.mean(data[::3], axis=1).tobytes()
                    ).decode("utf-8"),
                }
                has_sent_data = True
                task = asyncio.create_task(send_message(message))
            elif task["type"] == "finish":
                # 完成写入本地文件
                if Config.save_audio:
                    finish_file(file)

                console.print(f"任务标识：{task_id}")
                console.print(f"    录音时长：{duration:.2f}s")

                # 从未发送过音频帧（短于 threshold 的录音/双击翻转）：服务端没有已开始
                # 的片段，无需也不应上传空 final——空片段会被解码器熔斷成垃圾文本。
                if not has_sent_data:
                    console.print("    录音过短，未上传音频\n")
                    break

                # 告诉服务端音频片段结束了
                message = {
                    "task_id": task_id,
                    "seg_duration": Config.mic_seg_duration,  # 分段长度
                    "seg_overlap": Config.mic_seg_overlap,  # 分段重叠
                    "is_final": True,
                    "time_start": time_start,
                    "time_frame": task["time"],
                    "source": "mic",
                    "data": "",
                }
                task = asyncio.create_task(send_message(message))
                break
            elif task["type"] == "cancel":
                # ported from upstream 4e3505f：取消后兜底排空本会话残留的
                # 脏 data/begin 帧（只清 pending，不动正在处理的数据）
                drained = 0
                while True:
                    try:
                        Cosmic.queue_in.get_nowait()
                        Cosmic.queue_in.task_done()
                        drained += 1
                    except asyncio.QueueEmpty:
                        break
                if drained:
                    logger.debug(f"录音已取消，排空队列残留 {drained} 条")

                # 从未发送过音频帧（短于 threshold 的录音/双击翻转）：服务端没有已开始
                # 的片段，无需也不应上传空 final——空片段会被解码器熔斷成垃圾文本。
                if not has_sent_data:
                    break

                # 告诉服务端任务已取消
                message = {
                    "task_id": task_id,
                    "seg_duration": Config.mic_seg_duration,  # 分段长度
                    "seg_overlap": Config.mic_seg_overlap,  # 分段重叠
                    "is_final": True,
                    "time_start": time_start,
                    "time_frame": task["time"],
                    "source": "mic",
                    "data": "",
                }
                task = asyncio.create_task(send_message(message))
                break
    except Exception as e:
        console.print(e)

        logger.error(f"发送音频时出错: {e}")
