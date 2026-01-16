import io
import sys
from asyncio import Queue
from typing import List, Union

import sounddevice as sd
import websockets
from rich.theme import Theme

# from rich.console import Console
from util.resizeable_console import Console

original_stdout = sys.stdout
try:
    # 为 core_server 指定utf-8编码
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except AttributeError:
    # 为 mulitprocessing init_recognizer 指定默认编码
    sys.stdout = original_stdout

my_theme = Theme({"markdown.code": "cyan", "markdown.item.number": "yellow"})
console = Console(highlight=False, soft_wrap=False, theme=my_theme)


class Cosmic:
    """
    用一个 class 存储需要跨模块访问的变量值，命名为 Cosmic
    """

    on = False
    queue_in: Queue
    queue_out: Queue
    websocket: websockets.WebSocketClientProtocol = None
    client_id = None
    audio_files = {}
    stream: Union[None, sd.InputStream] = None
    kwd_list: List[str] = []
    transcribe_subtitles = False
    online_translate_needed = False
    offline_translate_needed = False
    opposite_state = False
