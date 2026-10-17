#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADB 控制 Android - 通过 Windows 键盘控制手机音频与媒体播放

功能:
    - 全局热键: 静音/取消静音、播放/暂停、播放、暂停
    - 对讲机键 (Right Ctrl): 按住静音+暂停 / 松开恢复音量+播放
      * 仅当手机确实有音频在播放时才触发，避免误触发播放
    - 无线 ADB 连接: 支持通过 Wi-Fi 连接手机，无需 USB 线
    - 低延迟: 持久 adb shell 会话 + 后台监控线程

用法:
    python adb_control.py connect <IP>[:端口]   # 连接手机
    python adb_control.py disconnect            # 断开无线连接
    python adb_control.py devices               # 列出已连接设备
    python adb_control.py playing               # 检查是否有音频播放
    python adb_control.py status                # 查看当前音量
    python adb_control.py debug                 # 打印原始 dumpsys 输出
    python adb_control.py audiodebug            # 打印音频播放器详情
    python adb_control.py mute                  # 静音
    python adb_control.py unmute                # 取消静音
    python adb_control.py play                  # 播放
    python adb_control.py pause                 # 暂停
    python adb_control.py toggle                # 播放/暂停切换
    python adb_control.py                       # 启动热键监听

依赖:
    pip install keyboard
