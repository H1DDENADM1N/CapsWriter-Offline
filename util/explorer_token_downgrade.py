# https://github.com/H1DDENADM1N/PyPrivilege/blob/main/explorer_token_downgrade.py

# 降权
# 已用户身份运行 notepad.exe

# gsudo uv run explorer_token_downgrade.py


import ctypes
import sys
from ctypes import wintypes


# ==========================================
# 权限检查
# ==========================================
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


# if not is_admin():
#     print("【严重错误】此脚本必须以管理员身份运行才能生效。")
#     print("请右键点击脚本 -> 以管理员身份运行，或在 VSCode 中以管理员身份启动。")
#     input("按回车键退出...")
#     sys.exit(1)

# ==========================================
# 常量定义
# ==========================================
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100

# 进程创建标志
# 0x01000000: CREATE_BREAKAWAY_FROM_JOB (关键：脱离Job对象)
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400

# 枚举常量
SecurityImpersonation = 2
TokenPrimary = 1


# ==========================================
# 结构体定义
# ==========================================
class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPBYTE),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


# ==========================================
# 加载 DLL
# ==========================================
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)


# ==========================================
# 核心函数
# ==========================================
def downgraded_via_explorer_token(executable_path):
    """
    使用 Explorer 令牌创建脱离 Job 对象的独立进程
    """
    # 1. 获取 Explorer 窗口句柄
    hwnd_shell = user32.GetShellWindow()
    if not hwnd_shell:
        raise Exception("无法获取 Shell 窗口句柄")

    # 2. 获取 Explorer 进程 ID
    explorer_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd_shell, ctypes.byref(explorer_pid))
    if not explorer_pid.value:
        raise Exception("无法获取 Explorer 进程 ID")

    print(f"正在从 Explorer (PID: {explorer_pid.value}) 获取令牌...")

    # 3. 打开 Explorer 进程
    h_process = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, explorer_pid.value
    )
    if not h_process:
        raise Exception(f"OpenProcess 失败: {kernel32.GetLastError()}")

    # 4. 打开 Explorer 的令牌
    h_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        h_process, TOKEN_DUPLICATE | TOKEN_QUERY, ctypes.byref(h_token)
    ):
        kernel32.CloseHandle(h_process)
        raise Exception(f"OpenProcessToken 失败: {kernel32.GetLastError()}")

    # 5. 复制令牌 (创建主令牌)
    h_new_token = wintypes.HANDLE()
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.bInheritHandle = False

    if not advapi32.DuplicateTokenEx(
        h_token,
        TOKEN_ASSIGN_PRIMARY
        | TOKEN_DUPLICATE
        | TOKEN_QUERY
        | TOKEN_ADJUST_DEFAULT
        | TOKEN_ADJUST_SESSIONID,
        ctypes.byref(sa),
        SecurityImpersonation,
        TokenPrimary,
        ctypes.byref(h_new_token),
    ):
        kernel32.CloseHandle(h_token)
        kernel32.CloseHandle(h_process)
        raise Exception(f"DuplicateTokenEx 失败: {kernel32.GetLastError()}")

    # 6. 准备启动信息
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()

    # 创建可写的 unicode 缓冲区
    # CreateProcessWithTokenW 会修改这个字符串来解析路径，必须是可写的
    command_line = ctypes.create_unicode_buffer(executable_path)

    # 7. 创建新进程
    creation_flags = CREATE_BREAKAWAY_FROM_JOB | CREATE_UNICODE_ENVIRONMENT

    success = advapi32.CreateProcessWithTokenW(
        h_new_token,  # hToken
        0,  # LogonFlags
        None,  # lpApplicationName (从命令行解析)
        command_line,  # lpCommandLine
        creation_flags,  # dwCreationFlags
        None,  # lpEnvironment
        None,  # lpCurrentDirectory
        ctypes.byref(si),  # lpStartupInfo
        ctypes.byref(pi),  # lpProcessInformation
    )

    # 清理句柄
    kernel32.CloseHandle(h_new_token)
    kernel32.CloseHandle(h_token)
    kernel32.CloseHandle(h_process)

    if not success:
        error_code = kernel32.GetLastError()
        raise Exception(f"CreateProcessWithTokenW 失败，错误代码: {error_code}")

    print(f"✅ 成功启动进程 (PID: {pi.dwProcessId})")
    print("✅ 该进程已使用 Explorer 令牌，并强制脱离 Job 对象，调试器无法杀死它。")

    # 关闭子进程句柄，让它彻底独立
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)

    return True


if __name__ == "__main__":
    if not is_admin():
        print("【严重错误】此脚本必须以管理员身份运行才能生效。")
        print("请右键点击脚本 -> 以管理员身份运行，或在 VSCode 中以管理员身份启动。")
        input("按回车键退出...")
        sys.exit(1)
    try:
        downgraded_via_explorer_token("notepad.exe")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        input("\n按回车键退出...")
