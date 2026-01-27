import asyncio
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import keyboard
from flask import sessions
from loguru import logger
from pycaw.pycaw import AudioUtilities
from tomlkit import dumps, parse

from util.check_process import check_focus, check_process
from util.client.cosmic import Cosmic, console
from util.client.pause_other_audio import (
    get_audio_playing_apps,
    handle_special_media_apps,
)
from util.client.send_audio import send_audio
from util.client.send_signal_to_hint_while_recording import (
    send_signal_to_hint_while_recording,
)
from util.client.stream import stream_reopen
from util.config import ClientConfig as Config
from util.my_status import Status

if shutil.which("ffplay") and Config.play_stop_music:
    from util.client.play_music import play_music
if shutil.which("ffplay") and Config.play_start_music:
    from util.client.play_music import play_music

config_toml_path = Path("config.toml")


task = asyncio.Future()
status = Status("开始录音", spinner="point")
pool = ThreadPoolExecutor()
pressed = False
released = True
event = Event()
restore_audio_playing_needed = False
saved_result_for_restore_audio_playing_needed = False
double_clicked = False
is_short_duration = False
is_short_press = False
hold_mode_first_time_cancel_task = False
last_time_pressed = 0
last_time_released = 0
key_pressed = False
saved_result_for_offline_translate_needed = False
saved_result_for_online_translate_needed = False
unmute_task = None
restore_capslock_task = None
sessions = []
saved_special_apps = []
ignore_recording_order = False


def shortcut_correct(e: keyboard.KeyboardEvent):
    # 在我的 Windows 电脑上，left ctrl 和 right ctrl 的 keycode 都是一样的，
    # keyboard 库按 keycode 判断触发
    # 即便设置 right ctrl 触发，在按下 left ctrl 时也会触发
    # 不过，虽然两个按键的 keycode 一样，但事件 e.name 是不一样的
    # 在这里加一个判断，如果 e.name 不是我们期待的按键，就返回
    key_expect = keyboard.normalize_name(Config.speech_recognition_shortcut).replace(
        "left ", ""
    )
    key_actual = e.name.replace("left ", "")
    if key_expect != key_actual:
        return False
    return True


def handle_disable_exe_list_on_focus():
    for exe_name in Config.disable_exe_list_on_focus:
        if check_focus(exe_name):
            status.update("侦测到 " + exe_name + " 为焦点，忽略此次语音输入请求。")
            return True
    return False


def handle_disable_exe_list():
    # 在运行这些程序时，不启用客户端功能
    for exe_name in Config.disable_exe_list:
        # if check_process(exe_name) or check_focus(exe_name):
        if check_process(exe_name):
            # if check_focus(exe_name):
            status.update("请关闭 " + exe_name + " 后再试")
            return True
    return False


async def allow_recording_after_delay():
    # 异步延迟1秒（不阻塞事件循环）
    await asyncio.sleep(1)  # 这个延迟时间需要自定义定制吗？
    global key_pressed
    key_pressed = False


def mute_all_sessions():
    global sessions
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        process_name = session.Process and session.Process.name()
        # 排除 ffplay.exe
        if process_name != "ffplay.exe":
            volume = session.SimpleAudioVolume
            volume.SetMute(1, None)


def unmute_all_sessions():
    global sessions
    for session in sessions:
        process_name = session.Process and session.Process.name()
        # 排除 ffplay.exe
        if process_name != "ffplay.exe":
            volume = session.SimpleAudioVolume
            volume.SetMute(0, None)


# 封装需要异步执行的逻辑（延迟+取消静音）
async def async_unmute_after_delay():
    # 异步延迟0.3秒（不阻塞事件循环）
    await asyncio.sleep(0.3)
    # 执行取消静音操作
    unmute_all_sessions()


