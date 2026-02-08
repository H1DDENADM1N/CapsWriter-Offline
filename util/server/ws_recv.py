import json
import time
import uuid
from base64 import b64decode

import websockets
from loguru import logger

from util.constants import AudioFormat
from util.my_status import Status
from util.server.classes import Task
from util.server.cosmic import Cosmic, console

status_mic = Status("正在接收音频", spinner="point")


class AudioCache:
    """
    音频缓冲区

    用于缓存接收到的音频数据，直到达到分段阈值后提交处理。
    """

    def __init__(self):
        self.chunks: bytes = b""  # 音频数据缓冲
        self.offset: float = 0.0  # 当前偏移时间（秒）
        self.byte_count: int = 0  # 累计接收字节数

    @property
    def duration(self) -> float:
        """缓冲区音频时长（秒）"""
        return AudioFormat.bytes_to_seconds(len(self.chunks))

    @property
    def total_duration(self) -> float:
        """累计接收的音频总时长（秒）"""
        return AudioFormat.bytes_to_seconds(self.byte_count)

    def reset(self) -> None:
        """重置缓冲区"""
        self.chunks = b""
        self.offset = 0.0
        self.byte_count = 0


async def message_handler(websocket, message, cache: AudioCache):
    """处理得到的音频流数据"""

    # 使用优先级队列
    priority_queue = Cosmic.priority_queue_in

    global status_mic
    source = message["source"]
    is_final = message["is_final"]
    is_start = not bool(cache.chunks)

    # 获取 id
    task_id = message["task_id"]
    socket_id = str(websocket.id)

    # 获取麦克风听写时分段重叠
    seg_overlap = message["seg_overlap"]

    # 实时粘贴分段长度（从客户端消息获取，用于中间结果）
    realtime_seg_duration = message.get("realtime_paste_interval", 5)
    if realtime_seg_duration > 0:
        # 确保最小值为1秒，避免过于频繁的分段
        realtime_seg_duration = max(realtime_seg_duration, 1)
        realtime_seg_overlap = 1
        realtime_seg_threshold = realtime_seg_duration + realtime_seg_overlap * 2
    else:
        # 如果为0，禁用实时粘贴，设置一个很大的阈值
        realtime_seg_threshold = float("inf")

    # 根据来源设置优先级
    if source == "mic":
        priority = 1  # 麦克风输入：高优先级
    elif source == "file":
        priority = 10  # 文件转录：低优先级
    else:
        priority = 10  # 默认低优先级

    # base64 解码音频数据，再
    # 音频数据是 float32、单声道、16000采样率
    data = b64decode(message["data"])
    cache.chunks += data
    cache.byte_count += len(data)

    if not is_final:
        # 打印消息
        if source == "mic":
            status_mic.start()
        if source == "file" and is_start:
            console.print("正在接收音频文件...")

            logger.info(
                f"正在接收音频文件..., 任务ID：{task_id}, Socket ID：{socket_id}"
            )

        # 若缓冲已达到分段长度，将片段作为任务提交
        while len(cache.chunks) / 4 / 16000 >= realtime_seg_threshold:
            # 转换为整数，避免浮点数切片错误
            chunk_size = int(4 * 16000 * (realtime_seg_duration + realtime_seg_overlap))
            advance_size = int(4 * 16000 * realtime_seg_duration)
            data = cache.chunks[:chunk_size]
            cache.chunks = cache.chunks[advance_size:]
            task = Task(
                source=message["source"],
                data=data,
                offset=cache.offset,
                task_id=task_id,
                socket_id=socket_id,
                overlap=realtime_seg_overlap,
                is_final=False,
                time_start=message["time_start"],
                time_submit=time.time(),
            )
            cache.offset += realtime_seg_duration
            # 使用优先级队列
            priority_queue.put(task, priority)

    elif is_final:
        # 打印消息
        if source == "mic":
            status_mic.stop()
        elif source == "file":
            print(f"音频文件接收完毕，时长 {cache.total_duration:.2f}s")

            logger.info(
                f"音频文件接收完毕，任务ID: {task_id}, 时长: {cache.total_duration:.2f}s"
            )

        # 客户端说片段结束，将缓冲区音频识别
        task = Task(
            source=message["source"],
            data=cache.chunks[0:],
            offset=cache.offset,
            task_id=task_id,
            socket_id=socket_id,
            overlap=seg_overlap,
            is_final=True,
            time_start=message["time_start"],
            time_submit=time.time(),
        )
        # 使用优先级队列
        priority_queue.put(task, priority)
        logger.debug(
            f"提交最终片段，任务ID: {task_id}, 数据大小: {len(cache.chunks)} bytes"
        )

        # 重置缓冲区
        cache.reset()


async def ws_recv(websocket):
    client_id = f"client_{uuid.uuid4().hex[:8]}"

    # 登记 socket 到字典，以 socket id 字符串为索引
    sockets = Cosmic.sockets
    sockets_id = Cosmic.sockets_id
    sockets[str(websocket.id)] = websocket
    sockets_id.append(str(websocket.id))

    # 显示连接信息，同时显示两个ID
    with console.resize(width=44):
        console.rule("[green]连接成功")
    console.print(f"服务端 WebSocket ID: [dim]{websocket.id}[/dim]\n", style="")
    console.print(f"客户端地址: [dim]{websocket.remote_address}[/dim]", style="")
    console.print(f"客户端ID: [cyan]{client_id}[/cyan]", style="")
    console.print()

    logger.info(f"新客户端连接: 客户端ID={client_id}, WebSocket ID={websocket.id}")

    # 发送客户端ID给客户端
    try:
        welcome_message = {
            "type": "connection_ack",
            "client_id": client_id,
            "server_websocket_id": str(websocket.id),
            "remote_address": str(websocket.remote_address),
            "timestamp": time.time(),
        }
        await websocket.send(json.dumps(welcome_message))
        logger.info(
            f"[dim]已发送客户端ID给客户端: 服务端分配的客户端ID={client_id}, 服务端WebSocket ID={websocket.id}[/dim]"
        )

    except Exception as e:
        console.print(f"[red]发送欢迎消息失败: {e}[/red]")

    # 片段缓冲区、偏移时长
    cache = AudioCache()

    # 接收数据
    try:
        async for message in websocket:
            # json 解码字符串
            message = json.loads(message)

            # 处理数据
            await message_handler(websocket, message, cache)

        console.print(
            "ConnectionClosed...",
        )
        logger.info("ConnectionClosed...")
    except websockets.exceptions.ConnectionClosedError:
        console.print("ConnectionClosed...\n")
        logger.error("ConnectionClosedError..., socket closed unexpectedly")
    except websockets.ConnectionClosed:
        console.print(
            "ConnectionClosed...",
        )
        logger.error("ConnectionClosed..., socket closed normally")
    except websockets.InvalidState:
        console.print("InvalidState...")
        logger.error("InvalidState..., invalid websocket state")
    except Exception as e:
        console.print("Exception:", e)
        logger.error(f"Exception in ws_recv: {e}")
    finally:
        status_mic.stop()
        status_mic.on = False
        sockets.pop(str(websocket.id))
        if str(websocket.id) in sockets_id:
            sockets_id.remove(str(websocket.id))
        if str(websocket.id) in Cosmic.sockets_id:
            Cosmic.sockets_id.remove(str(websocket.id))
