import keyboard
from util.client_cosmic import Cosmic, console
from config import ClientConfig as Config
import json  # 我不会其他传递变量的方法, 先用写入文件的方法吧
import time
import asyncio
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from util.client_send_audio import send_audio
from util.my_status import Status
from util.client_pause_other_audio import pause_other_audio, audio_playering_app_name
from util.client_stream import stream_open, stream_close, stream_reopen
from pycaw.pycaw import AudioUtilities

task = asyncio.Future()
status = Status('开始录音', spinner='point')
pool = ThreadPoolExecutor()
pressed = False
released = True
event = Event()
unpause_needed = False
opposite_state_need = False

def shortcut_correct(e: keyboard.KeyboardEvent):
    # 在我的 Windows 电脑上，left ctrl 和 right ctrl 的 keycode 都是一样的，
    # keyboard 库按 keycode 判断触发
    # 即便设置 right ctrl 触发，在按下 left ctrl 时也会触发
    # 不过，虽然两个按键的 keycode 一样，但事件 e.name 是不一样的
    # 在这里加一个判断，如果 e.name 不是我们期待的按键，就返回
    key_expect = keyboard.normalize_name(Config.speech_recognition_shortcut).replace('left ', '')
    key_actual = e.name.replace('left ', '')
    if key_expect != key_actual: return False
    return True


def mute_all_sessions():
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        volume = session.SimpleAudioVolume
        volume.SetMute(1, None)


def unmute_all_sessions():
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        volume = session.SimpleAudioVolume
        volume.SetMute(0, None)


def launch_task():
    # 确认是否需要翻译
    if keyboard.is_pressed(Config.offline_translate_shortcut):
        Cosmic.offline_translate_needed = True
    else:
        Cosmic.offline_translate_needed = False
    if keyboard.is_pressed(Config.online_translate_shortcut):
        Cosmic.online_translate_needed = True
    else:
        Cosmic.online_translate_needed = False

    if Config.only_enable_microphones_when_pressed_record_shortcut:
        # 重启音频流
        stream_reopen()
        Cosmic.stream.start()
    # 记录开始时间
    t1 = time.time()

    # 将开始标志放入队列
    asyncio.run_coroutine_threadsafe(
        Cosmic.queue_in.put({'type': 'begin', 'time': t1, 'data': None}),
        Cosmic.loop
    )

    # 录音时静音其他音频播放
    if Config.mute_other_audio:
        mute_all_sessions()

    # 录音时暂停其他音频播放 且 有音频正在播放
    global unpause_needed
    if Config.pause_other_audio and audio_playering_app_name() != None:
        pause_other_audio()
        unpause_needed = True

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


def cancel_task():
    # 通知停止录音，关掉滚动条
    Cosmic.on = False
    status.stop()

    # 取消协程任务
    task.cancel()

    # 取消音频静音
    if Config.mute_other_audio:
        unmute_all_sessions()

    # 取消音频暂停
    global unpause_needed
    if Config.pause_other_audio and unpause_needed:
        keyboard.send('play/pause')
        unpause_needed = False
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
            {'type': 'finish',
             'time': time.time(),
             'data': None
             },
        ),
        Cosmic.loop
    )

    # 取消音频静音
    if Config.mute_other_audio:
        unmute_all_sessions()

    # 取消音频暂停
    global unpause_needed
    if Config.pause_other_audio and unpause_needed:
        keyboard.send('play/pause')
        unpause_needed = False
    if Config.only_enable_microphones_when_pressed_record_shortcut:
        # 结束音频流
        Cosmic.stream.stop()
        Cosmic.stream.close()


# =================单击模式======================


def count_down(e: Event):
    """按下后，开始倒数"""
    time.sleep(Config.threshold)
    e.set()

