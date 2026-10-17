#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADB 控制手机（录音期静音 + 暂停播放）

用途:
    CapsWriter 开始录音时，若手机上确有音频在播放，则把媒体流（stream 3）音量置 0
    并发送播放/暂停键暂停手机外放；录音结束后恢复原音量并继续播放，避免手机声音
    被麦克风录入。

    这是 tests/adb_control.py 的精简版：只保留录音所需的接口，刻意不做 DeviceMonitor
    后台轮询线程，改为录音开始时做一次实时查询，降低对手机的常驻开销。

公共 API（FROZEN，不得改名/改签名）:
    ensure_connected() -> bool
    pause_for_recording() -> None
    resume_after_recording() -> None
    close() -> None
"""

import re
import shutil
import subprocess
import threading
import time

from util.config import ClientConfig as Config
from util.client.cosmic import console

__all__ = [
    "ensure_connected",
    "pause_for_recording",
    "resume_after_recording",
    "close",
]

# adb 可执行文件路径。若已加入系统 PATH，保持 "adb" 即可
ADB_PATH = "adb"

# Android 音乐流编号与媒体播放/暂停切换键码
MEDIA_STREAM = 3
KEYCODE_MEDIA_PLAY_PAUSE = 85

# 记录不到有效音量时的兜底恢复值
DEFAULT_VOLUME = 8

# 查询与操作的单次 adb 往返超时（秒）。必须短，避免阻塞按键钩子线程
CMD_TIMEOUT = 1.0

# 连接/设备列表的进程级超时（秒）
CONNECT_TIMEOUT = 10


# ============================================================
# AdbShell: 持久 adb shell 会话（复用 tests/adb_control.py 的标记机制）
# ============================================================


class AdbShell:
    """
    持久 adb shell 会话。

    只启动一个长驻的 `adb shell` 进程，后续命令通过 stdin 发送、通过 stdout 读取，
    单次往返远低于每次新起进程的开销。

    关键技术点:
        1. 命令结束检测: 用唯一 marker (echo __DONE_xxx__) 标记命令输出结尾
        2. PTY 回显剥离: adb shell 分配 PTY 会把输入的命令回显到输出，
           用唯一 unique 标记包裹命令，取最后一次出现的 unique 之后的内容
    """

    def __init__(self, adb_path=ADB_PATH, device=None):
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
        except Exception:
            # adb 缺失等异常静默处理: ensure_connected() 已负责向用户提示
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
            命令的输出文本（str）；超时或异常返回空字符串（视为失败）
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
            try:
                self.proc.stdin.close()
            except Exception:
                pass


# ============================================================
# 普通一次性 adb 调用（用于连接、设备列表等不频繁的操作）
# ============================================================


def run_adb(args, timeout=CONNECT_TIMEOUT):
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
            [ADB_PATH] + list(args),
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
    except Exception as e:
        return -1, "", str(e)


# ============================================================
# 状态解析
# ============================================================

# 匹配 media_session 中的播放状态:
#   state=PlaybackState {state=PLAYING(3), ...}
#   state=PlaybackState {state=3, ...}
_MS_PLAYING_RE = re.compile(
    r"state=PlaybackState\s*\{\s*state=(PLAYING\((\d+)\)|(\d+))"
)

# 匹配 `media volume --show --stream 3` 的输出，例如:
#   volume is 8 in range [0..15]
_VOLUME_RE = re.compile(r"volume is (\d+) in range \[0\.\.(\d+)\]")

# 录音开始时的一次往返查询: 音量 + 两个来源的播放状态
_QUERY_CMD = (
    f"media volume --show --stream {MEDIA_STREAM}; "
    "echo ---MS---; dumpsys media_session | grep -m1 'state=PLAYING(3)' ; "
    "echo ---AU---; dumpsys audio | grep AudioPlaybackConfiguration"
)


def _is_playing(out):
    """
    从合并的 dumpsys 输出判断手机是否有音频在播放。

    双来源判定（任一命中即为播放中）:
        1. dumpsys media_session: state=PlaybackState {state=PLAYING(3)}
           适用于实现了标准 MediaSession 的 App（网易云、QQ音乐、B站等）
        2. dumpsys audio: AudioPlaybackConfiguration ... state:started
           适用于没有 MediaSession 的 App（抖音、快手等短视频）
           * 必须排除 mutedState:clientVolume / mutedState:muted 的静音轨
             （抖音播放时会保留一条静音轨用于预加载，它的 state 也是 started）

    参数:
        out: 含 ---MS--- / ---AU--- 分隔的合并输出文本

    返回:
        True 有音频在播放；False 无音频播放
    """
    if not out:
        return False

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


def _parse_volume(out):
    """从查询输出解析 stream 3 当前音量；解析不到返回 0"""
    m = _VOLUME_RE.search(out or "")
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0


# ============================================================
# 模块级状态
# ============================================================

_lock = threading.Lock()  # 保护下述状态与 adb 操作序列
_paused = False  # 是否已执行「静音 + 暂停」，用于重入保护
_saved_volume = DEFAULT_VOLUME  # 暂停前记录的音量，恢复时使用
_shell = None  # 惰性创建的持久 AdbShell（复用）
_connect_attempted_addr = None  # 已对哪个地址做过 best-effort 连接（避免重复打印）


def _enabled():
    """读取配置开关；配置项缺失时视为关闭（绝不抛异常）"""
    try:
        return bool(Config.enable_adb_control)
    except Exception:
        return False


def _resolve_addr():
    """
    解析配置中的手机地址。

    返回:
        形如 "192.168.1.100:5555" 的地址；未配置时返回空字符串
    """
    try:
        addr = str(Config.adb_addr).strip()
    except Exception:
        return ""
    if not addr:
        return ""
    if ":" not in addr:
        addr = f"{addr}:5555"
    return addr


def _device_state(addr):
    """
    查询 `adb devices` 中指定地址的状态。

    返回:
        "device" / "offline" / "unauthorized" 等状态字符串；未找到或失败返回 ""
    """
    try:
        code, out, err = run_adb(["devices"], timeout=CONNECT_TIMEOUT)
        if code != 0:
            return ""
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == addr:
                return parts[1]
        return ""
    except Exception:
        return ""


def _ensure_shell():
    """
    惰性创建/复用持久 shell。

    首次创建前对同一地址做一次 best-effort ensure_connected()，避免地址未连接时
    白白等待，也避免每次录音重复打印连接信息（换了地址则重新尝试）。
    地址未配置或创建失败时返回 None（调用方跳过本次操作）。

    重要: 持久 shell 必须通过 device 参数显式绑定配置里的地址，等价于
    `adb -s <addr> shell`，否则电脑上同时连着第二台设备时会打错设备。

    注意: 本函数必须在持有 _lock 时调用（状态一致性）。
    """
    global _shell, _connect_attempted_addr
    try:
        if _shell is None:
            addr = _resolve_addr()
            if not addr:
                return None
            # best-effort 连接: 同一地址只尝试一次（结果不影响后续，交给持久 shell 自己容错）
            if _connect_attempted_addr != addr:
                _connect_attempted_addr = addr
                ensure_connected()
            # 显式绑定目标设备，避免多设备时命令打到错误设备
            _shell = AdbShell(ADB_PATH, device=addr)
        return _shell
    except Exception:
        return None


# ============================================================
# FROZEN 公共 API
# ============================================================


def ensure_connected() -> bool:
    """
    确保配置中的手机地址已通过 adb 连接。

    流程:
        1. shutil.which 检查 adb 是否存在（缺失则红字提示并返回 False）
        2. `adb devices` 判断该地址状态是否为 device；是则直接返回 True
        3. 否则 `adb connect <addr>`，打印结果并复查 `adb devices`
        4. 成功返回 True；失败仅输出提示，不重试，返回 False

    绝不向外抛异常。
    """
    global _connect_attempted_addr
    try:
        if shutil.which(ADB_PATH) is None:
            console.print(
                f"[red]❌ 未找到 adb 可执行文件（{ADB_PATH}），"
                f"请安装 platform-tools 并加入 PATH[/red]"
            )
            return False

        addr = _resolve_addr()
        if not addr:
            console.print("[red]❌ 未配置 adb 地址（Config.adb_addr），无法连接手机[/red]")
            return False

        # 记录「本地址已尝试过连接」（成功/失败都记）。这样后续 _ensure_shell()
        # 不会在按键钩子线程里重复跑一遍 30s 的 devices/connect/devices 往返。
        # 注意: 行为不变——每次被显式调用仍执行下面的完整检查。
        _connect_attempted_addr = addr

        # 已经是 device 状态 → 无需重连
        if _device_state(addr) == "device":
            return True

        code, out, err = run_adb(["connect", addr], timeout=CONNECT_TIMEOUT)
        console.print(f"[yellow]🔌 adb connect {addr}: {out or err or '无输出'}[/yellow]")

        # 复查一次，不重试
        if _device_state(addr) == "device":
            return True
        console.print(f"[red]❌ ADB 连接失败（{addr}），本次不控制手机[/red]")
        return False
    except Exception as e:
        console.print(f"[red]❌ ADB 连接检查异常: {e}[/red]")
        return False


def pause_for_recording() -> None:
    """
    录音开始: 若手机确有音频在播放 → 静音（stream 3 置 0）+ 发送播放/暂停键暂停。

    - 未开启 Config.enable_adb_control 时直接返回
    - 已处于 paused 状态则直接返回（双击序列重入保护）
    - 一次往返查询「是否在播放 + 当前音量」，查询超时/空输出视为未播放
    - 不在播放时完全不动（避免误触发播放）
    - 绝不向外抛异常
    """
    global _paused, _saved_volume
    try:
        if not _enabled():
            return
        with _lock:
            if _paused:
                return

            shell = _ensure_shell()
            if shell is None:
                return

            out = shell.run(_QUERY_CMD, timeout=CMD_TIMEOUT)
            if not out:
                return  # 超时/空输出 → 视为未播放，不做任何动作
            if not _is_playing(out):
                return

            # 记录音量（避免记录到 0）
            vol = _parse_volume(out)
            _saved_volume = vol if vol > 0 else DEFAULT_VOLUME

            # 一次 adb 往返完成: 音量置 0 + 发送 PLAY_PAUSE
            # 用 PLAY_PAUSE(85) 而非 PAUSE(127): 部分 App 会把 127 也当 toggle
            shell.run(
                f"media volume --stream {MEDIA_STREAM} --set 0; "
                f"input keyevent {KEYCODE_MEDIA_PLAY_PAUSE}",
                timeout=CMD_TIMEOUT,
            )
            _paused = True
    except Exception:
        # 兜底: 任何异常都不得影响录音主流程
        pass


def resume_after_recording() -> None:
    """
    录音结束: 若此前执行过「静音 + 暂停」，恢复原音量并继续播放。

    注意: 刻意不用 Config.enable_adb_control 门控——录音中途关闭开关，
          也必须能把手机恢复原状。

    绝不向外抛异常。
    """
    global _paused, _saved_volume
    try:
        with _lock:
            if not _paused:
                return
            shell = _shell
            vol = _saved_volume
            try:
                if shell is not None:
                    shell.run(
                        f"media volume --stream {MEDIA_STREAM} --set {vol}; "
                        f"input keyevent {KEYCODE_MEDIA_PLAY_PAUSE}",
                        timeout=CMD_TIMEOUT,
                    )
            finally:
                # 无论 adb 是否成功都复位状态，避免一直停在 paused
                _paused = False
                _saved_volume = DEFAULT_VOLUME
    except Exception:
        pass


def close() -> None:
    """
    关闭持久 adb shell 会话并释放资源。

    若关闭时仍处于「静音 + 暂停」状态（例如录音中途退出客户端），
    会先恢复原音量并继续播放，避免手机停在静音。

    绝不向外抛异常。
    """
    global _shell, _connect_attempted_addr, _paused, _saved_volume
    try:
        with _lock:
            shell = _shell
            # 先恢复手机（若此前暂停过），再关闭 shell
            try:
                if _paused and shell is not None:
                    shell.run(
                        f"media volume --stream {MEDIA_STREAM} --set {_saved_volume}; "
                        f"input keyevent {KEYCODE_MEDIA_PLAY_PAUSE}",
                        timeout=CMD_TIMEOUT,
                    )
            except Exception:
                pass
            finally:
                _paused = False
                _saved_volume = DEFAULT_VOLUME

            _shell = None
            _connect_attempted_addr = None  # 下次录音重新做一次 best-effort 连接检查
            if shell is not None:
                shell.close()
    except Exception:
        pass
