import asyncio
import json

import websockets
from loguru import logger

from util.config import ClientConfig as Config


async def translate_text(
    text, url=f"ws://{Config.addr}:{Config.offline_translate_port}"
):
    # 设置要发送的数据
    data = {"text": text}
    # 将Python字典转换为JSON格式的字符串
    json_data = json.dumps(data)

    # 异步函数发送WebSocket请求并接收响应
    async with websockets.connect(url) as ws:
        await ws.send(json_data)
        response = await ws.recv()
        # 假设响应是JSON格式的字符串，将其转换回Python字典
        response_data = json.loads(response)
        # 假设字典中有一个'translated_text'键，返回它的值
        return response_data.get("translated_text", "Translation not available")


# 这个函数将启动翻译任务并返回离线翻译结果
async def translate_offline(text):
    try:
        # 创建一个任务来运行协程
        trans_text_task = asyncio.create_task(translate_text(text))
        # 等待翻译完成
        trans_text = await trans_text_task
        return trans_text
    except Exception as e:
        print(f"An error occurred: {e}")

        logger.error(f"离线翻译时出错: {e}")
        return None


async def main():
    text = "你好，世界！"
    trans_text = await translate_offline(text)
    print(trans_text)


if __name__ == "__main__":
    asyncio.run(main())