def restore_audio_playing():
    # - [x] 改進: 20250925: 把 "cancel_task()" 和 "finish_task()" 裏面的恢復音頻音量的函數"unmute_all_sessions()"全放在這裏, 同时，采用了异步 + 延迟的方法，避免了阻塞主线程，以及避免一些"杂音"。

    # 恢復音频的播放
    global \
        restore_audio_playing_needed, \
        saved_result_for_restore_audio_playing_needed, \
        unmute_task, \
        saved_special_apps
    # 处理音频暂停相关逻辑
    restore_audio_playing_needed = saved_result_for_restore_audio_playing_needed

    if Config.pause_other_audio and restore_audio_playing_needed:
        # hold_mode: 切换字母大小: 还是出现了一次恢复播放失败的情况, 保险起见专门为此情况增加了延迟
        if Config.hold_mode and is_short_press:
            time.sleep(0.1)
        if saved_special_apps:
            # 处理特殊应用的恢复播放
            for app_info in saved_special_apps:
                if app_info["hotkey"] == "":
                    # 不需要恢复音频播放
                    ...
                    # print(
                    #     f"未配置 {app_info['name']} 的全局暂停快捷键，不需要恢复音频播放"
                    # )
                else:
                    # 翻譯功能的"shift"會干擾發送停止播放的快捷鍵, 因此，需要預先釋放
                    if keyboard.is_pressed(Config.offline_translate_shortcut):
                        keyboard.release(Config.offline_translate_shortcut)
                    if keyboard.is_pressed(Config.online_translate_shortcut):
                        keyboard.release(Config.online_translate_shortcut)

                    # 发送相同的快捷键恢复播放
                    keyboard.send(app_info["hotkey"])
                    # print(f"已恢复 {app_info['name']}（{app_info['hotkey']}）")
            saved_special_apps = []
        else:
            keyboard.send("play/pause")

        restore_audio_playing_needed = False

    # 取消音频静音, 在主线程中调用（非事件循环线程）, 这行代码会立即返回，不会阻塞主线程
    unmute_task = asyncio.run_coroutine_threadsafe(
        async_unmute_after_delay(),  # 提交封装好的异步任务
        Cosmic.loop,  # 目标事件循环
    )


def translate_needed():
    # 确认是否需要翻译
    if (
        keyboard.is_pressed(Config.offline_translate_shortcut)
        and Config.use_offline_translate_function
    ):
        Cosmic.offline_translate_needed = True
    else:
        Cosmic.offline_translate_needed = False
    if (
        keyboard.is_pressed(Config.online_translate_shortcut)
        and Config.use_online_translate_function
    ):
        Cosmic.online_translate_needed = True
    else:
        Cosmic.online_translate_needed = False


