# 启动离线翻译服务

# 测试
# websocat ws://localhost:6017/
# {"text": "你好，世界！"}

# .\runtime\python.exe .\util\client\translate_offline.py


import asyncio
import json
from multiprocessing import Process

import websockets
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from util.config import ClientConfig, ModelPaths
from util.config import ServerConfig as Config

# 离线翻译
modelName = ModelPaths.opus_mt_dir
# 加载模型
model = AutoModelForSeq2SeqLM.from_pretrained(modelName, local_files_only=True)
# 加载分词器
tokenizer = AutoTokenizer.from_pretrained(modelName, local_files_only=True)


# 定义翻译函数
async def translate_text(text):
    # 分词
    input_ids = tokenizer.encode(text, return_tensors="pt")

    # 获取离线翻译结果
    outputs = model.generate(input_ids)
    translated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    return translated_text


# 定义WebSocket处理函数
async def offline_translate_server(websocket):
    global logger
    client_address = websocket.remote_address
    logger.info(f"客户端连接来自: {client_address}")

    async for message in websocket:
        logger.info(f"收到消息: {message}")
        data = json.loads(message)
        text_to_translate = data.get("text", "")

        # 调用翻译函数
        translated_text = await translate_text(text_to_translate)
        logger.info(f"翻译结果: {translated_text}")

        # 将离线翻译结果发送回客户端
        await websocket.send(json.dumps({"translated_text": translated_text}))


def run_offline_translate_service(passed_logger):
    global logger
    logger = passed_logger

    async def main():
        # 使用async with来管理服务器生命周期
        async with websockets.serve(
            offline_translate_server, ClientConfig.addr, Config.offline_translate_port
        ) as server:
            logger.trace(
                f"离线翻译服务启动在 {ClientConfig.addr}:{Config.offline_translate_port}"
            )
            await server.serve_forever()
            logger.success("离线翻译服务启动成功")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("离线翻译服务器被用户中断")
    except Exception as e:
        logger.error(f"离线翻译服务器错误: {e}")


if __name__ == "__main__":
    # 启动离线翻译 WebSocket服务器
    server_process = Process(target=run_offline_translate_service)
    server_process.start()
