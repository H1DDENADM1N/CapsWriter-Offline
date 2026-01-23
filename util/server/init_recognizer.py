import warnings

warnings.filterwarnings("ignore", message=".*pkg_resources.*", module="jieba._compat")


import logging
import time
from multiprocessing import Queue
from platform import system

import jieba
import sherpa_onnx
from loguru import logger

from util.config import FunASRArgs, ModelPaths, ParaformerArgs, SenseVoiceArgs
from util.config import ServerConfig as Config
from util.empty_working_set import empty_current_working_set
from util.safe_logger import init_logging
from util.server.cosmic import console

if Config.model == "Paraformer":
    from util.server.recognize_paraformer import recognize
elif Config.model == "Sensevoice":
    from util.server.recognize_sensevoice import recognize
else:
    from util.server.recognize_funasr import recognize


def disable_jieba_debug():
    # 关闭 jieba 的 debug
    jieba.setLogLevel(logging.INFO)


def init_recognizer(queue_in: Queue, queue_out: Queue, sockets_id):
    # 导入模块
    with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
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
    elif Config.model == "Sensevoice":
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            **{
                key: value
                for key, value in SenseVoiceArgs.__dict__.items()
                if not key.startswith("_")
            }
        )
    else:
        recognizer = sherpa_onnx.OfflineRecognizer.from_funasr_nano(
            **{
                key: value
                for key, value in FunASRArgs.__dict__.items()
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
            #     punc_model = CT_Transformer(ModelPaths.punc_model_dir, quantize=True)
            punc_model = sherpa_onnx.OfflinePunctuation(
                sherpa_onnx.OfflinePunctuationConfig(
                    model=sherpa_onnx.OfflinePunctuationModelConfig(
                        ct_transformer=(
                            ModelPaths.punc_model_dir / "model.onnx"
                        ).as_posix()
                    ),
                )
            )
            console.print("[green4]标点模型载入完成", end="\n\n")

    console.print(f"模型加载耗时 {time.time() - t1:.2f}s", end="\n\n")

    # 清空物理内存工作集
    if system() == "Windows":
        empty_current_working_set()

    queue_out.put(True)  # 通知主进程加载完了

    while True:
        # 从队列中获取任务消息
        # 阻塞最多1秒，便于中断退出
        try:
            task = queue_in.get(timeout=1)
        except Exception:
            continue

        if task.socket_id not in sockets_id:  # 检查任务所属的连接是否存活
            init_logging()

            logger.info(
                f"连接已关闭，放弃识别任务，任务ID：{task.task_id}，Socket ID：{task.socket_id}"
            )
            continue

        # 执行识别
        if Config.model == "Paraformer":
            result = recognize(recognizer, punc_model, task)
        elif Config.model == "Sensevoice":
            result = recognize(recognizer, task)
        else:
            result = recognize(recognizer, task)

        queue_out.put(result)  # 返回结果