# 這個函數採用了: 把整組 pause_other_audio 相關的代碼放到 task = asyncio.run_coroutine_threadsafe(send_audio(),Cosmic.loop,) 的後面, 從而避免影響接收聲音。
def launch_task():
    # - [x] 改進點: 20250925: time.sleep(0.6)這句代碼會阻塞整個主线程, 導致雙擊功能會有一點點的錄音延遲，不爽。
    # ✔思路1: 把整組 pause_other_audio 相關的代碼放到 task = asyncio.run_coroutine_threadsafe(send_audio(),Cosmic.loop,) 的後面, 從而避免影響接收聲音。 為方便測試調整為10秒"time.sleep(10.6)", 測試結果: 是可行的。
    # 1. 如果我把按鍵抬起的時間放在10秒後: 功能正常, ✔會恢復播放
    # 2. 如果我把按鍵抬起的時間放在10秒內: 功能正常, ✔會恢復播放, 但是有一點副作用就是必須"10秒"後才會恢復運行後面的代碼
    # 這個副作用是可以接受，因此現在採用此辦法
    # - Bug: 在應用程式全部暫停播放的情況下使用錄音會導致播放的情況
    # - 只在hold_mode的情況出現, 是 "and not Config.hold_mode" 的判斷問題

    # 思路2: 採用异步async def delay_pause(), 為方便測試調整為10秒"asyncio.sleep(10.5)", 測試結果:
    # 1. 如果我把按鍵抬起的時間放在10秒後: 功能正常, ✔會恢復播放
    # 2. 如果我把按鍵抬起的時間放在10秒內: 功能正常, ✘不會恢復播放
    # 現在不採用異步的方法, 除非有辦法能解決短時間內抬起，不會恢復播放的問題
    # Git: 753321e008117e227d666efba188543c4200b48e

    global hold_mode_first_time_cancel_task, unmute_task, restore_capslock_task

    # 开始任务时播放提示音
    if shutil.which("ffplay") and Config.play_start_music:
        play_music(Config.start_music_path, Config.start_music_volume)

    # 确认是否需要翻译
    # 改为独立调用
    # translate_needed()

    if (
        not double_clicked
        and Config.only_enable_microphones_when_pressed_record_shortcut
    ):
        # 重启音频流; 在双击情况下, 只在第一次的时候启动(单击模式)
        stream_reopen()
        Cosmic.stream.start()

    # 长按模式(hold_mode)双击功能 第二次重启不适用于上面的判断, 因此，需要下面来判断是否重启音频流
    # 长按模式(hold_mode)双击功能 確實需要第二次啓動音频流, 设计的时候就是如此, 因为会进行一次 start  cancel 的流程, 然后第二次啓動才是双击功能的录音
    elif (
        hold_mode_first_time_cancel_task
        and double_clicked
        and Config.only_enable_microphones_when_pressed_record_shortcut
    ):
        stream_reopen()
        Cosmic.stream.start()
        hold_mode_first_time_cancel_task = False
    # 记录开始时间
    t1 = time.time()

    # 将开始标志放入队列
    try:
        asyncio.run_coroutine_threadsafe(
            Cosmic.queue_in.put({"type": "begin", "time": t1, "data": None}),
            Cosmic.loop,
        )
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            try:
                Cosmic.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(Cosmic.loop)
                asyncio.run_coroutine_threadsafe(
                    Cosmic.queue_in.put({"type": "begin", "time": t1, "data": None}),
                    Cosmic.loop,
                )
            except Exception as e:
                logger.error(f"Failed to create new event loop: {e}")
        else:
            raise

    if is_short_duration and unmute_task is not None:
        is_cancelled = unmute_task.cancel()
        # if is_cancelled:
        #     print("成功取消延迟的unmute操作")
        # else:
        #     print("取消失败（任务可能已执行或已完成）")
        unmute_task = None

    # 录音时静音其他音频播放
    if Config.mute_other_audio:
        mute_all_sessions()

    # 通知录音线程可以向队列放数据了
    Cosmic.on = t1

    # 打印动画：正在录音
    status.start()

    # 启动识别任务
    global task
    task = asyncio.run_coroutine_threadsafe(
        send_audio(),
        Cosmic.loop,
    )

    # 录音时暂停其他音频播放 且 有音频正在播放
    global \
        restore_audio_playing_needed, \
        saved_result_for_restore_audio_playing_needed, \
        saved_special_apps

    if Config.pause_other_audio and not restore_audio_playing_needed:
        # 针对双击导致停止和播放的指令过快的问题，增加了时间延迟
        # if is_short_duration:
        #     # 试过的时间: 0.2✘; 0.3✘; 0.4✘; 0.5✔;1✔
        #     time.sleep(0.6)
        playing_apps = get_audio_playing_apps()
        if len(playing_apps) > 0:
            print(f"{len(playing_apps)} 个程序正在播放音频: {playing_apps}")
        # 网易云音乐/QQ音乐/PotPlayer/foobar2000 播放时 使用 播放器设置的 全局快捷键 暂停/恢复 播放
        has_processed, processed_apps = handle_special_media_apps(playing_apps)
        if has_processed:
            # 保存处理的应用信息，用于后续恢复或其他操作
            print("❗特殊应用在播放音频")
            saved_special_apps = processed_apps  # 保存到全局变量或配置中

            # 记录日志
            for app_info in processed_apps:
                print(f"已暂停 {app_info['name']} ({app_info['exe']})")

            # 继续执行原有逻辑
            restore_audio_playing_needed = True
            if not is_short_duration:
                saved_result_for_restore_audio_playing_needed = (
                    restore_audio_playing_needed
                )
        else:
            # print("非特殊应用在播放音频")
            match len(playing_apps):
                case 0:
                    # 如果没有程序在播放，清除恢复标志
                    if not saved_special_apps:
                        saved_result_for_restore_audio_playing_needed = False
                        restore_audio_playing_needed = False
                case 1:
                    # 只有一个程序在播放音频
                    keyboard.send("play/pause")
                    restore_audio_playing_needed = True
                    if not is_short_duration:
                        saved_result_for_restore_audio_playing_needed = (
                            restore_audio_playing_needed
                        )
                case _:
                    # 多个程序在播放音频
                    if not saved_special_apps:
                        saved_result_for_restore_audio_playing_needed = False
                        restore_audio_playing_needed = False
                    print("不支持暂停多个程序的音频播放，跳过暂停其他音频播放")


