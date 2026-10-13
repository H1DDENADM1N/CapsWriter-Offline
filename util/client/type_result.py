import asyncio
import platform

import clipman
import keyboard
from loguru import logger

from util.check_process import check_focus
from util.client.cosmic import console
from util.config import ClientConfig as Config


def _resolve_key(key_name: str):
    """
    将按键名解析为 keyboard 库可发送的形式。

    ported from upstream 4448746：本方客户端组无 pynput 依赖（不得新增），
    改用本方现有 keyboard 库动态解析——keyboard.key_to_scan_codes() 原生支持
    insert/home/end/page_up/方向键/f1-f12 等全部特殊键名，等价于上游
    「从 pynput keyboard.Key 枚举动态构建映射」的做法；解析失败返回 None，
    由调用方记日志跳过，与上游行为一致。
    """
    if not key_name:
        return None
    try:
        codes = keyboard.key_to_scan_codes(key_name)
        return codes[0] if codes else None
    except (ValueError, KeyError):
        return None


def _emulate_key(key_name: str) -> None:
    """
    补发一个完整按键（按下+松开），用于 suppress 短按被屏蔽后的异步补发。
    """
    try:
        code = _resolve_key(key_name)
        if code is not None:
            keyboard.press(code)
            keyboard.release(code)
            logger.debug(f"[{key_name}] 补发按键成功")
        else:
            logger.warning(f"[{key_name}] 无法识别的按键，跳过补发")
    except Exception as e:
        logger.error(f"[{key_name}] 补发按键失败: {e}")


async def emulate_key_async(key_name: str) -> None:
    """
    异步补发按键（在线程池中执行，不阻塞事件循环）。

    ported from upstream a898587：补发从同步改为线程异步，常驻复用，
    避免在按键热路径上重复初始化。
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _emulate_key, key_name)


async def _auto_enter(delay: float) -> None:
    """延迟发送回车键（ported from upstream e74673f）"""
    await asyncio.sleep(delay)
    keyboard.press_and_release("enter")
    logger.debug(f"自动回车已发送 (延迟 {delay}s)")


def _match_enter_app(process_name: str):
    """
    匹配焦点程序是否命中 enter_apps 名单，命中返回延迟秒数，未命中返回 None。
    """
    for item in Config.enter_apps:
        app, delay = item[0], item[1]
        if app.lower() == process_name:
            return delay
    return None


async def type_result(text):
    if text == "":
        return

    # 模拟粘贴
    if Config.paste:
        console.print(f"模拟粘贴：{text}")
        # 保存剪切板
        try:
            # 初始化剪贴板模块
            clipman.init()
            temp = clipman.get()
        except clipman.exceptions.ClipmanBaseException as e:
            temp = e

            logger.error(f"获取剪贴板内容时出错: {e}")

        # 复制结果
        clipman.set(text)

        # 粘贴结果
        if platform.system() == "Darwin":  # Mac
            keyboard.press(55)
            keyboard.press(9)
            keyboard.release(55)
            keyboard.release(9)
        else:
            if keyboard.is_pressed(Config.offline_translate_shortcut):
                keyboard.release(Config.offline_translate_shortcut)
            if keyboard.is_pressed(Config.online_translate_shortcut):
                keyboard.release(Config.online_translate_shortcut)
            keyboard.send("ctrl + v")

        # 还原剪贴板
        if Config.restore_clipboard_after_paste:
            await asyncio.sleep(0.1)
            clipman.set(temp)

    # 模拟打印
    else:
        console.print(f"模拟打印：{text}")
        keyboard.write(text)

    # 带延迟的附加回车（ported from upstream e74673f）：
    # 粘贴完成后，若焦点程序命中 enter_apps 名单，延迟后自动补一个回车
    if Config.paste and platform.system() == "Windows":
        import ctypes

        import psutil

        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process_name = psutil.Process(pid.value).name().lower()
        except Exception as e:
            logger.debug(f"获取焦点程序名失败，跳过自动回车检测: {e}")
            process_name = ""
        delay = _match_enter_app(process_name)
        if delay is not None:
            asyncio.create_task(_auto_enter(delay))
