import json

from loguru import logger

from util.client.cosmic import Cosmic, console
from util.safe_logger import init_logging


async def handle_welcome_message():
    """
    处理服务端发送的欢迎消息，获取客户端ID和其他连接信息
    """
    try:
        init_logging()

        # 先接收服务端的欢迎消息
        welcome_message = await Cosmic.websocket.recv()
        welcome_data = json.loads(welcome_message)

        if welcome_data.get("type") == "connection_ack":
            # 获取服务端分配的客户端ID
            Cosmic.client_id = welcome_data["client_id"]
            server_websocket_id = welcome_data["server_websocket_id"]
            remote_address = welcome_data.get("remote_address", "未知")

            console.print(f"   服务端 WebSocket ID: [dim]{server_websocket_id}[/dim]\n")
            console.print(f"   客户端ID: [cyan]{Cosmic.client_id}[/cyan]")
            console.print()

            logger.info(
                f"连接到服务端成功: 服务端分配的客户端ID={Cosmic.client_id}, 客户端地址={remote_address}, "
                f"客户端 WebSocket ID={Cosmic.websocket.id}, 服务端WebSocket ID={server_websocket_id}"
            )

            return True
        else:
            logger.warning(f"收到意外的欢迎消息类型: {welcome_data.get('type')}")
            return False

    except json.JSONDecodeError as e:
        logger.error(f"解析欢迎消息JSON失败: {e}")
        return False
    except KeyError as e:
        logger.error(f"欢迎消息缺少必需字段: {e}")
        return False
    except Exception as e:
        logger.error(f"处理欢迎消息时出错: {e}")
        return False
