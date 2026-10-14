"""
CapsWriter 托盘图标诊断脚本
===========================

用途：排查「管理员运行能显示托盘图标 / 普通权限运行不显示」的现象。

运行方式（在真实桌面 pwsh 或 cmd 中）：
    普通权限跑一次：  runtime\\python.exe dev\\tray_diag.py
    管理员权限跑一次： gsudo runtime\\python.exe dev\\tray_diag.py
    两次结果对比即可定位差异。

脚本会打印三类证据：
  1. 当前进程自身的完整性级别 + 窗口站 / 桌面名
  2. explorer.exe（任务栏 / 托盘宿主）的完整性级别 + 会话
  3. 直接调用 Win32 Shell_NotifyIconW 注册一个真实托盘图标，返回是否成功，
     并暂停等待你肉眼确认托盘（含 ^ 折叠区）里是否出现了图标。

原理：
  托盘图标由交互 shell（explorer.exe 的通知区域窗口）承载。
  若 explorer 以提升权限（High integrity）运行，UIPI 会拦截普通完整性
  （Medium）进程发来的通知消息，导致图标静默不出现；而同为提升权限的
  进程则能正常注册、显示。
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25

INTEGRITY_NAMES = {  # 正确映射：S-1-16 子权威值 -> 级别
    0x00000000: "Untrusted",
    0x00001000: "Low",
    0x00002000: "Medium",
    0x00003000: "High",
    0x00004000: "System",
}


def integrity_of(pid: int) -> str:
    """读取进程完整性级别（S-1-16-xxxxx -> 可读名）。"""
    # 正确设置参数类型，避免 64 位指针截断
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    advapi32.OpenProcessToken.restype = wt.BOOL
    advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    advapi32.GetTokenInformation.restype = wt.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)
    ]
    advapi32.ConvertSidToStringSidW.restype = wt.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.LPWSTR)]

    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return f"(无法打开进程 pid={pid}, err={ctypes.get_last_error()})"
    try:
        th = wt.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(th)):
            return f"(OpenProcessToken err={ctypes.get_last_error()})"
        try:
            size = wt.DWORD(0)
            # 先查需要的缓冲区长度
            advapi32.GetTokenInformation(th, TokenIntegrityLevel, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(
                th, TokenIntegrityLevel, buf, size.value, ctypes.byref(size)
            ):
                return f"(GetTokenInformation err={ctypes.get_last_error()})"
            # TOKEN_MANDATORY_LABEL = { SID_AND_ATTRIBUTES Label }，
            # SID_AND_ATTRIBUTES = { PSID Sid; DWORD Attributes }，
            # 缓冲区开头是一个指向 SID 的指针，先解引用取出真正的 SID 地址。
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents.value
            psid = ctypes.c_void_p(sid_ptr)
            sid_str_ptr = wt.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(sid_str_ptr)):
                return f"(ConvertSidToStringSid err={ctypes.get_last_error()})"
            sid_str = ctypes.wstring_at(sid_str_ptr)
            # 形如 S-1-16-8192 / 12288 / 4096 ...
            val = int(sid_str.rsplit("-", 1)[1])
            return f"{INTEGRITY_NAMES.get(val, '?')} (0x{val:X})"
        finally:
            kernel32.CloseHandle(th)
    finally:
        kernel32.CloseHandle(h)


def obj_name(handle, info_class: int) -> str:
    """读取窗口站（UOI_NAME=2）或桌面（UOI_NAME=1）名称。"""
    user32.GetUserObjectInformationW.argtypes = [
        wt.HANDLE, ctypes.c_int, wt.LPWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD)
    ]
    user32.GetUserObjectInformationW.restype = wt.BOOL
    buf = ctypes.create_unicode_buffer(256)
    n = wt.DWORD(0)
    if user32.GetUserObjectInformationW(handle, info_class, buf, ctypes.sizeof(buf), ctypes.byref(n)):
        return buf.value
    return f"(err={ctypes.get_last_error()})"


def window_station_name() -> str:
    user32.GetProcessWindowStation.restype = wt.HANDLE
    return obj_name(user32.GetProcessWindowStation(), 2)


def desktop_name() -> str:
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    user32.GetThreadDesktop.restype = wt.HANDLE
    user32.GetThreadDesktop.argtypes = [wt.DWORD]
    return obj_name(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()), 1)


def resolve_pids_by_name(name: str) -> list:
    """把进程名解析为 pid 列表（用 tasklist CSV；失败返回空）。"""
    try:
        raw = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = []
        for line in raw.stdout.splitlines():
            parts = [p.strip('"') for p in line.strip().split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                out.append(int(parts[1]))
        return out
    except Exception:  # noqa: BLE001
        return []


def list_explorer() -> list:
    """用 tasklist 列出 explorer.exe（返回 (pid, session, name) 列表）。失败返回空。"""
    out = []
    try:
        raw = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in raw.stdout.splitlines():
            line = line.strip()
            if "explorer.exe" not in line.lower():
                continue
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 3 and parts[1].isdigit():
                out.append((int(parts[1]), parts[2], parts[0]))
    except Exception as e:  # noqa: BLE001
        print(f"  (tasklist 枚举失败: {e})")
    return out


# --- Shell_NotifyIcon 真实注册测试 ----------------------------------------------

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
WM_APP = 0x8000

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    """ctypes.wintypes 没有 WNDCLASSW，手动定义。"""
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    """ctypes.wintypes 没有 NOTIFYICONDATAW，手动定义（与 Win32 NOTIFYICONDATAW V2 对齐）。"""
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeoutOrVersion", wt.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wt.HICON),
    ]


# 模块级持有 WNDPROC 回调，防止窗口仍存在时回调对象被 GC 释放（悬空指针 -> 访问违例 0x90）。
_TRAY_WNDPROC_HOLDER = None


def tray_test(icon_path: str):
    """创建隐藏窗口并注册一个真实托盘图标。返回 (add_ok, hwnd)。"""
    global _TRAY_WNDPROC_HOLDER
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.RegisterClassW.restype = wt.ATOM
    user32.CreateWindowExW.restype = wt.HWND
    user32.LoadImageW.restype = wt.HANDLE
    shell32 = ctypes.windll.shell32
    shell32.Shell_NotifyIconW.restype = wt.BOOL

    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wt.HWND
    user32.DestroyWindow.argtypes = [wt.HWND]
    user32.LoadImageW.argtypes = [
        wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT,
    ]
    user32.LoadImageW.restype = wt.HANDLE
    shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.c_void_p]

    wc = WNDCLASSW()
    _TRAY_WNDPROC_HOLDER = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
    wc.lpfnWndProc = _TRAY_WNDPROC_HOLDER
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = "CapsWriterTrayDiagWnd"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        return False, None
    hwnd = user32.CreateWindowExW(
        0, wc.lpszClassName, "tray_diag", 0,
        -1, -1, 0, 0, None, None, wc.hInstance, None,
    )
    if not hwnd:
        return False, None
    hicon = user32.LoadImageW(None, icon_path, 1, 32, 32, 0x00000010)
    if not hicon:
        hicon = user32.LoadImageW(None, icon_path, 1, 16, 16, 0x00000010)
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(nid)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_TIP
    if hicon:
        nid.uFlags |= NIF_ICON
        nid.hIcon = hicon
    nid.uCallbackMessage = WM_APP + 1
    nid.szTip = "CapsWriter tray diag - 看到它说明注册成功"
    add_ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
    return add_ok, hwnd


def tray_remove(hwnd):
    if not hwnd:
        return
    shell32 = ctypes.windll.shell32
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(nid)
    nid.hWnd = hwnd
    nid.uID = 1
    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
    user32.DestroyWindow(hwnd)


def main() -> None:
    # `--self`：只打印当前进程自己的完整性级别，不注册托盘、不等待。
    if "--self" in sys.argv:
        print(f"pid={os.getpid()} integrity={integrity_of(os.getpid())}")
        return
    # 简易参数：`tray_diag.py --pid <pid|进程名>` 只打印完整性级别
    if "--pid" in sys.argv:
        i = sys.argv.index("--pid")
        if i + 1 < len(sys.argv):
            arg = sys.argv[i + 1]
            if arg.isdigit():
                pids = [int(arg)]
            else:
                pids = resolve_pids_by_name(arg)
            if not pids:
                print(f"（找不到进程 {arg}）")
                return
            for p in pids:
                print(f"pid={p} integrity={integrity_of(p)}")
            return
    print("=" * 62)
    print("CapsWriter 托盘图标诊断")
    print("=" * 62)
    print(f"[当前进程] pid={os.getpid()}  python={sys.version.split()[0]}")
    print(f"  integrity      : {integrity_of(os.getpid())}")
    print(f"  window station : {window_station_name()}")
    print(f"  desktop        : {desktop_name()}")
    print("-" * 62)
    print("[explorer.exe] 任务栏 / 托盘宿主：")
    exp = list_explorer()
    if not exp:
        print("  （未找到 explorer.exe —— 任务栏可能由其它 shell / 第三方工具承载）")
    for pid, session, name in exp:
        print(f"  pid={pid}  session={session}  integrity={integrity_of(pid)}")
    print("=" * 62)
    print("真实托盘图标注册测试（Shell_NotifyIconW NIM_ADD）：")
    print("  现在会尝试在系统托盘显示图标，请肉眼检查托盘（包括 ^ 折叠区）。")
    icon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "icon", "client-icon.ico",
    )
    add_ok, hwnd = tray_test(icon_path)
    print(f"  Shell_NotifyIconW(ADD) 返回: {add_ok!s}"
          f"  ->  {'注册成功(图标应在托盘)' if add_ok else '注册失败(被拦截/无托盘)'}")
    try:
        input("  按回车删除测试图标并结束 ...")
    except EOFError:
        time.sleep(5)
    tray_remove(hwnd)
    print("完成。")


if __name__ == "__main__":
    main()
