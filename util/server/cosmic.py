import io
import sys
from multiprocessing import Queue
from typing import Dict, List

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
    sockets: Dict[str, websockets.WebSocketClientProtocol] = {}
    sockets_id: List
    queue_in = Queue()
    queue_out = Queue()
