import json

from loguru import logger

from util.server.asyncio_to_thread import to_thread
from util.server.classes import Result
from util.server.cosmic import Cosmic, console


async def ws_send():
    queue_out = Cosmic.queue_out
    sockets = Cosmic.sockets

    while True:
        try:
            # 获取识别结果（从多进程队列）
            result: Result = await to_thread(queue_out.get)

            # 得到退出的通知
            if result is None:
                return

            # 构建消息：仅在最终结果时发送 tokens/timestamps（中间结果不需要，减少 JSON 大小防止阻塞事件循环）
            message = {
                "task_id": result.task_id,
                "duration": result.duration,
                "time_start": result.time_start,
                "time_submit": result.time_submit,
                "time_complete": result.time_complete,
                "text": result.text,
                "is_final": result.is_final,
            }
            if result.is_final:
                message["tokens"] = result.tokens
                message["timestamps"] = result.timestamps

            # 获得 socket
            websocket = next(
                (ws for ws in sockets.values() if str(ws.id) == result.socket_id),
                None,
            )

            if not websocket:
                continue

            # 发送消息（json.dumps 可能因 tokens 列表过长阻塞事件循环，卸载到线程）
            await websocket.send(await to_thread(json.dumps, message))

            if result.source == "mic" and result.text != "":
                console.print(f"识别结果：\n    [green]{result.text}")
            elif result.source == "file":
                console.print(f"    转录进度：{result.duration:.2f}s", end="\r")
                if result.is_final:
                    console.print("\n    [green]转录完成")

        except Exception as e:
            print(e)

            logger.error(f"发送识别结果时出错: {e}")
