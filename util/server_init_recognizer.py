import time
import sherpa_onnx
from multiprocessing import Queue
import signal
from platform import system
from config import ServerConfig as Config
from config import ParaformerArgs, ModelPaths
from util.server_cosmic import console
from util.server_recognize import recognize
from util.empty_working_set import empty_current_working_set


def disable_jieba_debug():
    # 关闭 jieba 的 debug
    import jieba
    import logging

    jieba.setLogLevel(logging.INFO)


def init_recognizer(queue_in: Queue, queue_out: Queue, sockets_id):
    # Ctrl-C 退出
    signal.signal(signal.SIGINT, lambda signum, frame: exit())

    # 导入模块
    with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
        import sherpa_onnx

    console.print("[green4]模块加载完成", end="\n\n")

    # 载入语音模型
    console.print("[yellow]语音模型载入中，载入时长约 20 秒，请耐心等待...", end="\r")
    t1 = time.time()
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        **{
            key: value
            for key, value in ParaformerArgs.__dict__.items()
            if not key.startswith("_")
        }
    )
    console.print(f"[green4]语音模型载入完成", end="\n\n")

    # 清空物理内存工作集
    if system() == "Windows":
        empty_current_working_set()

    queue_out.put(True)  # 通知主进程加载完了

    while True:
        # 从队列中获取任务消息
        # 阻塞最多1秒，便于中断退出
        try:
            task = queue_in.get(timeout=1)
        except:
            continue

        if task.socket_id not in sockets_id:  # 检查任务所属的连接是否存活
            continue

        result = recognize(recognizer, task)  # 执行识别
        queue_out.put(result)  # 返回结果
