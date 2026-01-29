"""
Windows 原生弹窗通知工具模块

提供 Windows 系统原生弹窗通知功能，用于显示 iGPU 溢出警告等系统级提示。
"""

import ctypes
import time
import threading
from typing import Optional

# Windows API 常量定义
MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONWARNING = 0x00000030
MB_ICONINFORMATION = 0x00000040
MB_DEFBUTTON1 = 0x00000000
MB_APPLMODAL = 0x00000000
MB_TASKMODAL = 0x00002000  # 任务模态弹窗，不阻塞其他应用程序

# 用户32.dll 函数原型
user32 = ctypes.windll.user32
user32.MessageBoxW.argtypes = [
    ctypes.c_void_p,  # hWnd
    ctypes.c_wchar_p,  # lpText
    ctypes.c_wchar_p,  # lpCaption
    ctypes.c_int,  # uType
]
user32.MessageBoxW.restype = ctypes.c_int


class NotificationManager:
    """弹窗通知管理器，提供频率控制和弹窗功能"""

    def __init__(self, cooldown_seconds: int = 60):
        """
        初始化通知管理器

        Args:
            cooldown_seconds: 弹窗冷却时间（秒），默认60秒
        """
        self.cooldown_seconds = cooldown_seconds
        self.last_notification_time = 0
        self.notification_key = "igpu_overflow_warning"

    def can_show_notification(self) -> bool:
        """
        检查是否可以显示弹窗（基于时间冷却）

        Returns:
            bool: 是否可以显示弹窗
        """
        current_time = time.time()
        time_since_last = current_time - self.last_notification_time
        return time_since_last >= self.cooldown_seconds

    def _show_message_box(self, message: str, title: str):
        """在单独的线程中显示弹窗，避免阻塞主程序"""
        try:
            # 使用任务模态弹窗，不阻塞当前应用程序但会阻塞其他应用程序
            flags = MB_ICONERROR | MB_DEFBUTTON1 | MB_TASKMODAL
            user32.MessageBoxW(None, message, title, flags)
        except Exception as e:
            print(f"弹窗显示失败: {e}")

    def show_igpu_overflow_warning(self) -> bool:
        """
        显示 iGPU 溢出警告弹窗（非模态，不阻塞主程序）

        Returns:
            bool: 是否成功显示弹窗
        """
        if not self.can_show_notification():
            return False

        title = "服务端 FunASR-GGUF 转录文件 iGPU 溢出警告"
        message = (
            "警告: 服务端 FunASR-GGUF 转录文件时检测到异常重复输出（可能由 iGPU 溢出引起），已熔断。\n\n"
            "解决方案:\n"
            "• 尝试在 config.toml 中禁用 Vulkan (vulkan_enable = false)\n"
            "• 强制使用 FP32 精度 (vulkan_force_fp32 = true)\n"
            "• 调整模型参数或检查硬件资源"
        )

        try:
            # 在单独的线程中显示弹窗，避免阻塞主程序
            thread = threading.Thread(
                target=self._show_message_box,
                args=(message, title),
                daemon=True
            )
            thread.start()

            # 更新最后通知时间
            self.last_notification_time = time.time()
            return True

        except Exception as e:
            # 如果弹窗失败，记录错误但不影响主程序运行
            print(f"弹窗显示失败: {e}")
            return False

    def reset_cooldown(self):
        """重置冷却时间，立即允许下次弹窗"""
        self.last_notification_time = 0


# 全局通知管理器实例
_notification_manager = NotificationManager()


def show_igpu_overflow_warning() -> bool:
    """
    显示 iGPU 溢出警告弹窗（便捷函数，非模态）

    Returns:
        bool: 是否成功显示弹窗
    """
    return _notification_manager.show_igpu_overflow_warning()


def set_cooldown_seconds(seconds: int):
    """
    设置弹窗冷却时间

    Args:
        seconds: 冷却时间（秒）
    """
    _notification_manager.cooldown_seconds = seconds


def get_cooldown_seconds() -> int:
    """
    获取当前弹窗冷却时间

    Returns:
        int: 冷却时间（秒）
    """
    return _notification_manager.cooldown_seconds


def time_until_next_notification() -> Optional[int]:
    """
    获取距离下次允许弹窗的时间（秒）

    Returns:
        int: 距离下次允许弹窗的时间（秒），如果可以立即显示则返回 None
    """
    current_time = time.time()
    time_since_last = current_time - _notification_manager.last_notification_time
    remaining = _notification_manager.cooldown_seconds - time_since_last

    if remaining > 0:
        return int(remaining)
    else:
        return None
