import signal
import time
from multiprocessing import Queue
from platform import system

from config import ModelPaths, ParaformerArgs, SenseVoiceArgs
from config import ServerConfig as Config
from util.empty_working_set import empty_current_working_set
from util.server_cosmic import console

if Config.model == "Paraformer":
    from util.server_recognize_paraformer import recognize
else:
    from util.server_recognize_sensevoice import recognize


def disable_jieba_debug():
    # 关闭 jieba 的 debug
    import logging

    import jieba

    jieba.setLogLevel(logging.INFO)


def init_recognizer(queue_in: Queue, queue_out: Queue, sockets_id):
    # Ctrl-C 退出
    signal.signal(signal.SIGINT, lambda signum, frame: exit())

    # 导入模块
    with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
        import sherpa_onnx

        if Config.model == "Paraformer":
            from funasr_onnx import CT_Transformer
        disable_jieba_debug()

    console.print("[green4]模块加载完成", end="\n\n")

    # 载入语音模型
    console.print("[yellow]语音模型载入中，载入时长约 20 秒，请耐心等待...", end="\r")
    t1 = time.time()
    if Config.model == "Paraformer":
        recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            **{
                key: value
                for key, value in ParaformerArgs.__dict__.items()
                if not key.startswith("_")
            }
        )
    else:
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            **{
                key: value
                for key, value in SenseVoiceArgs.__dict__.items()
                if not key.startswith("_")
            }
        )
    console.print("[green4]语音模型载入完成", end="\n\n")

    if Config.model == "Paraformer":
        # 载入标点模型
        punc_model = None
        if Config.format_punc:
            console.print(
                "[yellow]标点模型载入中，载入时长约 50 秒，请耐心等待...", end="\r"
            )
            punc_model = CT_Transformer(ModelPaths.punc_model_dir, quantize=True)
            console.print("[green4]标点模型载入完成", end="\n\n")

    console.print(f"模型加载耗时 {time.time() - t1 :.2f}s", end="\n\n")

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

        if Config.model == "Paraformer":
            result = recognize(recognizer, punc_model, task)  # 执行识别
        else:
            result = recognize(recognizer, task)  # 执行识别

        queue_out.put(result)  # 返回结果
