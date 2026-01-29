import time
import warnings

warnings.filterwarnings("ignore", message=".*pkg_resources.*")
from multiprocessing import Queue
from pathlib import Path
from platform import system

import jieba
import sherpa_onnx
from loguru import logger as default_logger  # 备用 logger

from util.config import FunASRArgs, ModelPaths, ParaformerArgs, SenseVoiceArgs
from util.config import ServerConfig as Config
from util.empty_working_set import empty_current_working_set
from util.server.cosmic import console


def init_recognizer(
    priority_queue: Queue, queue_out: Queue, sockets_id, passed_logger
) -> None:
    # --- 辅助函数：确保传入的 logger 是可用的 ---
    # 虽然 passed_logger 应该总是存在，但加个保险防止意外
    log = passed_logger if passed_logger is not None else default_logger

    # 导入模块
    with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
        jieba.setLogLevel("INFO")
    try:
        # 只有在导入这些模块后才能设置
        from util.fun_asr_gguf import nano_llama, utils
        from util.fun_asr_gguf.hotword import rag_fast

        # 注入 logger，使得 llama.cpp 的日志和 vprint 的日志都通过 passed_logger 发送
        nano_llama.set_llama_logger(log)
        utils.set_utils_logger(log)
        rag_fast.set_rag_logger(passed_logger)

        log.debug("已将 logger 注入到 fun_asr_gguf 底层模块")
    except ImportError as e:
        log.warning(f"无法导入底层模块进行 logger 注入: {e}")
    except AttributeError as e:
        log.warning(f"底层模块似乎未实现 set_logger 接口: {e}")
    log.trace("模块加载完成")
    console.print("[green4]模块加载完成", end="\n\n")

    # 载入语音模型
    log.trace("语音模型载入中…")
    console.print("[yellow]语音模型载入中，载入时长约 20 秒，请耐心等待...")
    t1 = time.time()

    recognizer = None

    if Config.model == "Paraformer":
        from util.server.recognize_paraformer import recognize

        recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            **{
                key: value
                for key, value in ParaformerArgs.__dict__.items()
                if not key.startswith("_")
            }
        )

    elif Config.model == "Sensevoice":
        from util.server.recognize_sensevoice import recognize

        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            **{
                key: value
                for key, value in SenseVoiceArgs.__dict__.items()
                if not key.startswith("_")
            }
        )
    else:
        from util.fun_asr_gguf.asr_engine import create_asr_engine
        from util.fun_asr_gguf.hotword.manager import get_hotword_manager
        from util.server.recognize_funasr import recognize

        # 传入 logger 给热词管理器
        # 这样后续在该子进程中任何地方调用 get_hotword_manager() 都能拿到安全的 logger
        hotword_mgr = get_hotword_manager(
            hotword_file=Path(
                ModelPaths.funasr_hotwords_path
            ),  # 建议从 Config 读取路径
            threshold=0.7,  # 建议从 Config 读取阈值
            logger=log,  # <--- 注入多进程安全的 logger
        )
        # 加载热词数据
        hotword_mgr.load()
        # 传入 logger 给 FunASR 引擎
        recognizer = create_asr_engine(
            logger=log,  # <--- 传递 logger
            **{
                key: value
                for key, value in FunASRArgs.__dict__.items()
                if not key.startswith("_")
            },
        )
        log.trace("热词管理器初始化中...")
        log.trace("热词管理器初始化完成")

    log.success("语音模型载入完成")
    console.print("[green4]语音模型载入完成", end="\n\n")

    if Config.model == "Paraformer":
        # 载入标点模型
        log.trace("标点模型载入中...")
        punc_model = None
        if Config.format_punc:
            console.print("[yellow]标点模型载入中，载入时长约 50 秒，请耐心等待...")
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
            log.success("标点模型载入完成")
            console.print("[green4]标点模型载入完成", end="\n\n")

    console.print(f"模型加载耗时 {time.time() - t1:.2f}s", end="\n\n")
    log.success(f"模型加载耗时 {time.time() - t1:.2f}s")

    # 清空物理内存工作集
    if system() == "Windows":
        empty_current_working_set()

    queue_out.put(True)  # 通知主进程加载完了

    while True:
        # 从优先级队列中获取任务消息
        try:
            task = priority_queue.get(timeout=1)
        except Exception as e:
            log.error(f"从优先级队列中获取任务消息时出错: {e}", exc_info=True)
            continue

        # 添加 None 检查
        if task is None:
            continue

        if task.socket_id not in sockets_id:  # 检查任务所属的连接是否存活
            log.warning(
                f"连接已关闭，放弃识别任务，任务ID：{task.task_id}，Socket ID：{task.socket_id}"
            )
            continue

        # 执行识别
        try:
            if Config.model == "Paraformer":
                result = recognize(
                    recognizer, punc_model=punc_model, task=task, logger=log
                )
            elif Config.model == "Sensevoice":
                result = recognize(recognizer, task=task, logger=log)
            else:
                result = recognize(recognizer, task=task, logger=log)

            queue_out.put(result)
        except Exception as e:
            log.error(f"识别任务出错: {e}", exc_info=True)
            queue_out.put(None)  # 或者放入错误信息对象