def cancel_task():
    # 通知停止录音，关掉滚动条
    Cosmic.on = False
    status.stop()

    # 发送取消任务的消息到队列
    asyncio.run_coroutine_threadsafe(
        Cosmic.queue_in.put({"type": "cancel", "time": time.time(), "data": None}),
        Cosmic.loop,
    )

    if Config.only_enable_microphones_when_pressed_record_shortcut:
        # 结束音频流
        Cosmic.stream.stop()
        Cosmic.stream.close()


def finish_task():
    global task
    # 通知停止录音，关掉滚动条
    Cosmic.on = False
    status.stop()

    # 通知结束任务
    asyncio.run_coroutine_threadsafe(
        Cosmic.queue_in.put(
            {"type": "finish", "time": time.time(), "data": None},
        ),
        Cosmic.loop,
    )

    # 结束任务时播放提示音
    if shutil.which("ffplay") and Config.play_stop_music:
        play_music(Config.stop_music_path, Config.stop_music_volume)

    if Config.only_enable_microphones_when_pressed_record_shortcut:
        # 结束音频流
        Cosmic.stream.stop()
        Cosmic.stream.close()


# =================单击模式======================
# 封装需要异步执行的原版 CapsLock 功能（延迟+恢复）
async def original_capslock_function():
    global restore_capslock_task, return_allowed
    if Config.restore_key:
        # 开始"倒数"至少0.3秒(threshold)
        await asyncio.sleep(Config.threshold)
        # "倒数"0.3秒后，如果该按键依然是被按下的状态，就执行原本功能
        if keyboard.is_pressed(Config.speech_recognition_shortcut):
            keyboard.send(Config.speech_recognition_shortcut)
        restore_capslock_task = None
        return_allowed = True


