import multiprocessing
import sys
import threading
from pathlib import Path

from loguru import logger

from util.config import DebugConfig


class SafeLogger:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, mp_context=None):
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            if mp_context is None:
                try:
                    self.mp_context = multiprocessing.get_context("fork")
                except ValueError:
                    self.mp_context = multiprocessing.get_context()
            else:
                self.mp_context = mp_context

            self.log_dir = Path("logs")
            self.setup_logging()
            self._initialized = True

    # --- 修复 AttributeError ---
    def __getattr__(self, name):
        return getattr(logger, name)

    def get_script_name(self) -> str:
        try:
            main_module = sys.modules.get("__main__")
            if (
                main_module
                and hasattr(main_module, "__file__")
                and main_module.__file__
            ):
                script_path = Path(main_module.__file__)
                return script_path.stem
        except (AttributeError, KeyError):
            pass

        try:
            if sys.argv and sys.argv[0]:
                script_path = Path(sys.argv[0])
                return script_path.stem
        except (IndexError, AttributeError):
            pass

        return "python_script"

    def get_log_file_path(self) -> Path:
        script_name = self.get_script_name()
        safe_script_name = "".join(
            c for c in script_name if c.isalnum() or c in ("_", "-")
        ).rstrip()
        if not safe_script_name:
            safe_script_name = "python_script"
        return self.log_dir / f"{safe_script_name}.log"

    def setup_logging(self):
        logger.remove()
        self.log_dir.mkdir(exist_ok=True)

        log_file = self.get_log_file_path()
        log_level = DebugConfig.logger_level

        # 确保这里只有文件 sink，这样 logger 对象才能被 pickle 传给子进程
        logger.add(
            sink=str(log_file),
            rotation="10 MB",
            retention="7 days",
            enqueue=True,
            context=self.mp_context,
            level=log_level,
            backtrace=True,
            diagnose=True,
            catch=True,
        )


def worker(passed_logger):
    # 子进程接收到的 logger 只有文件 handler，它会通过 Queue 发回主进程
    passed_logger.info("Worker process started")
    for i in range(5):
        passed_logger.info(f"Worker message {i}")
    passed_logger.info("Worker process finished")


if __name__ == "__main__":
    # Windows 下使用 spawn
    ctx = multiprocessing.get_context("spawn")

    # 1. 初始化 Logger (此时只有文件日志，对象是 Picklable 的)
    SafeLogger(mp_context=ctx)

    # 获取 logger 对象用于传递
    main_logger = logger

    # 2. 创建子进程，此时 pickle 参数不会报错
    p = ctx.Process(target=worker, args=(main_logger,))
    p.start()

    # 在子进程启动后，为主进程单独添加控制台输出
    # 这样既不影响子进程接收 logger，又能让主进程在屏幕看到日志
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logger.add(
        sink=sys.stderr,
        level=DebugConfig.logger_level,
        catch=True,
    )

    main_logger.info("Main process started")
    main_logger.info("Child process started")

    p.join()
    main_logger.info("Child process finished")
