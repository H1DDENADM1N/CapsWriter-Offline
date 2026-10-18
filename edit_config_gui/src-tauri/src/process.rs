//! 服务进程检测与受限重启（规格 §9.4）。
//!
//! 两个清单**职责不同，不能合并**：
//!
//! - [`SERVER_PROCS`] / [`CLIENT_PROCS`] 只给 [`detect()`] 用，判断「在不在跑」；
//!   匹配规则与 `util/check_process.py:10-31` 一致：大小写不敏感、`.exe` 可省。
//!   名单照抄 `util/server/restart.py:53-57` 与 `util/client/restart.py:52-57`，
//!   其中 `python_CapsWriter_Server.exe` / `hint_while_recording.exe` /
//!   `deeplx_windows_amd64.exe` 是「检测对象」，不是「启动目标」。
//! - [`LAUNCHERS`] 只给 [`restart_launcher()`] 用，决定「能不能被拉起」：必须与
//!   字面量精确相等（大小写、空格、路径分隔符都不放宽）。前端一旦被注入，也只能
//!   在这三个固定名字里选，不能借这个命令启动白名单外的可执行文件。
//!
//! 重启时启动进程 **必须**显式传 `lpCurrentDirectory = config.toml 的父目录`：
//! `core_server.py:39-41` 与 `core_client.py:35-36` 都把 `os.getcwd()` 当作
//! `BASE_DIR` 来加载相对路径的模型与配置。旧 `util/server/restart.py:32-36` 的
//! `start "" "<exe>"` 没有传 cwd，只是因为旧编辑器（PyStand）的 cwd 恰好是仓库根
//! 才没有暴露问题；Tauri 产物从任意目录启动时就必须显式指定。
//!
//! 管理员身份下服务端启动要借 explorer 的令牌降权，否则会以管理员权限拉起服务端，
//! 导致客户端连不上（`util/server/restart.py:66-69`）。降权链路与
//! `util/explorer_token_downgrade.py:104-201` 等价：
//! `GetShellWindow` → `GetWindowThreadProcessId` → `OpenProcess` →
//! `OpenProcessToken` → `DuplicateTokenEx` → `CreateProcessWithTokenW`。
//! 任一步失败则回退普通 `CreateProcessW`，并返回 `degraded: true` 让 UI 明确提示，
//! 不允许静默假装成功。

use std::ffi::OsStr;
use std::path::{Path, PathBuf};

/// 「在跑就显示」的检测名单，含非启动器进程。
const SERVER_PROCS: [&str; 3] = [
    "start_server_gui.exe",
    "python_capswriter_server.exe",
    "deeplx_windows_amd64.exe",
];
const CLIENT_PROCS: [&str; 4] = [
    "start_client_gui_admin.exe",
    "start_client_gui.exe",
    "python_capswriter_client.exe",
    "hint_while_recording.exe",
];

/// 「允许被拉起」的启动器，比上面窄：`is_whitelisted` 只认这三个字面量。
const LAUNCHERS: [&str; 3] = [
    "start_server_gui.exe",
    "start_client_gui.exe",
    "start_client_gui_admin.exe",
];

/// 客户端启动器变体：检测时用它决定重启哪一个。
const CLIENT_ADMIN_EXE: &str = "start_client_gui_admin.exe";
const CLIENT_EXE: &str = "start_client_gui.exe";
const SERVER_EXE: &str = "start_server_gui.exe";

/// `windows_sys::Win32::System::SystemServices::MAXIMUM_ALLOWED` 的实测值
/// （`0x0200_0000`）。该常量在 windows-sys 0.59 里被 `Win32_System_SystemServices`
/// feature 门控，而本 crate 只启用了任务列出的 7 个 feature，所以按源码里的值在此
/// 本地定义，语义与直接引用该常量完全一致。
const MAXIMUM_ALLOWED: u32 = 0x0200_0000;

#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ServiceTarget {
    Server,
    Client,
}