def click_mode(e: keyboard.KeyboardEvent):
    # 0. 原来的设计甚是巧妙巧妙, 但是我的功力有限，消化不良.
    # 1. 这里的设计思路是: 按下`录音键`只记录`按下时的时间标记`，然后根据`弹起来时的时间标记`和前面`按下时的时间标记`的 长短 进行判断应该进行哪一种行为.

    # 2. 这种方法可以处理以下的情况:
    # 2.1. 原来的设计: 使用`CapsLock`开启大小写的功能, 在单击模式下`未触发`录音模式之前,长按这个按键切换有机率失败，但是进行录音模式`之后`, 成功的几率极大.
    # 2.2. 这是因为: `def manage_task(e: Event): `它是按下按键就立刻开启任务，在开启任务之后才进行判断是否`长/短`按。这就是导致有几率失败的原因

    # 3.改進點: `長按` = 进行大小写切换的功能, 需要按键抬起后才能切换;
    # - [x] 改進: 20250926: 通过异步的方法实现了原版的长按功能(至少按下0.3秒,click_mode only), 在`长按`的过程中, 按键会自动重复, 就像原来的"caps lock"自己亮起的一样。
    # - Bug: 20250926: 通过长按录音键后恢复原有的功能之后，立刻马上进行录音会失败
    # - [x] 解決方法: 引入 return_allowed 变量来引导进入return结束函数

    # 4. 为了解决在 Windows 下按键会自动重复的问题 : key_pressed 变量用于追踪按键是否已经被按下并记录时间。当按键第一次被按下时，记录时间并将 key_pressed 设为 True，防止重复记录时间。当按键释放时，将 key_pressed 重新设为 False，允许下一次按键记录新的时间。

    # - [x] Bug6: 20250918: click_mode : "double_clicked" 改为常驻 → 导致 Config.enable_double_click_opposite_state 失效。
    # 解决方法: client_recv_result.py → 判断变量放到 async def recv_result() 后；client_shortcut_handler.py → 移除所有 Config.enable_double_click_opposite_state。

    # - [x] Bug4: 20250919: click_mode : "Shift + double_clicked / double_clicked" 可能导致恢复播放失败。
    # 解决方法-Bug4: 在 "elif (double_clicked and is_short_duration)" 中移除 restore_audio_playing()。

    # - [ ] 潜在改善点: 20250924: 假如有两个应用在运行, 其中第1个在播放，第2个在暂停, 那么我进行录音，第一个会被暂停，而第2个在录音期间依然会被播放(靜音)，不符合“暂停所有应用”的设想。
    # 思路:
    # 1. 能否指定某应用暂停/播放？
    # - [ ]
    #   handle_special_media_apps(playing_apps) 处理 网易云音乐/QQ音乐/PotPlayer/foobar2000 播放时 使用 播放器设置的 全局快捷键 暂停/恢复 播放。
    #   非网易云音乐/QQ音乐/PotPlayer/foobar2000，仅有一个应用在播放时，使用全局媒体键 播放/暂停 ，如果后台有其他已暂停播放的应用，可能影响其他后台已暂停应用的播放 😂
    #   非网易云音乐/QQ音乐/PotPlayer/foobar2000，有两个以上应用在播放时，不使用全局媒体键 播放/暂停 ，只能指望静音其他音频播放的功能 😂
    # 2. 如何判断应用是否在播放？
    # - [x] playing_apps = get_audio_playing_apps() 可获取正在播放的应用，字典形式。{pid: name} 默认排除 ffplay.exe ，这是用于播放提示音的，排除以避免误判。

    global \
        last_time_pressed, \
        last_time_released, \
        key_pressed, \
        double_clicked, \
        is_short_duration, \
        restore_audio_playing_needed, \
        restore_capslock_task, \
        return_allowed, \
        ignore_recording_order

    if e.event_type == keyboard.KEY_DOWN and not key_pressed:
        key_pressed = True  # 锁上
        return_allowed = False  # 重置状态
        ignore_recording_order = False  # 重置状态; 此变量让 "elif e.event_type == keyboard.KEY_UP" 之后的代码可以妥善处理

        # `屏蔽录音命令`的功能放在 "key_pressed 锁" 之后, 减少判断次数; 直接在更接近源头的地方进行判断, 平时没必要进入
        if Config.disable_exe_list_on_focus:
            if handle_disable_exe_list_on_focus():
                ignore_recording_order = True
                # 进一步减低进来的频率
                asyncio.run_coroutine_threadsafe(
                    allow_recording_after_delay(), Cosmic.loop
                )
                # 模拟按键按下
                keyboard.press(Config.speech_recognition_shortcut)
                return
        if Config.disable_exe_list:
            if handle_disable_exe_list():
                ignore_recording_order = True
                # asyncio.run_coroutine_threadsafe(allow_recording_after_delay(), Cosmic.loop)
                keyboard.press(Config.speech_recognition_shortcut)
                key_pressed = False  # 和上面的`allow_recording_after_delay()` 2选1
                return

        if restore_capslock_task is None:
            restore_capslock_task = asyncio.run_coroutine_threadsafe(
                original_capslock_function(),  # 提交封装好的异步任务
                Cosmic.loop,  # 目标事件循环
            )

        # 計算是否屬於短時間內雙击`錄音鍵`
        is_short_duration = (
            True if time.time() - last_time_released < Config.threshold else False
        )
        last_time_pressed = time.time()
    elif e.event_type == keyboard.KEY_UP:
        if ignore_recording_order:
            # 模拟按键抬起
            keyboard.release(Config.speech_recognition_shortcut)
            return
        if not ignore_recording_order:
            last_time_released = time.time()

            if restore_capslock_task is not None:
                # 取消 延迟恢复原版CapsLock功能的任务
                restore_capslock_task_cancelled = restore_capslock_task.cancel()
                # if restore_capslock_task_cancelled:
                #     print("成功取消延迟的restore_capslock_task操作")
                # else:
                #     print("取消失败（任务可能已执行或已完成）")
                restore_capslock_task = None

            # 如果大于`Config.threshold`的值, 判定为`長按`, 就取消本栈启动的任务(`cancel_task()`)
            if Config.restore_key and return_allowed:
                # 判定为`長按`，发送原來的按键功能
                # keyboard.send(Config.speech_recognition_shortcut)
                last_time_released = 0  # 重置; 用途是解决不再启动录音任务情况
                key_pressed = False
                return

            # 任务不在进行中, 且不判定为`短击`, 就开始任务, 同时标记 任务在进行中狀态
            elif not double_clicked and not is_short_duration:
                translate_needed()
                send_signal_to_hint_while_recording(
                    True,
                    is_short_duration,
                    Cosmic.offline_translate_needed,
                    Cosmic.online_translate_needed,
                    Config.hold_mode,
                    Config.convert_to_traditional_chinese_main,
                )
                launch_task()
                double_clicked = True
                key_pressed = False
                return

            # 任务在进行中, 且不判定为`短击`, 就结束和完成任务
            elif double_clicked and not is_short_duration:
                finish_task()
                send_signal_to_hint_while_recording(
                    False,
                    is_short_duration,
                    Cosmic.offline_translate_needed,
                    Cosmic.online_translate_needed,
                    Config.hold_mode,
                    Config.convert_to_traditional_chinese_main,
                )
                last_time_released = 0  # 重置; 用途是解决快速开始任务&结束之后不再进入`launch_task()`情况
                double_clicked = False
                key_pressed = False
                # 恢復音频的播放
                restore_audio_playing()
                return

            # 任务在进行中, 且为`短击`, 判定爲需要輸出 `簡/繁`, 并且结束函数
            elif double_clicked and is_short_duration:
                translate_needed()
                send_signal_to_hint_while_recording(
                    True,
                    is_short_duration,
                    Cosmic.offline_translate_needed,
                    Cosmic.online_translate_needed,
                    Config.hold_mode,
                    Config.convert_to_traditional_chinese_main,
                )

                Cosmic.opposite_state = not Cosmic.opposite_state
                key_pressed = False
                # return

            # print(f'世界的尽头!')


