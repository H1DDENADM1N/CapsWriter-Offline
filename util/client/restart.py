import subprocess
from typing import Optional

from loguru import logger as default_logger
from loguru._logger import Logger

from util.check_process import check_process


def stop_exe(exe_name: str, logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    try:
        _logger.info(f"Stopping {exe_name}")
        proc = subprocess.Popen(
            f"taskkill /IM {exe_name} /F",
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            text=True,
        )
        stdout, stderr = proc.communicate()
        _logger.debug(f"Taskkill output: {stdout}")
        if stderr:
            _logger.error(f"Taskkill errors: {stderr}")
    except Exception as e:
        _logger.error(f"Error stopping {exe_name}: {e}")


def start_exe(exe_name: str, logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    # print(f"Starting {exe_name}")
    proc = subprocess.Popen(
        f'start "" "{exe_name}"',
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        text=True,
    )
    stdout, stderr = proc.communicate()
    # print(f"{stdout}, {stderr}")
    _logger.info(f"Starting {exe_name}")
    _logger.info(f"Start output: {stdout}")
    if stderr:
        _logger.error(f"Start errors: {stderr}")


def stop_client(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    exe_name_list = [
        "start_client_gui_admin.exe",
        "start_client_gui.exe",
        "python_CapsWriter_Client.exe",
        "hint_while_recording.exe",
    ]

    for exe_name in exe_name_list:
        stop_exe(exe_name, logger=_logger)


def restart_client_admin(logger: Optional[Logger] = None):
    _logger = logger if logger is not None else default_logger
    stop_client(logger=_logger)
    start_exe("start_client_gui_admin.exe", logger=_logger)


def restart_client(logger: Optional[Logger] = None):
    stop_client(logger=logger)
    start_exe("start_client_gui.exe", logger=logger)


if __name__ == "__main__":
    import multiprocessing as mul
    import sys

    from util.config import DebugConfig
    from util.safe_logger import SafeLogger

    ctx = mul.get_context("spawn")
    SafeLogger(mp_context=ctx)
    default_logger.add(
        sink=sys.stderr,
        level=DebugConfig.logger_level,
        catch=True,
    )
    if check_process("start_client_gui_admin.exe", logger=default_logger):
        restart_client_admin(logger=default_logger)
    else:
        restart_client(logger=default_logger)
