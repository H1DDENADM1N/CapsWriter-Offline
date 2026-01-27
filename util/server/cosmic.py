import io
import sys
from multiprocessing import Queue
from typing import Dict, List, Optional

import websockets

# from rich.console import Console
from util.resizeable_console import Console

original_stdout = sys.stdout
try:
    # 为 core_server 指定utf-8编码
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except AttributeError:
    # 为 mulitprocessing init_recognizer 指定默认编码
    sys.stdout = original_stdout

console = Console(highlight=False)


class Cosmic:
    """
    服务端全局状态容器

    存储服务端运行时的共享状态：
    - sockets: WebSocket 连接字典，以 socket_id 为键
    - sockets_id: 跨进程的 socket ID 列表（由 Manager 创建）
    - queue_in: 任务输入队列（主进程 -> 识别进程）
    - queue_out: 结果输出队列（识别进程 -> 主进程）

    Note:
        使用类变量而非实例变量，确保全局唯一。
        sockets_id 需要在 core_server.py 中使用 Manager().list() 初始化。
    """

    # WebSocket 连接池
    sockets: Dict[str, websockets.WebSocketClientProtocol] = {}

    # 跨进程共享的 socket ID 列表（需要用 Manager().list() 初始化）
    sockets_id: Optional[List] = None

    # 消息队列
    queue_in: Queue = Queue()
    queue_out: Queue = Queue()