# ======================长按模式==================================
def hold_mode(e: keyboard.KeyboardEvent):
    """像对讲机一样，按下录音，松开停止"""
    # - [x] 改進: 20250918: 增加 key_pressed 变量避免函数重复触发。
    # - [x] 改進: 20250918: 去掉 Cosmic.on，改用 last_time_released & last_time_pressed 记录时间。

    # - [x] Bug1: 20250918: Hold Mode 下
    #       1. 单次按下/弹起录音键 < Config.threshold
    #       2. 双击录音键
    #     → 播放无法恢复。
    # - [x] 解決方法-Bug1 20250919: 双击 → 增加 saved_result_for_restore_audio_playing_needed 保存状态。
    # - [x] 解決方法-Bug1 20250919: < threshold → 恢复命令延后执行，独立成函数。

    # - [?] Bug2: 20250918: 改动后需观察是否仍有任务顺序错乱。

    # - [x] Bug3: 20250918: holdmode=true 时 shift+录音键(双击) 失效，输出简体中文；holdmode=false 正常。
    # 解決方法-Bug3: 20250919: 修改 Config.enable_double_click_opposite_state=false → 可英文输出。
    # 解決方法-Bug3: 20250919: 删除 hold_mode() 内的 enable_double_click_opposite_state → 变为中文输出，问题与该变量相关。
    # 解決方法-Bug3: 20250924: 引入 saved_result_for_offline_translate_needed 保存状态，避免 shift 被误判抬起。
    # - [?] 原因-Bug3: 可能与 shift/caps lock 状态牵连有关，需继续确认。

    # - [x] 更新 20250919: 更新 "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
    # 解決方法-更新: 20250924: 新模型无标点，需额外加载；最终的效果不如旧版，已还原。

    # - [x] Bug5: 20250919: hold_mode 下双击录音键可能不恢复播放。
    # 观察-Bug5: 调整 launch_task() 暂停逻辑后，仅出现过一次，需继续观察。
    # 观察-Bug5: 20250924: 快速三次操作导致第三次动作被吞，第二次抬起时错误暂停。
    # 解决方法-Bug5: 20250924: 在 launch_task() 中对快速第二次按下(is_short_duration)增加延迟，仅 hold_mode 应用。

    global \
        task, \
        key_pressed, \
        double_clicked, \
        last_time_pressed, \
        last_time_released, \
        hold_mode_first_time_cancel_task, \
        is_short_duration, \
        is_short_press, \
        restore_audio_playing_needed, \
        saved_result_for_restore_audio_playing_needed, \
        saved_result_for_offline_translate_needed, \
        saved_result_for_online_translate_needed, \
        ignore_recording_order

    # 处理按键按下事件
    if e.event_type == "down":
        if not key_pressed:
            key_pressed = True  # 锁上
            ignore_recording_order = (
                False  # 重置状态; 此变量让 "e.event_type == "up" 之后的代码可以妥善处理
            )

            # `屏蔽录音命令`的功能放在 "key_pressed 锁" 之后, 减少判断次数; 直接在更接近源头的地方进行判断, 平时没必要进入
            if Config.disable_exe_list_on_focus:
                if handle_disable_exe_list_on_focus():
                    ignore_recording_order = True
                    # 进一步减低进来的频率
                    asyncio.run_coroutine_threadsafe(
                        allow_recording_after_delay(), Cosmic.loop
                    )
                    if Config.suppress:
                        # 模拟按键按下; "suppress = Ture" 才需要模拟
                        keyboard.press(Config.speech_recognition_shortcut)
                    return
            if Config.disable_exe_list:
                if handle_disable_exe_list():
                    ignore_recording_order = True
                    # asyncio.run_coroutine_threadsafe(allow_recording_after_delay(), Cosmic.loop)
                    if Config.suppress:
                        keyboard.press(Config.speech_recognition_shortcut)
                    key_pressed = False  # 和上面的`allow_recording_after_delay()` 2选1
                    return

            last_time_pressed = time.time()
            # 計算是否屬於短時間內按下`錄音鍵`
            is_short_duration = (
                last_time_pressed - last_time_released
            ) < Config.threshold

            # 短時間內,按下第二次錄音鍵判定爲需要輸出 `簡/繁`
            if is_short_duration:
                double_clicked = True

            # 处理双击切换简/繁状态, 当初为何使用这个double_clicked变量来判断？嗯，记不起来了. 可能是当时还没使用key_pressed来锁定
            if double_clicked:
                Cosmic.opposite_state = not Cosmic.opposite_state

            translate_needed()
            send_signal_to_hint_while_recording(
                True,
                is_short_duration,
                Cosmic.offline_translate_needed,
                Cosmic.online_translate_needed,
                Config.hold_mode,
                Config.convert_to_traditional_chinese_main,
            )
            # 启动录音任务
            launch_task()
            if not is_short_duration:
                saved_result_for_offline_translate_needed = (
                    Cosmic.offline_translate_needed
                )
                saved_result_for_online_translate_needed = (
                    Cosmic.online_translate_needed
                )

    elif e.event_type == "up":
        if Config.suppress and ignore_recording_order:
            # 模拟按键抬起
            keyboard.release(Config.speech_recognition_shortcut)
            return
        # 仅在已按下状态时处理松开事件
        if key_pressed and not ignore_recording_order:
            # 标记最后弹起的时间
            last_time_released = time.time()

            # 计算按键弹起来和按下的间隔
            is_short_press = (last_time_released - last_time_pressed) < Config.threshold

            if is_short_duration:
                Cosmic.offline_translate_needed = (
                    saved_result_for_offline_translate_needed
                )
                Cosmic.online_translate_needed = (
                    saved_result_for_online_translate_needed
                )

                if Config.suppress:
                    keyboard.send(Config.speech_recognition_shortcut)

            # 取消或完成任务
            if is_short_press and not double_clicked:
                hold_mode_first_time_cancel_task = True
                cancel_task()

                if Config.suppress:
                    keyboard.send(Config.speech_recognition_shortcut)

            else:
                finish_task()

                # 任务完成后, 还原释放案件的时间, 以免两个任务的时间间隔太短导致误判
                last_time_released = 0

                # 松开快捷键后，再按一次，恢复 CapsLock 或 Shift 等按键的状态
                if not double_clicked and Config.restore_key and not Config.suppress:
                    time.sleep(0.01)

                    keyboard.send(Config.speech_recognition_shortcut)

                # 恢复輸出 `簡/繁` 原来的狀態， 恢复这个关于翻译的变量状态
                double_clicked = False
                saved_result_for_offline_translate_needed = False
                saved_result_for_online_translate_needed = False

            # 20250918: 增加了"key_pressed" 之后这里不应该向 AHK 发送 is_short_duration=True 的信号, 否则会导致"语音输入中"的提示不会进行取消 (跟AHK代码逻辑有关)， 最后，不影响AHK的提示。
            send_signal_to_hint_while_recording(
                False,
                False,
                Cosmic.offline_translate_needed,
                Cosmic.online_translate_needed,
                Config.hold_mode,
                Config.convert_to_traditional_chinese_main,
            )

            # 恢復音频的播放
            restore_audio_playing()
            is_short_press = False
            key_pressed = False  # 标记为未按下