/// `running_processes` 命令的返回值。字段用 camelCase 给前端（`clientVariant` /
/// `isAdmin`），与 `bridge.ts` 的 `RunningInfo` 一一对应。
#[derive(serde::Serialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct RunningInfo {
    pub server: bool,
    pub client: bool,
    pub client_variant: Option<String>,
    pub is_admin: bool,
}

#[derive(Debug)]
pub enum ProcError {
    NotWhitelisted(String),
    Spawn(String),
    Kill(String),
    Downgrade(String),
}

impl std::fmt::Display for ProcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ProcError::NotWhitelisted(name) => write!(f, "拒绝启动不在白名单内的程序：{name}"),
            ProcError::Spawn(e) => write!(f, "启动进程失败：{e}"),
            ProcError::Kill(e) => write!(f, "结束进程失败：{e}"),
            ProcError::Downgrade(e) => write!(f, "降权启动失败：{e}"),
        }
    }
}

impl std::error::Error for ProcError {}

#[derive(serde::Serialize, Debug, Clone, Copy)]
#[serde(rename_all = "camelCase")]
pub struct RestartOutcome {
    pub degraded: bool,
}

/// 进程名匹配：双向去 `.exe` + 小写比较。
///
/// 先用 `to_lowercase()` 再去后缀，所以 `Start_Server_GUI.EXE` 与
/// `start_server_gui` 也能匹配；`start_server_gui_admin` 不会误命中
/// `start_server_gui`（去后缀后是完整字符串比较，不是前缀匹配）。
pub fn name_matches(exe_name: &str, target: &str) -> bool {
    fn normalized(s: &str) -> String {
        let lower = s.to_lowercase();
        match lower.strip_suffix(".exe") {
            Some(stem) => stem.to_string(),
            None => lower,
        }
    }
    normalized(exe_name) == normalized(target)
}

/// 当前进程是否以管理员身份运行。`IsUserAnAdmin` 返回 `BOOL`（`i32`），非 0 为是。
fn is_admin() -> bool {
    unsafe { windows_sys::Win32::UI::Shell::IsUserAnAdmin() != 0 }
}

/// 扫描所有进程，判断服务端 / 客户端是否在跑。
///
/// `client_variant` 返回命中的**小写字面量**。若 admin 变体与普通变体同时在跑，
/// 优先记录 admin 变体：规格要求「检测到 admin 在跑就重启该变体」。
pub fn detect() -> RunningInfo {
    use sysinfo::{ProcessesToUpdate, System};

    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All, true);

    let mut server = false;
    let mut client = false;
    let mut client_variant: Option<String> = None;

    for proc_ in sys.processes().values() {
        let name = proc_.name().to_string_lossy();

        if SERVER_PROCS.iter().any(|target| name_matches(&name, target)) {
            server = true;
        }

        if CLIENT_PROCS.iter().any(|target| name_matches(&name, target)) {
            client = true;
            if name_matches(&name, CLIENT_ADMIN_EXE) {
                // admin 变体优先，避免 HashMap 遍历顺序影响变体选择
                client_variant = Some(CLIENT_ADMIN_EXE.to_string());
            } else if name_matches(&name, CLIENT_EXE) && client_variant.is_none() {
                client_variant = Some(CLIENT_EXE.to_string());
            }
        }
    }

    RunningInfo {
        server,
        client,
        client_variant,
        is_admin: is_admin(),
    }
}

/// 纯判定，不启动任何进程：名称必须与白名单中的某个字面量完全相等。
///
/// 不做 trim、不做大小写折叠、不接受路径 —— 前端只能传枚举，Rust 侧只认字面量。
pub fn is_whitelisted(name: &str) -> bool {
    LAUNCHERS.iter().any(|launcher| *launcher == name)
}

