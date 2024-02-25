import keyboard
import time
import threading
from config import ClientConfig as Config

# 初始化停止事件为None
thread = None
stop_event = None
class KeyPressCounter:
    exceed_time = False

def count_duration(stop_event):
    start_time = time.time()  # 获取开始时间
    while not stop_event.is_set():  # 检查是否需要停止
        duration = time.time() - start_time  # 计算持续时间
        # print(f' {Config.shortcut} 按键持续按下：{duration:.1f} 秒')
        if not keyboard.is_pressed(Config.shortcut):  # 如果按键释放，则停止线程
            KeyPressCounter.exceed_time = False
            stop_event.set()
        if duration > Config.auto_type:
            KeyPressCounter.exceed_time = True
            # print('超时间')
            stop_event.set()

def key_press_counter(e: keyboard.KeyboardEvent):
    global thread, stop_event
    if e.name == Config.shortcut:
        if thread and thread.is_alive():  # 如果线程已经存在且正在运行，则不继续
            return

        stop_event = threading.Event()  # 创建一个事件对象用于停止线程
        if keyboard.is_pressed(Config.shortcut):
            thread = threading.Thread(target=count_duration, args=(stop_event,), daemon=True)
            thread.start()  # 启动一个线程来持续检测按键按下时间







if __name__ == '__main__':
    # 注册事件监听器
    keyboard.on_press(key_press_counter)
    # 进入无限循环，直到程序被关闭
    keyboard.wait('esc')  # 按下Esc键退出监听