# ==================== 绑定 handler ===============================


def hold_handler(e: keyboard.KeyboardEvent) -> None:
    # 验证按键名正确
    if not shortcut_correct(e):
        return

    # 长按模式
    hold_mode(e)


def click_handler(e: keyboard.KeyboardEvent) -> None:
    # 验证按键名正确
    if not shortcut_correct(e):
        return

    # 单击模式
    click_mode(e)


def update_prompt_style_handler(style: str) -> None:
    try:
        with config_toml_path.open("r", encoding="utf-8") as f:
            config_str = f.read()
            config = parse(config_str)
        config["client"]["prompt_style_selection"] = style
        with config_toml_path.open("w", encoding="utf-8") as f:
            f.write(dumps(config))
    except Exception as e:
        console.print(
            f"{Config.prompt_official_shortcut} 快捷键修改提示风格 {style} 失败: {e}"
        )

        logger.error(f"保存配置文件失败: {e}")
        return


def prompt_official_handler() -> None:
    update_prompt_style_handler("official")


def prompt_sweetheart_handler() -> None:
    update_prompt_style_handler("sweetheart")


def prompt_social_handler() -> None:
    update_prompt_style_handler("social")


def prompt_poetry_handler() -> None:
    update_prompt_style_handler("poetry")


def prompt_english_handler() -> None:
    update_prompt_style_handler("english")


