import subprocess

from loguru import logger

from util.check_process import check_process
from util.explorer_token_downgrade import downgraded_via_explorer_token, is_admin
from util.safe_logger import init_logging


def stop_exe(exe_name: str):
    init_logging()

    try:
        logger.info(f"Stopping {exe_name}")
        proc = subprocess.Popen(
            f"taskkill /IM {exe_name} /F",
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            text=True,
        )
        stdout, stderr = proc.communicate()
        logger.debug(f"Taskkill output: {stdout}")
        if stderr:
            logger.error(f"Taskkill errors: {stderr}")
    except Exception as e:
        logger.error(f"Error stopping {exe_name}: {e}")


def start_exe(exe_name: str):
    init_logging()
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
    logger.info(f"Starting {exe_name}")
    logger.info(f"Start output: {stdout}")
    if stderr:
        logger.error(f"Start errors: {stderr}")


def stop_server():
    exe_name_list = [
        "start_server_gui.exe",
        "pythonw_CapsWriter_Server.exe",
        "deeplx_windows_amd64.exe",
    ]

    for exe_name in exe_name_list:
        stop_exe(exe_name)


def restart_server():
    stop_server()
    if is_admin():
        downgraded_via_explorer_token("start_server_gui.exe")
    else:
        start_exe("start_server_gui.exe")


if __name__ == "__main__":
    if check_process("start_server_gui.exe"):
        restart_server()
