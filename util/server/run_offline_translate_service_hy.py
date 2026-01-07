# 启动离线翻译服务（简化版）

import asyncio
import json

import websockets
from loguru import logger
from transformers import AutoModelForCausalLM, AutoTokenizer

from util.config import ClientConfig, ModelPaths
from util.config import ServerConfig as Config
from util.safe_logger import init_logging

# 离线翻译模型名称
modelName = ModelPaths.hy_mt_dir

# 全局变量
model = None
tokenizer = None


def init_model():
    """初始化模型"""
    global model, tokenizer
    try:
        logger.info(f"开始加载离线翻译模型: {modelName}")
        # 加载模型
        model = AutoModelForCausalLM.from_pretrained(
            modelName, local_files_only=True, device_map="auto"
        )
        # 加载分词器
        tokenizer = AutoTokenizer.from_pretrained(modelName, local_files_only=True)
        logger.info("离线翻译模型加载完成")
    except Exception as e:
        logger.error(f"加载离线翻译模型失败: {e}")
        raise


# 定义翻译函数
async def translate_text(text):
    if not model or not tokenizer:
        raise RuntimeError("模型未初始化")

    # 定义聊天消息
    messages = [
        {
            "role": "user",
            "content": "Translate the following segment into English, without additional explanation.\n\n"
            + text,
        },
    ]
    # 分词
    tokenized_chat = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False, return_tensors="pt"
    )

    # 获取离线翻译结果
    outputs = model.generate(tokenized_chat.to(model.device), max_new_tokens=2048)
    translated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # 去除提示词部分
    translated_text = translated_text.replace(
        "Translate the following segment into English, without additional explanation.\n\n",
        "",
    ).strip()
    # 去除原文部分，只保留翻译结果
    if text in translated_text:
        translated_text = translated_text.replace(text, "").strip()
    # 去除 换行符
    translated_text = translated_text.replace("\n", " ").strip()

    return translated_text


# 定义WebSocket处理函数
async def offline_translate_server(websocket, path=None):
    """处理WebSocket连接"""
    client_address = websocket.remote_address
    logger.info(f"客户端连接来自: {client_address}")

    try:
        async for message in websocket:
            logger.info(f"收到消息: {message}")
            try:
                data = json.loads(message)
                text_to_translate = data.get("text", "")

                if not text_to_translate:
                    await websocket.send(json.dumps({"error": "文本内容为空"}))
                    continue

                # 调用翻译函数
                translated_text = await translate_text(text_to_translate)
                logger.info(f"翻译结果: {translated_text}")

                # 将离线翻译结果发送回客户端
                await websocket.send(json.dumps({"translated_text": translated_text}))
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"error": "JSON格式错误"}))
            except Exception as e:
                logger.error(f"翻译处理错误: {e}")
                await websocket.send(json.dumps({"error": str(e)}))
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"客户端断开连接: {client_address}")
    except Exception as e:
        logger.error(f"WebSocket连接错误: {e}")


async def main():
    """主异步函数"""
    init_logging()

    # 初始化模型
    init_model()

    # 启动服务器
    async with websockets.serve(
        offline_translate_server,
        ClientConfig.addr,
        Config.offline_translate_port,
        ping_interval=20,
        ping_timeout=20,
    ) as server:
        logger.info(
            f"离线翻译服务启动在 {ClientConfig.addr}:{Config.offline_translate_port}"
        )
        logger.info("按 Ctrl+C 停止服务")

        # 保持服务器运行
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("离线翻译服务器被用户中断")
    except Exception as e:
        logger.error(f"离线翻译服务器错误: {e}")