def prompt_academic_handler() -> None:
    update_prompt_style_handler("academic")


def prompt_customer_service_handler() -> None:
    update_prompt_style_handler("customer_service")


def prompt_creative_writing_handler() -> None:
    update_prompt_style_handler("creative_writing")


def bond_shortcut():
    if Config.prompt_official_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_official_shortcut, prompt_official_handler, suppress=False
        )
    if Config.prompt_sweetheart_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_sweetheart_shortcut, prompt_sweetheart_handler, suppress=False
        )
    if Config.prompt_social_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_social_shortcut, prompt_social_handler, suppress=False
        )
    if Config.prompt_poetry_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_poetry_shortcut, prompt_poetry_handler, suppress=False
        )
    if Config.prompt_english_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_english_shortcut, prompt_english_handler, suppress=False
        )
    if Config.prompt_academic_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_academic_shortcut, prompt_academic_handler, suppress=False
        )
    if Config.prompt_customer_service_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_customer_service_shortcut,
            prompt_customer_service_handler,
            suppress=False,
        )
    if Config.prompt_creative_writing_shortcut != "":
        keyboard.add_hotkey(
            Config.prompt_creative_writing_shortcut,
            prompt_creative_writing_handler,
            suppress=False,
        )

    if Config.hold_mode:
        keyboard.hook_key(
            Config.speech_recognition_shortcut, hold_handler, suppress=Config.suppress
        )
    else:
        # 单击模式，必须得阻塞快捷键
        # 收到长按时，再模拟发送按键
        keyboard.hook_key(
            Config.speech_recognition_shortcut, click_handler, suppress=True
        )