/// 结束 → 以 `base_dir` 为 cwd 重新拉起。
///
/// `base_dir` 必须由调用方传 `config.toml` 的父目录（见模块文档）。
/// `variant` 只在客户端有意义：`Some("start_client_gui_admin.exe")` 时重启 admin
/// 变体，其它值（含 `None`）一律重启普通客户端。
pub fn restart(
    target: ServiceTarget,
    base_dir: &Path,
    variant: Option<&str>,
) -> Result<RestartOutcome, ProcError> {
    let (procs, launcher): (&[&str], &str) = match target {
        ServiceTarget::Server => (&SERVER_PROCS, SERVER_EXE),
        ServiceTarget::Client => {
            if variant == Some(CLIENT_ADMIN_EXE) {
                (&CLIENT_PROCS, CLIENT_ADMIN_EXE)
            } else {
                (&CLIENT_PROCS, CLIENT_EXE)
            }
        }
    };

    // 与旧 `stop_server` / `stop_client` 一致：按整张表逐个 taskkill；
    // 参数分离、不经 shell，避免把进程名拼进命令行造成注入。
    kill_procs(procs)?;
    restart_launcher(launcher, base_dir)
}

/// 只允许白名单里的字面量；路径、`..`、绝对路径一律 `Err`。内部先过 [`is_whitelisted`]。
///
/// 管理员身份下先尝试借 explorer 的令牌降权启动；链路任一步失败就回退普通
/// `CreateProcessW`，此时返回值 `degraded == true`，UI 必须提示用户。
pub fn restart_launcher(name: &str, base_dir: &Path) -> Result<RestartOutcome, ProcError> {
    if !is_whitelisted(name) {
        return Err(ProcError::NotWhitelisted(name.into()));
    }

    let exe = resolve_launcher(name, base_dir);

    if !is_admin() {
        spawn_normal(&exe, base_dir)
            .map(|()| RestartOutcome { degraded: false })
            .map_err(ProcError::Spawn)
    } else {
        match spawn_downgraded(&exe, base_dir) {
            Ok(()) => Ok(RestartOutcome { degraded: false }),
            Err(downgrade_err) => match spawn_normal(&exe, base_dir) {
                Ok(()) => Ok(RestartOutcome { degraded: true }),
                Err(fallback_err) => Err(ProcError::Downgrade(format!(
                    "{downgrade_err}；回退普通启动也失败：{fallback_err}"
                ))),
            },
        }
    }
}

/// 解析启动器路径：优先 `base_dir`（仓库根），其次本 exe 同目录，最后原样交给
/// Win32 的搜索路径。`name` 已经过白名单校验，本身不含路径成分。
fn resolve_launcher(name: &str, base_dir: &Path) -> PathBuf {
    let in_base = base_dir.join(name);
    if in_base.is_file() {
        return in_base;
    }
    if let Ok(current) = std::env::current_exe() {
        if let Some(dir) = current.parent() {
            let in_exe_dir = dir.join(name);
            if in_exe_dir.is_file() {
                return in_exe_dir;
            }
        }
    }
    PathBuf::from(name)
}

