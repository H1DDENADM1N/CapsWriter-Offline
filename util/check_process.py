import ctypes
from ctypes import wintypes
from typing import Optional

import psutil
from loguru import logger as default_logger
from loguru._logger import Logger


def get_target_names(name):
    """
    获取要搜索的进程名列表
    """
    target_name = name.lower()
    search_names = [target_name]
    if target_name.endswith(".exe"):
        search_names.append(target_name[:-4])  # 去除.exe后缀
    return search_names


def is_process_match(proc_name, search_names):
    """
    检查进程名是否匹配搜索列表中的任一名称
    """
    if not proc_name:
        return False
    proc_name_lower = proc_name.lower()
    for search_name in search_names:
        if proc_name_lower == search_name:
            return True
    return False


def check_process(name, logger: Optional[Logger] = None):
    """
    使用psutil检查指定名称的进程是否存在
    """
    _logger = logger if logger is not None else default_logger
    try:
        search_names = get_target_names(name)

        # 遍历所有进程
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = proc.info["name"]
                if is_process_match(proc_name, search_names):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                # 进程可能已结束或无权访问，跳过
                continue
            except Exception as e:
                # 记录其他异常但不中断循环
                _logger.debug(f"检查进程时出现异常: {e}")
                continue

        return False
    except Exception as e:
        _logger.error(f"检查进程时出错: {e}")
        return False


def check_focus(name, logger: Optional[Logger] = None):
    """
    检查指定名称的进程是否为当前焦点程序（前台窗口）
    """
    _logger = logger if logger is not None else default_logger
    try:
        search_names = get_target_names(name)

        # 获取前台窗口的进程ID
        try:
            # 使用ctypes调用Windows API
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd == 0:
                return False

            # 获取进程ID
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # 获取进程信息
            try:
                proc = psutil.Process(pid.value)
                proc_name = proc.name()

                # 检查是否匹配目标进程
                if is_process_match(proc_name, search_names):
                    return True

                # 如果进程有父进程，也检查父进程（有些应用有启动器）
                try:
                    parent = proc.parent()
                    if parent:
                        parent_name = parent.name()
                        if is_process_match(parent_name, search_names):
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False

        except Exception as e:
            _logger.debug(f"获取前台窗口信息时出错: {e}")
            return False

        return False

    except Exception as e:
        _logger.error(f"检查焦点进程时出错: {e}")
        return False


if __name__ == "__main__":
    import time

    # 测试进程检查
    process_name = "do-not-exist.exe"

    print("=== 测试进程检查 ===")
    start = time.time()
    exists = check_process(process_name)
    print(f"进程 '{process_name}' 存在: {exists}")  # False 0.01s
    print(f"耗时: {time.time() - start:.3f}s")

    process_name = "游戏-forhonor.exe"

    print("=== 测试进程检查 ===")
    start = time.time()
    exists = check_process(process_name)
    print(f"进程 '{process_name}' 存在: {exists}")  # True 0.001s
    print(f"耗时: {time.time() - start:.3f}s")

    process_name = "游戏-forhonor.exe"

    print("\n=== 测试焦点检查 ===")
    start = time.time()
    focused = check_focus(process_name)
    print(f"进程 '{process_name}' 是否为焦点: {focused}")  # False 0.007s
    print(f"耗时: {time.time() - start:.3f}s")

    process_name = "Code - Insiders.exe"

    print("\n=== 测试焦点检查 ===")
    start = time.time()
    focused = check_focus(process_name)
    print(f"进程 '{process_name}' 是否为焦点: {focused}")  # True 0.000s
    print(f"耗时: {time.time() - start:.3f}s")