def manage_task(e: Event):
    """
    通过检测 e 是否在 threshold 时间内被触发，判断是单击，还是长按
    进行下一步的动作
    """
    global opposite_state_need

    # 計算是否屬於短時間內按下`錄音鍵`
    is_short_duration = True if time.time() - Cosmic.on < Config.threshold else False

    # 短時間內,按下第二次錄音鍵判定爲需要輸出 `簡/繁`, 并且结束函数
    if is_short_duration and opposite_state_need and Config.enable_double_click_opposite_state:
        update_opposite_state("")
        return

    # 记录是否有任务
    on = Cosmic.on
    # 先运行任务
    if not on:
        # 觸發需要輸出 `簡/繁` 的狀態(如果在短時間內按下錄音鍵`is_short_duration`)
        opposite_state_need = True
        launch_task()

    # 及时松开按键了，是单击
    if e.wait(timeout=Config.threshold * 0.8):
        # 如果有任务在运行，就结束任务
        if Cosmic.on and on:
            finish_task()
            # 恢复輸出 `簡/繁` 原来的狀態
            if Config.enable_double_click_opposite_state:
                opposite_state_need = False

    # 没有及时松开按键，是长按
    else:
        # 就取消本栈启动的任务
        if not on:
            cancel_task()
            # 恢复輸出 `簡/繁` 原来的狀態
            if Config.enable_double_click_opposite_state:
                opposite_state_need = False
        # 长按，发送按键
        keyboard.send(Config.speech_recognition_shortcut)


def click_mode(e: keyboard.KeyboardEvent):
    global pressed, released, event

    if e.event_type == 'down' and released:
        pressed, released = True, False
        event = Event()
        pool.submit(count_down, event)
        pool.submit(manage_task, event)

    elif e.event_type == 'up' and pressed:
        pressed, released = False, True
        event.set()


# ======================长按模式==================================


def hold_mode(e: keyboard.KeyboardEvent):
    """像对讲机一样，按下录音，松开停止"""
    global task, opposite_state_need

    if e.event_type == 'down' and not Cosmic.on:
        # 根據上一次是否短時間內(`duration < Config.threshold`)按下錄音鍵,來判斷是否需要輸出 `簡/繁`
        if opposite_state_need and Config.enable_double_click_opposite_state:
            update_opposite_state("")
        # 记录开始时间
        launch_task()

    elif e.event_type == 'up':
        # 记录持续时间，并标识录音线程停止向队列放数据
        duration = time.time() - Cosmic.on

        # 取消或停止任务
        if duration < Config.threshold:
            # 短時間內,按下第二次錄音鍵判定爲需要輸出 `簡/繁`
            if Config.enable_double_click_opposite_state:
                opposite_state_need = True
            cancel_task()

        else:
            finish_task()
            # 松开快捷键后，再按一次，恢复 CapsLock 或 Shift 等按键的状态
            if Config.restore_key and not opposite_state_need:
                time.sleep(0.01)
                keyboard.send(Config.speech_recognition_shortcut)
            # 恢复輸出 `簡/繁` 原来的狀態
            if Config.enable_double_click_opposite_state:
                opposite_state_need = False


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


def bond_shortcut():
    if Config.hold_mode:
        keyboard.hook_key(Config.speech_recognition_shortcut, hold_handler, suppress=Config.suppress)
    else:
        # 单击模式，必须得阻塞快捷键
        # 收到长按时，再模拟发送按键
        keyboard.hook_key(Config.speech_recognition_shortcut, click_handler, suppress=True)


# ==================== 传递变量 `opposite_state`===============


def update_opposite_state(aa):
    # 我不会其他传递变量的方法, 先用写入文件的方法吧
    if aa is False:
        opposite_state = False
    else:
        opposite_state = not read_opposite_state()
    with open('opposite_state.json', 'w') as f:
        json.dump(opposite_state, f)
    if aa is not False:
        print(f"切换状态 : {opposite_state}")
    return opposite_state


def read_opposite_state():
    # 我不会其他传递变量的方法, 先用写入文件的方法吧
    with open('opposite_state.json', 'r') as f:
        opposite_state = json.load(f)
    return opposite_state