/// `taskkill /IM <name> /F`。找不到进程（退出码 128 或本地化「没有找到」）不算错误。
fn kill_procs(names: &[&str]) -> Result<(), ProcError> {
    use std::os::windows::process::CommandExt;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    for name in names {
        let output = std::process::Command::new("taskkill")
            .args(["/IM", name, "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| ProcError::Kill(format!("无法执行 taskkill（{name}）：{e}")))?;

        if output.status.success() {
            continue;
        }

        // taskkill 的「没有找到进程」在不同语言/版本下文案不同，但退出码稳定为 128。
        let text = format!(
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        let not_found = output.status.code() == Some(128)
            || text.contains("没有找到")
            || text.contains("找不到")
            || text.to_lowercase().contains("not found");
        if not_found {
            continue;
        }

        return Err(ProcError::Kill(format!(
            "taskkill {name} 失败（退出码 {:?}）：{}",
            output.status.code(),
            text.trim()
        )));
    }
    Ok(())
}

/// 普通启动：`CreateProcessW`，`lpCurrentDirectory` 显式设为 `base_dir`。
fn spawn_normal(exe: &Path, base_dir: &Path) -> Result<(), String> {
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, PROCESS_INFORMATION, STARTUPINFOW,
    };

    let mut cmdline = command_line(exe);
    let cwd = wide(base_dir.as_os_str());
    let mut startup: STARTUPINFOW = unsafe { std::mem::zeroed() };
    startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
    let mut info: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };

    let ok = unsafe {
        CreateProcessW(
            std::ptr::null(),
            cmdline.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            0,
            0,
            std::ptr::null(),
            cwd.as_ptr(),
            &startup,
            &mut info,
        )
    };
    if ok == 0 {
        return Err(last_error("CreateProcessW"));
    }

    unsafe { close_process_info(&info) };
    Ok(())
}

/// 借 explorer 令牌降权启动。链路与 `util/explorer_token_downgrade.py:104-201` 等价。
///
/// 注意：`OpenProcessToken` 在 `windows_sys::Win32::System::Threading`，不在
/// `Win32::Security`（windows-sys 0.59 的实际归属）。
///
/// 此路径需要管理员身份才能端到端验证；非管理员会话下只会走 [`spawn_normal`]。
fn spawn_downgraded(exe: &Path, base_dir: &Path) -> Result<(), String> {
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::Security::{
        DuplicateTokenEx, SecurityImpersonation, TokenPrimary, TOKEN_DUPLICATE, TOKEN_QUERY,
    };
    use windows_sys::Win32::System::Threading::{
        OpenProcess, OpenProcessToken, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetShellWindow, GetWindowThreadProcessId};

    unsafe {
        // ① explorer 的 shell 窗口
        let hwnd = GetShellWindow();
        if hwnd.is_null() {
            return Err("GetShellWindow 返回空句柄（explorer 未运行？）".to_string());
        }

        // ② 窗口所属进程 PID
        let mut explorer_pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, &mut explorer_pid);
        if explorer_pid == 0 {
            return Err("GetWindowThreadProcessId 未能取得 explorer 进程 ID".to_string());
        }

        // ③ 打开 explorer 进程
        let h_process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, explorer_pid);
        if h_process.is_null() {
            return Err(last_error("OpenProcess"));
        }

        // ④ 打开 explorer 令牌
        let mut h_token: HANDLE = std::ptr::null_mut();
        if OpenProcessToken(h_process, TOKEN_DUPLICATE | TOKEN_QUERY, &mut h_token) == 0 {
            let err = last_error("OpenProcessToken");
            CloseHandle(h_process);
            return Err(err);
        }

        // ⑤ 复制成主令牌（MAXIMUM_ALLOWED 让 CreateProcessWithTokenW 有足够权限）
        let mut h_new_token: HANDLE = std::ptr::null_mut();
        if DuplicateTokenEx(
            h_token,
            MAXIMUM_ALLOWED,
            std::ptr::null(),
            SecurityImpersonation,
            TokenPrimary,
            &mut h_new_token,
        ) == 0
        {
            let err = last_error("DuplicateTokenEx");
            CloseHandle(h_token);
            CloseHandle(h_process);
            return Err(err);
        }

        // ⑥ 以复制出的令牌创建进程
        let result = spawn_with_token(h_new_token, exe, base_dir);

        CloseHandle(h_new_token);
        CloseHandle(h_token);
        CloseHandle(h_process);
        result
    }
}