"""

import re
import subprocess
import sys
import threading
import time

# 强制 stdout/stderr 使用 UTF-8，避免 Windows 管道重定向时 GBK 编码报错
# 例如: python adb_control.py audiodebug | findstr "xxx" 时若不设置会抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import keyboard  # 全局热键库，监听键盘事件、注册快捷键

# ============================================================
# 配置区（按需修改）
# ============================================================

# adb 可执行文件路径。若已加入系统 PATH，保持 "adb" 即可；
# 否则写绝对路径，例如 r"C:\platform-tools\adb.exe"
ADB_PATH = "adb"

# 对讲机键: 按住→静音+暂停，松开→恢复音量+播放
# 可选值: "right ctrl" / "right shift" / "right alt" / "scroll lock" / "menu"
PTT_KEY = "right ctrl"

# 全局热键组合
HOTKEY_MUTE_TOGGLE = "ctrl+alt+m"  # 静音/取消静音 智能切换
HOTKEY_PLAY_PAUSE = "ctrl+alt+space"  # 播放/暂停 切换
HOTKEY_PLAY = "ctrl+alt+p"  # 播放
HOTKEY_PAUSE = "ctrl+alt+s"  # 暂停

# 后台监控线程的刷新间隔（秒）。越小越灵敏，但会持续消耗手机端资源
MONITOR_INTERVAL = 0.2

# 热键去抖窗口（秒）。防止连按触发多次动作
_DEBOUNCE_SECONDS = 0.3

# 是否输出监控线程的调试日志。排查问题时改成 True
MONITOR_DEBUG = False

# ============================================================
# Android KeyEvent 键码
# 参考: https://developer.android.com/reference/android/view/KeyEvent
# ============================================================

KEYCODE_VOLUME_MUTE = 164  # 音量静音切换（部分 ROM 无效）
KEYCODE_MEDIA_PLAY_PAUSE = 85  # 播放/暂停 切换（toggle 语义）
KEYCODE_MEDIA_PLAY = 126  # 播放
KEYCODE_MEDIA_PAUSE = 127  # 暂停（在部分 App 上也是 toggle 语义）

# 全局状态: 上次热键触发时间，用于去抖
_last_trigger_time = 0


# ============================================================
# AdbShell: 持久 adb shell 会话
# ============================================================


class AdbShell:
    """
    持久 adb shell 会话。

    相比每次调用 `subprocess.run(["adb", "shell", ...])`（每次约 50-200ms 进程启动
    开销），此实现只启动一个长驻的 `adb shell` 进程，后续命令通过 stdin 发送、
    通过 stdout 读取，单次往返可降至 30-80ms。

    关键技术点:
        1. 命令结束检测: 用唯一 marker (echo __DONE_xxx__) 标记命令输出结尾
        2. PTY 回显剥离: adb shell 分配 PTY 会把输入的命令回显到输出，
           用唯一 unique 标记包裹命令，取最后一次出现的 unique 之后的内容
    """

    def __init__(self, adb_path="adb", device=None):
        """
        参数:
            adb_path: adb 可执行文件路径
            device:   指定设备序列号（多设备时使用，格式 "192.168.1.100:5555"）
        """
        self.adb_path = adb_path
        self.device = device
        self.proc = None  # subprocess.Popen 对象
        self._buf = b""  # 输出缓冲区（字节）
        self._buf_lock = threading.Lock()  # 保护 _buf 的锁
        self._cmd_lock = threading.Lock()  # 保证一次只执行一条命令
        self._alive = False  # 进程是否存活
        self._reader_thread = None  # 后台读取线程
        self._start()

    def _start(self):
        """启动 adb shell 进程，并开启后台线程持续读取输出"""
        try:
            args = [self.adb_path]
            if self.device:
                args += ["-s", self.device]
            args += ["shell"]
            self.proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
                bufsize=0,  # 无缓冲，立即读取
            )
            self._buf = b""
            self._alive = True
            self._reader_thread = threading.Thread(target=self._reader, daemon=True)
            self._reader_thread.start()
        except FileNotFoundError:
            print("❌ 找不到 adb，请检查 ADB_PATH")
            self._alive = False

    def _reader(self):
        """后台线程: 持续从 stdout 读取数据到 _buf"""
        while self._alive:
            try:
                chunk = self.proc.stdout.read(4096)
                if not chunk:
                    break  # EOF，进程已退出
                with self._buf_lock:
                    self._buf += chunk
            except Exception:
                break
        self._alive = False

    def run(self, cmd, timeout=2.0):
        """
        执行一条 shell 命令并返回输出文本。

        参数:
            cmd:     要在 Android shell 中执行的命令字符串
            timeout: 等待输出的最长秒数

        返回:
            命令的输出文本（str）；超时或异常返回空字符串

        实现细节:
            - 用 echo __OUT_xxx__ 包裹命令，回显时 unique 会出现一次，
              真实输出再出现一次，用 rfind 取最后一次之后的内容即可剥离回显
            - 用 echo __DONE_xxx__ 标记命令结束
        """
        if not self._alive:
            self._start()
            if not self._alive:
                return ""

        with self._cmd_lock:
            try:
                # 每次调用生成唯一标识，避免与历史数据混淆
                uid = time.time_ns()
                marker = f"__DONE_{uid}__"
                unique = f"__OUT_{uid}__"

                # 清空上次遗留的缓冲区
                with self._buf_lock:
                    self._buf = b""

                # 发送命令
                full = f"echo {unique}; {cmd}; echo {marker}\n"
                self.proc.stdin.write(full.encode())
                self.proc.stdin.flush()

                # 轮询等待 marker 出现
                marker_bytes = marker.encode()
                start = time.monotonic()
                while time.monotonic() - start < timeout:
                    with self._buf_lock:
                        idx = self._buf.find(marker_bytes)
                        if idx >= 0:
                            text = self._buf[:idx].decode("utf-8", errors="ignore")
                            self._buf = b""
                            # 剥离命令回显：取最后一次出现的 unique 之后的内容
                            pos = text.rfind(unique)
                            if pos >= 0:
                                text = text[pos + len(unique) :]
                            return text
                    time.sleep(0.002)
                return ""  # 超时
            except Exception:
                self._alive = False
                return ""

    def close(self):
        """关闭 adb shell 进程"""
        self._alive = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass


# ============================================================
# 普通一次性 adb 调用（用于连接、断开等不频繁的操作）
# ============================================================


def run_adb(args, timeout=10):
    """
    执行一次 adb 命令（新起进程，适合一次性操作）。

    参数:
        args:    adb 的参数列表，不含 "adb" 本身，
                 例如 ["connect", "192.168.1.100:5555"]
        timeout: 超时秒数

    返回:
        (returncode, stdout, stderr)
    """
    try:
        result = subprocess.run(
            [ADB_PATH] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "adb not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


# ============================================================
# 音频播放状态解析
# ============================================================

# 匹配 media_session 中的播放状态:
#   state=PlaybackState {state=PLAYING(3), ...}
#   state=PlaybackState {state=3, ...}
_MS_PLAYING_RE = re.compile(
    r"state=PlaybackState\s*\{\s*state=(PLAYING\((\d+)\)|(\d+))"
)


def parse_playing_from_dumps(out):
    """
    从 dumpsys 输出判断 Android 是否有音频在播放。

    双来源判定（任一命中即为播放中）:
        1. dumpsys media_session: state=PlaybackState {state=PLAYING(3)}
           适用于实现了标准 MediaSession 的 App（网易云、QQ音乐、B站等）

        2. dumpsys audio: AudioPlaybackConfiguration ... state:started
           适用于没有 MediaSession 的 App（抖音、快手等短视频）
           * 必须排除 mutedState:clientVolume / mutedState:muted 的静音轨
             （抖音播放时会保留一条静音轨用于预加载，它的 state 也是 started）

    参数:
        out: 可以是合并的 dumpsys 文本（含 ---MS--- / ---AU--- 分隔），
             也可以是单个来源的文本

    返回:
        True  有音频在播放
        False 无音频播放
    """
    # 拆分 media_session 段和 audio 段
    if "---MS---" in out and "---AU---" in out:
        ms_seg = out.split("---MS---", 1)[1].split("---AU---", 1)[0]
        au_seg = out.split("---AU---", 1)[1]
    else:
        # 没有分隔符时把整段当作两个来源处理（正则各自命中即可）
        ms_seg = out
        au_seg = out

    # ---- 来源 1: media_session ----
    for line in ms_seg.splitlines():
        if "state=PlaybackState" in line:
            m = _MS_PLAYING_RE.search(line)
            if m:
                # group(2) 是 PLAYING(x) 里的数字，group(3) 是纯数字形式
                code = m.group(2) or m.group(3)
                if code == "3":
                    return True
    # 兜底匹配（有些 ROM 单独一行输出 PLAYING(3)）
    if re.search(r"state=PLAYING\(3\)", ms_seg):
        return True

    # ---- 来源 2: dumpsys audio ----
    for line in au_seg.splitlines():
        if "AudioPlaybackConfiguration" not in line:
            continue
        if "state:started" not in line:
            continue
        # 关键: 排除静音轨（抖音等 App 会保留）
        if "mutedState:clientVolume" in line or "mutedState:muted" in line:
            continue
        return True

    return False


# ============================================================
# DeviceMonitor: 后台监控线程
# ============================================================


class DeviceMonitor:
    """
    后台线程持续查询 Android 状态，缓存最新值。

    目的: 让热键动作可以零延迟读取音量/播放状态，无需每次按下都走 adb。
    监控内容:
        - 音乐流（stream 3）当前音量
        - 是否有音频正在播放
    """

    def __init__(self, shell: AdbShell, interval=0.2, debug=False):
        """
        参数:
            shell:    专用于监控的 AdbShell 实例（与操作 shell 分开避免排队）
            interval: 刷新间隔（秒）
            debug:    是否打印每轮监控结果
        """
        self.shell = shell
        self.interval = interval
        self.debug = debug

        # 缓存的状态字段
        self.is_playing = False
        self.volume = 8
        self.max_volume = 15
        self.muted = False

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        """启动后台监控线程"""
        self._thread.start()

    def stop(self):
        """请求停止监控线程"""
        self._stop.set()

    def _loop(self):
        """监控主循环: 定时执行 adb 查询并更新缓存"""
        # 一次 shell 往返内完成两件事:
        #   1. 查音量
        #   2. 查 media_session 和 audio 的播放状态
        cmd = (
            "media volume --show --stream 3; "
            "echo ---MS---; dumpsys media_session; "
            "echo ---AU---; dumpsys audio | grep AudioPlaybackConfiguration"
        )
        while not self._stop.is_set():
            try:
                out = self.shell.run(cmd, timeout=2.0)
                if out:
                    # 解析音量
                    m = re.search(r"volume is (\d+) in range \[0\.\.(\d+)\]", out)
                    if m:
                        self.volume = int(m.group(1))
                        self.max_volume = int(m.group(2))
                        self.muted = self.volume == 0
                    # 解析播放状态
                    self.is_playing = parse_playing_from_dumps(out)
                    if self.debug:
                        print(
                            f"[monitor] vol={self.volume}/{self.max_volume} "
                            f"playing={self.is_playing}"
                        )
            except Exception as e:
                if self.debug:
                    print(f"[monitor] 异常: {e}")
            # 使用 wait 而非 sleep，让 stop() 可以立即唤醒
            self._stop.wait(self.interval)


# ============================================================
# CLI 命令实现
# ============================================================


def adb_devices():
    """列出当前通过 adb 连接的所有设备"""
    code, out, err = run_adb(["devices"])
    if code != 0:
        print(f"❌ 获取设备列表失败: {err}")
        return
    # 跳过第一行 "List of devices attached"
    lines = [l for l in out.splitlines()[1:] if l.strip()]
    if not lines:
        print("📭 当前没有已连接的设备")
        return
    print("📱 已连接的设备：")
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, status = parts[0], parts[1]
        icon = "✅" if status == "device" else "⚠️"
        print(f"   {icon} {serial}  [{status}]")


def adb_connect(address):
    """
    通过 Wi-Fi 连接手机。

    参数:
        address: IP 地址，可带端口。不带端口时默认 5555，
                 例如 "192.168.1.100" 或 "192.168.1.100:5555"
    """
    if ":" not in address:
        address = f"{address}:5555"
    print(f"🔌 正在连接 {address} ...")
    code, out, err = run_adb(["connect", address], timeout=15)
    if "connected" in out.lower() and "cannot" not in out.lower():
        print(f"✅ 连接成功: {out}")
        adb_devices()
    elif "already connected" in out.lower():
        print(f"ℹ️  {out}")
    else:
        print(f"❌ 连接失败: {out or err}")


def adb_disconnect(address=None):
    """
    断开无线连接。

    参数:
        address: 指定要断开的设备 IP；为 None 时断开所有 TCP/IP 连接
    """
    if address and ":" not in address:
        address = f"{address}:5555"
    args = ["disconnect"] + ([address] if address else [])
    code, out, err = run_adb(args)
    print(f"🔌 {out or err or '已断开'}")


# ============================================================
# 对讲机键逻辑
# ============================================================

# PTT 状态机:
#   active:        当前是否处于"按住"状态
#   saved_volume:  按下时保存的音量；None 表示按下时未执行操作（无音频播放）
_ptt_state = {"active": False, "saved_volume": None}

# 全局 shell 与 monitor 实例（在 start_hotkey_listener 中初始化）
_action_shell: AdbShell = None
_monitor: DeviceMonitor = None


def query_is_playing_now(timeout=1.5):
    """
    PTT 按下瞬间的实时查询——绕过缓存直读当前状态。

    为什么要实时查询？
        监控线程有 0.2s 刷新间隔，如果恰好刚暂停但缓存还是旧值（is_playing=True），
        按下 PTT 就会错误地发送 PLAY_PAUSE，把已暂停的音频切成播放。

    参数:
        timeout: adb 查询超时秒数

    返回:
        True  手机正在播放音频
        False 无音频播放
    """
    # 注意: toybox grep 不支持 \| 交替语法，过滤逻辑必须放 Python 端
    cmd = (
        "dumpsys media_session | grep -m1 'state=PLAYING(3)' ; "
        "dumpsys audio | grep AudioPlaybackConfiguration"
    )
    out = _action_shell.run(cmd, timeout=timeout)
    if not out:
        return False

    # 快速通道: 标准 MediaSession
    if "state=PLAYING(3)" in out:
        return True

    # 慢速通道: dumpsys audio，Python 端过滤静音轨
    for line in out.splitlines():
        if "AudioPlaybackConfiguration" not in line:
            continue
        if "state:started" not in line:
            continue
        # 排除静音轨（抖音等 App 保留的预加载轨）
        if "mutedState:clientVolume" in line or "mutedState:muted" in line:
            continue
        return True

    return False


def on_ptt_press(event=None):
    """
    PTT 键按下回调: 若手机有音频播放 → 静音 + 暂停。

    event 参数由 keyboard 库传入，这里不使用。
    """
    # 忽略按键自动重复
    if _ptt_state["active"]:
        return
    _ptt_state["active"] = True

    t0 = time.monotonic()

    # 实时查询，避免读到滞后的缓存
    if not query_is_playing_now():
        _ptt_state["saved_volume"] = None
        print(
            f"⏭️  [{PTT_KEY}] 无音频播放，跳过 ({1000 * (time.monotonic() - t0):.0f}ms)"
        )
        return

    # 记录音量（避免记录到 0）
    saved_vol = _monitor.volume if _monitor.volume > 0 else 8
    _ptt_state["saved_volume"] = saved_vol

    # 一次 adb 往返完成: 音量置 0 + 发送 PLAY_PAUSE
    # 用 PLAY_PAUSE(85) 而非 PAUSE(127): 部分 App 会把 127 也当 toggle
    _action_shell.run(
        f"media volume --stream 3 --set 0; input keyevent {KEYCODE_MEDIA_PLAY_PAUSE}",
        timeout=1.5,
    )
    dt = 1000 * (time.monotonic() - t0)
    print(f"🔇 [{PTT_KEY}] 按下：静音(原 {saved_vol}) + 暂停  [{dt:.0f}ms]")


def on_ptt_release(event=None):
    """
    PTT 键松开回调: 恢复音量 + 继续播放。

    如果按下时因为没有音频而跳过，这里也不做任何事。
    """
    if not _ptt_state["active"]:
        return
    _ptt_state["active"] = False

    vol = _ptt_state["saved_volume"]
    if vol is None:
        print(f"⏭️  [{PTT_KEY}] 松开：无需恢复")
        return

    t0 = time.monotonic()
    _action_shell.run(
        f"media volume --stream 3 --set {vol}; input keyevent {KEYCODE_MEDIA_PLAY_PAUSE}",
        timeout=1.5,
    )
    _ptt_state["saved_volume"] = None
    dt = 1000 * (time.monotonic() - t0)
    print(f"🔊 [{PTT_KEY}] 松开：恢复音量 {vol} + 播放  [{dt:.0f}ms]")


# ============================================================
# 普通热键动作
# ============================================================


def _debounce(func):
    """
    装饰器: 限制函数在 _DEBOUNCE_SECONDS 内最多触发一次。
    用于防止热键连击（例如按住 Ctrl+Alt+M 不放会重复触发）。
    """

    def wrapper(*args, **kwargs):
        global _last_trigger_time
        now = time.monotonic()
        if now - _last_trigger_time < _DEBOUNCE_SECONDS:
            return
        _last_trigger_time = now
        func(*args, **kwargs)

    return wrapper


def toggle_mute():
    """智能切换静音状态: 当前静音 → 取消（恢复一半音量）；否则静音"""
    if _monitor.muted or _monitor.volume == 0:
        target = _monitor.max_volume // 2 or 8
        _action_shell.run(f"media volume --stream 3 --set {target}")
        print(f"🔊 取消静音（音量 {target}）")
    else:
        _action_shell.run("media volume --stream 3 --set 0")
        print("🔇 已静音")


def media_play():
    """发送播放键"""
    _action_shell.run(f"input keyevent {KEYCODE_MEDIA_PLAY}")
    print("▶️  播放")


def media_pause():
    """发送暂停键"""
    _action_shell.run(f"input keyevent {KEYCODE_MEDIA_PAUSE}")
    print("⏸️  暂停")


def media_toggle():
    """发送播放/暂停切换键"""
    _action_shell.run(f"input keyevent {KEYCODE_MEDIA_PLAY_PAUSE}")
    print("⏯️  播放/暂停切换")


# ============================================================
# 启动热键监听
# ============================================================


def start_hotkey_listener():
    """
    初始化持久 shell、后台监控线程、注册全局热键，然后阻塞等待。
    用户按 Ctrl+C 时优雅退出。
    """
    global _action_shell, _monitor

    # 两个独立的 shell 会话:
    #   _action_shell: 执行操作（静音、暂停等）
    #   monitor_shell: 后台轮询状态
    # 分开是为了避免监控线程的查询与用户操作排队
    print("🔌 建立持久 adb shell 连接 ...")
    _action_shell = AdbShell(ADB_PATH)
    monitor_shell = AdbShell(ADB_PATH)

    print("🔍 启动后台监控线程 ...")
    _monitor = DeviceMonitor(
        monitor_shell, interval=MONITOR_INTERVAL, debug=MONITOR_DEBUG
    )
    _monitor.start()

    # 等第一轮监控跑完，让缓存里有初始值
    time.sleep(0.5)

    # 打印快捷键说明
    print("=" * 62)
    print("  ADB 控制 Android - 低延迟版已启用")
    print("=" * 62)
    print(f"  {PTT_KEY + ' (按住)':22s} → 有音频时静音+暂停 / 松开恢复")
    print(f"  {HOTKEY_MUTE_TOGGLE:22s} → 静音/取消静音")
    print(f"  {HOTKEY_PLAY_PAUSE:22s} → 播放/暂停 切换")
    print(f"  {HOTKEY_PLAY:22s} → 播放")
    print(f"  {HOTKEY_PAUSE:22s} → 暂停")
    print("=" * 62)
    print(
        f"  监控间隔: {MONITOR_INTERVAL}s   "
        f"(当前 is_playing={_monitor.is_playing}, volume={_monitor.volume})"
    )
    print("  按 Ctrl+C 退出\n")

    # 注册组合热键（带防抖）
    keyboard.add_hotkey(HOTKEY_MUTE_TOGGLE, _debounce(toggle_mute))
    keyboard.add_hotkey(HOTKEY_PLAY_PAUSE, _debounce(media_toggle))
    keyboard.add_hotkey(HOTKEY_PLAY, _debounce(media_play))
    keyboard.add_hotkey(HOTKEY_PAUSE, _debounce(media_pause))

    # 注册 PTT 键的按下/松开事件
    keyboard.on_press_key(PTT_KEY, on_ptt_press)
    keyboard.on_release_key(PTT_KEY, on_ptt_release)

    # 阻塞主线程，保持监听
    try:
        keyboard.wait()
    except KeyboardInterrupt:
        print("\n👋 已退出")
    finally:
        # 退出清理:
        # 1. 若 PTT 仍处于"已执行暂停"状态，恢复播放（避免手机停在静音）
        # 2. 关闭持久 shell
        if _ptt_state["active"] and _ptt_state["saved_volume"] is not None:
            on_ptt_release()
        _monitor.stop()
        _action_shell.close()
        monitor_shell.close()


# ============================================================
# CLI 入口
# ============================================================


def main():
    """命令行入口: 无参数启动监听，有参数则执行对应命令"""
    # 无参数 → 启动热键监听
    if len(sys.argv) < 2:
        start_hotkey_listener()
        return

    cmd = sys.argv[1].lower()

    # ---------- 连接管理 ----------
    if cmd == "connect":
        if len(sys.argv) < 3:
            print("用法: python adb_control.py connect <IP>[:端口]")
            sys.exit(1)
        adb_connect(sys.argv[2])
    elif cmd == "disconnect":
        adb_disconnect(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "devices":
        adb_devices()

    # ---------- 状态查询 ----------
    elif cmd == "playing":
        # 单次查询（一次性进程，不复用持久 shell）
        _, out, _ = run_adb(["shell", "dumpsys media_session"])
        _, out2, _ = run_adb(
            ["shell", "dumpsys audio | grep AudioPlaybackConfiguration"]
        )
        combined = out + "\n---AU---\n" + out2
        print(f"🎵 音频播放中: {parse_playing_from_dumps('---MS---' + combined)}")
    elif cmd == "status":
        _, out, _ = run_adb(["shell", "media", "volume", "--show", "--stream", "3"])
        print(out)
    elif cmd == "debug":
        # 打印两段原始输出，方便排查解析规则
        print("=== media_session (state 行) ===")
        _, out, _ = run_adb(["shell", "dumpsys media_session"])
        for line in out.splitlines():
            if "state" in line.lower():
                print("   ", line.strip())
        print("\n=== audio (AudioPlaybackConfiguration) ===")
        _, out, _ = run_adb(
            ["shell", "dumpsys audio | grep AudioPlaybackConfiguration"]
        )
        for line in out.splitlines():
            print("   ", line.strip())
    elif cmd == "audiodebug":
        # 对比播放/暂停时 AudioPlaybackConfiguration 的差异
        print(
            "🎬 请在手机上分别执行下面两组操作，对比 AudioPlaybackConfiguration 差异："
        )
        print("   1) 播放抖音音频时执行本命令")
        print("   2) 暂停抖音音频后再执行本命令\n")
        _, out, _ = run_adb(
            ["shell", "dumpsys audio | grep AudioPlaybackConfiguration"]
        )
        for line in out.splitlines():
            print("   ", line.strip())

    # ---------- 单次操作 ----------
    elif cmd == "mute":
        # 直接设置音量为 0
        run_adb(["shell", "media", "volume", "--stream", "3", "--set", "0"])
        print("🔇 已静音")
    elif cmd == "unmute":
        # 恢复到最大音量的一半
        _, out, _ = run_adb(["shell", "media", "volume", "--show", "--stream", "3"])
        m = re.search(r"in range \[0\.\.(\d+)\]", out)
        target = (int(m.group(1)) // 2) if m else 8
        run_adb(["shell", "media", "volume", "--stream", "3", "--set", str(target)])
        print(f"🔊 已取消静音（音量 {target}）")
    elif cmd == "play":
        run_adb(["shell", "input", "keyevent", str(KEYCODE_MEDIA_PLAY)])
        print("▶️  播放")
    elif cmd == "pause":
        run_adb(["shell", "input", "keyevent", str(KEYCODE_MEDIA_PAUSE)])
        print("⏸️  暂停")
    elif cmd == "toggle":
        run_adb(["shell", "input", "keyevent", str(KEYCODE_MEDIA_PLAY_PAUSE)])
        print("⏯️  播放/暂停切换")

    else:
        print(f"❌ 未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