/// `CreateProcessWithTokenW`，同样显式传 `lpCurrentDirectory`。
fn spawn_with_token(
    token: windows_sys::Win32::Foundation::HANDLE,
    exe: &Path,
    base_dir: &Path,
) -> Result<(), String> {
    use windows_sys::Win32::System::Threading::{
        CreateProcessWithTokenW, PROCESS_INFORMATION, STARTUPINFOW,
    };

    let mut cmdline = command_line(exe);
    let cwd = wide(base_dir.as_os_str());
    let mut startup: STARTUPINFOW = unsafe { std::mem::zeroed() };
    startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
    let mut info: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };

    let ok = unsafe {
        CreateProcessWithTokenW(
            token,
            0,
            std::ptr::null(),
            cmdline.as_mut_ptr(),
            0,
            std::ptr::null(),
            cwd.as_ptr(),
            &startup,
            &mut info,
        )
    };
    if ok == 0 {
        return Err(last_error("CreateProcessWithTokenW"));
    }

    unsafe { close_process_info(&info) };
    Ok(())
}

/// 关闭 `PROCESS_INFORMATION` 里的两个句柄；空句柄直接跳过。
unsafe fn close_process_info(info: &windows_sys::Win32::System::Threading::PROCESS_INFORMATION) {
    use windows_sys::Win32::Foundation::CloseHandle;

    if !info.hProcess.is_null() {
        CloseHandle(info.hProcess);
    }
    if !info.hThread.is_null() {
        CloseHandle(info.hThread);
    }
}

/// GetLastError + 本地化系统错误文案。
fn last_error(operation: &str) -> String {
    let code = unsafe { windows_sys::Win32::Foundation::GetLastError() };
    format!(
        "{operation} 失败（错误码 {code}：{}）",
        std::io::Error::from_raw_os_error(code as i32)
    )
}

fn wide(s: &OsStr) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;

    let mut v: Vec<u16> = s.encode_wide().collect();
    v.push(0);
    v
}

/// 可写的 UTF-16 命令行：`CreateProcess*W` 会就地修改这个缓冲区。
fn command_line(exe: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;

    let mut v: Vec<u16> = Vec::with_capacity(exe.as_os_str().len() + 3);
    v.push('"' as u16);
    v.extend(exe.as_os_str().encode_wide());
    v.push('"' as u16);
    v.push(0);
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn whitelist_has_no_core_scripts() {
        // core_server.py / core_client.py 不是启动器，不得作为匹配目标
        for n in SERVER_PROCS.iter().chain(CLIENT_PROCS.iter()) {
            assert!(!n.contains("core_"), "{n}");
        }
    }

    #[test]
    fn name_match_rules() {
        assert!(name_matches("start_server_gui.exe", "start_server_gui"));
        assert!(name_matches("Start_Server_GUI.EXE", "start_server_gui.exe"));
        assert!(!name_matches(
            "start_server_gui_admin.exe",
            "start_server_gui"
        ));
        assert!(!name_matches("python.exe", "start_server_gui"));
    }

    #[test]
    fn detect_does_not_panic() {
        let info = detect();
        let _ = (info.server, info.client, info.client_variant, info.is_admin);
    }

    #[test]
    fn whitelist_rejects_path_like_names() {
        // 这条测试只调用纯判定函数，不会启动任何进程
        for bad in [
            r"C:\Windows\System32\cmd.exe",
            r"..\..\evil.exe",
            r".\start_server_gui.exe",
            "start_server_gui.exe ",      // 尾随空格
            "START_SERVER_GUI.EXE",       // 大小写与字面量不同，必须被拒（前端只能传枚举）
            "start_server_gui_admin.exe", // 客户端变体，不在服务端启动器白名单
            "",
        ] {
            assert!(!is_whitelisted(bad), "{bad:?} 不应通过白名单");
        }
    }

    #[test]
    fn whitelist_accepts_exact_literal_names() {
        assert!(is_whitelisted("start_server_gui.exe"));
        assert!(is_whitelisted("start_client_gui.exe"));
        assert!(is_whitelisted("start_client_gui_admin.exe"));
        // 被「检测」的进程不等于「启动器」：python_CapsWriter_Server.exe 只能被 kill，不能作为启动目标
        assert!(!is_whitelisted("python_CapsWriter_Server.exe"));
        assert!(!is_whitelisted("hint_while_recording.exe"));
        assert!(!is_whitelisted("deeplx_windows_amd64.exe"));
    }
}
