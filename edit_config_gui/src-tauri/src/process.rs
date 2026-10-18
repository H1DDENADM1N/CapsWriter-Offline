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
/// `isAdmin` / `clientAdmin` / `serverAdmin`），与 `bridge.ts` 的 `RunningInfo` 一一对应。
#[derive(serde::Serialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct RunningInfo {
    pub server: bool,
    pub client: bool,
    pub client_variant: Option<String>,
    pub is_admin: bool,
    /// 匹配到的客户端进程中**有任一**以管理员权限（elevated token）运行。
    ///
    /// 三次 token 查询全部失败（例如进程刚退出、权限不足）时，回退为
    /// `client_variant == "start_client_gui_admin.exe"`：admin 变体按约定就是提权启动的。
    pub client_admin: bool,
    /// 服务端是否为提权进程：一遍扫描中，**任一**命中 [`SERVER_PROCS`] 的进程的 token 判定
    /// 为提权即为真。与 `is_admin`（管理器自身是否管理员）无关——它描述的是被检测的服务端。
    ///
    /// token 查询**全失败**时为 `false`：服务端没有「admin 变体」这类可回退的字面量线索，
    /// 所以不猜（与 [`needs_elevation`] 的 Server 分支同源同值）。
    pub server_admin: bool,
}

#[derive(Debug)]
pub enum ProcError {
    NotWhitelisted(String),
    Spawn(String),
    Kill(String),
    Downgrade(String),
    /// 结束进程被系统拒绝（`taskkill` 报告的「拒绝访问」）。非管理员无法结束以管理员权限
    /// 运行的进程，此时正确的动作不是重试 kill，而是改走提权助手。
    AccessDenied(String),
}

impl std::fmt::Display for ProcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ProcError::NotWhitelisted(name) => write!(f, "拒绝启动不在白名单内的程序：{name}"),
            ProcError::Spawn(e) => write!(f, "启动进程失败：{e}"),
            ProcError::Kill(e) => write!(f, "结束进程失败：{e}"),
            ProcError::Downgrade(e) => write!(f, "降权启动失败：{e}"),
            ProcError::AccessDenied(msg) => {
                write!(f, "结束进程失败：拒绝访问（需管理员权限）：{msg}")
            }
        }
    }
}

impl std::error::Error for ProcError {}

#[derive(serde::Serialize, Debug, Clone, Copy)]
#[serde(rename_all = "camelCase")]
pub struct RestartOutcome {
    pub degraded: bool,
    /// `true` 表示**本次未做任何结束/启动**：检测到目标进程以管理员权限运行，调用方必须
    /// 改走提权路径（`restart_service_elevated`）。`degraded` 与它不会同时为真。
    pub needs_elevation: bool,
}

/// 重启时用什么令牌启动启动器。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LaunchPolicy {
    /// 当前进程是管理员时借 explorer 令牌降权（现有 `restart_launcher` 语义），失败回退
    /// 普通启动并置 `degraded = true`。非管理员身份下与普通启动等价。
    DowngradeWhenAdmin,
    /// 直接 `CreateProcessW`，保持调用者当前的权限形态。提权助手（本身已是 elevated）
    /// 用它把客户端拉起为管理员形态。
    InheritToken,
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

/// 一次进程扫描的原始结果。`detect()` 与 `needs_elevation()` 共用同一遍扫描，
/// 避免为了拿提权信息再遍历一次进程表。
struct ScanResult {
    server: bool,
    client: bool,
    client_variant: Option<String>,
    client_elevated: bool,
    client_elevation_known: bool,
    server_elevated: bool,
}

/// 扫描进程表：判断服务端/客户端是否在跑，并记录匹配到的进程里有没有提权进程。
///
/// 每一个命中的进程都做一次 `process_is_elevated`；`client_elevation_known` 表示至少有一次
/// token 查询对客户端成功返回了明确结论（`Some(_)`），全失败时为 `false`，供调用方回退。
/// 服务端没有可回退的字面量线索，所以只记 `server_elevated`。
fn scan() -> ScanResult {
    use sysinfo::{ProcessesToUpdate, System};

    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All, true);

    let mut result = ScanResult {
        server: false,
        client: false,
        client_variant: None,
        client_elevated: false,
        client_elevation_known: false,
        server_elevated: false,
    };

    for proc_ in sys.processes().values() {
        let name = proc_.name().to_string_lossy();

        if SERVER_PROCS.iter().any(|target| name_matches(&name, target)) {
            result.server = true;
            if process_is_elevated(proc_.pid().as_u32()) == Some(true) {
                result.server_elevated = true;
            }
        }

        if CLIENT_PROCS.iter().any(|target| name_matches(&name, target)) {
            result.client = true;
            if name_matches(&name, CLIENT_ADMIN_EXE) {
                // admin 变体优先，避免 HashMap 遍历顺序影响变体选择
                result.client_variant = Some(CLIENT_ADMIN_EXE.to_string());
            } else if name_matches(&name, CLIENT_EXE) && result.client_variant.is_none() {
                result.client_variant = Some(CLIENT_EXE.to_string());
            }
            match process_is_elevated(proc_.pid().as_u32()) {
                Some(elevated) => {
                    result.client_elevation_known = true;
                    result.client_elevated |= elevated;
                }
                None => {}
            }
        }
    }

    result
}

/// 客户端提权判定：有任一提权进程则为真；否则若 token 查询成功过则为假；三次全失败时
/// 回退「检测到的变体是 admin 启动器」。服务端同源的判定见 [`RunningInfo::server_admin`]。
fn client_admin_from(scan: &ScanResult) -> bool {
    if scan.client_elevated {
        true
    } else if scan.client_elevation_known {
        false
    } else {
        scan.client_variant.as_deref() == Some(CLIENT_ADMIN_EXE)
    }
}

/// 扫描所有进程，判断服务端 / 客户端是否在跑。
///
/// `client_variant` 返回命中的**小写字面量**。若 admin 变体与普通变体同时在跑，
/// 优先记录 admin 变体：规格要求「检测到 admin 在跑就重启该变体」。
pub fn detect() -> RunningInfo {
    let scan = scan();
    let client_admin = client_admin_from(&scan);

    RunningInfo {
        server: scan.server,
        client: scan.client,
        client_variant: scan.client_variant,
        is_admin: is_admin(),
        client_admin,
        server_admin: scan.server_elevated,
    }
}

/// 目标进程是否以管理员权限运行，`true` 表示「必须走提权路径才能结束/重启它」。
///
/// 当前进程已经是管理员时恒为 `false`（管理员本来就能结束提权进程，没有提权必要）。
/// 判定只读、**绝不结束任何进程**：真正的 kill 只发生在预检为假之后。
///
/// Server 用整张 [`SERVER_PROCS`] 表（进程组）判断；Client 与 `RunningInfo::client_admin`
/// 同一套语义（token 查询全失败时回退 admin 变体）。
pub fn needs_elevation(target: ServiceTarget) -> bool {
    if is_admin() {
        return false;
    }

    let scan = scan();
    match target {
        ServiceTarget::Server => {
            // 与 `RunningInfo::server_admin` 同源同值（都取自这一遍扫描的 `server_elevated`）：
            // 前端拿 server_admin 渲染，后端拿同一个布尔决定要不要走提权。
            // 查询全失败时回退 false：宁可尝试 kill（会得到明确的拒绝访问错误）也不想把
            // 用户无端引到 UAC；这里没有「admin 变体」这种可回退的字面量线索。
            scan.server_elevated
        }
        ServiceTarget::Client => client_admin_from(&scan),
    }
}

/// 读取一个进程的令牌提权状态。
///
/// `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` → `OpenProcessToken(TOKEN_QUERY)` →
/// `GetTokenInformation(TokenElevation)`。任何一步失败都返回 `None`，**绝不 panic**：
/// 进程可能恰好退出、也可能是低权限进程打不开的受保护进程，这些都不是错误。
pub fn process_is_elevated(pid: u32) -> Option<bool> {
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::Security::{
        GetTokenInformation, TokenElevation, TOKEN_ELEVATION, TOKEN_QUERY,
    };
    use windows_sys::Win32::System::Threading::{
        OpenProcess, OpenProcessToken, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    unsafe {
        let h_process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if h_process.is_null() {
            return None;
        }

        // OpenProcessToken 在 Win32::System::Threading（windows-sys 0.59 的实际归属），
        // GetTokenInformation 在 Win32::Security。
        let mut h_token: HANDLE = std::ptr::null_mut();
        if OpenProcessToken(h_process, TOKEN_QUERY, &mut h_token) == 0 {
            CloseHandle(h_process);
            return None;
        }

        let mut elevation: TOKEN_ELEVATION = std::mem::zeroed();
        let mut returned: u32 = 0;
        let ok = GetTokenInformation(
            h_token,
            TokenElevation,
            &mut elevation as *mut TOKEN_ELEVATION as *mut core::ffi::c_void,
            std::mem::size_of::<TOKEN_ELEVATION>() as u32,
            &mut returned,
        );

        CloseHandle(h_token);
        CloseHandle(h_process);

        if ok == 0 {
            None
        } else {
            Some(elevation.TokenIsElevated != 0)
        }
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
///
/// 预检在 kill 之前：目标以管理员权限运行时（[`needs_elevation`]）直接返回
/// `needs_elevation = true`，**一个进程都不结束**——非管理员 kill 提权进程只会拿到
/// 「拒绝访问」，还会在拿到拒绝前就把同组的普通进程杀掉，留下半重启的坏状态。
pub fn restart(
    target: ServiceTarget,
    base_dir: &Path,
    variant: Option<&str>,
) -> Result<RestartOutcome, ProcError> {
    if needs_elevation(target) {
        return Ok(RestartOutcome {
            degraded: false,
            needs_elevation: true,
        });
    }

    restart_with_policy(target, base_dir, variant, LaunchPolicy::DowngradeWhenAdmin)
}

/// 按指定 [`LaunchPolicy`] 结束并重启：`InheritToken` 用于提权助手（保持 elevated），
/// `DowngradeWhenAdmin` 保持现有「管理员时借 explorer 令牌降权」的语义。
///
/// 返回值里的 `needs_elevation` **一律 false**：能不能提权由调用方在更外层决定
/// （父进程走 [`crate::elevate::spawn_elevated_helper`]，助手本身已经在提权上下文里）。
pub fn restart_with_policy(
    target: ServiceTarget,
    base_dir: &Path,
    variant: Option<&str>,
    policy: LaunchPolicy,
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
    match policy {
        LaunchPolicy::DowngradeWhenAdmin => restart_launcher(launcher, base_dir),
        LaunchPolicy::InheritToken => {
            let exe = resolve_launcher(launcher, base_dir);
            spawn_normal(&exe, base_dir)
                .map(|()| RestartOutcome {
                    degraded: false,
                    needs_elevation: false,
                })
                .map_err(ProcError::Spawn)
        }
    }
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
            .map(|()| RestartOutcome {
                degraded: false,
                needs_elevation: false,
            })
            .map_err(ProcError::Spawn)
    } else {
        match spawn_downgraded(&exe, base_dir) {
            Ok(()) => Ok(RestartOutcome {
                degraded: false,
                needs_elevation: false,
            }),
            Err(downgrade_err) => match spawn_normal(&exe, base_dir) {
                Ok(()) => Ok(RestartOutcome {
                    degraded: true,
                    needs_elevation: false,
                }),
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

/// 控制台输出的解码结果分类。退出码与文案都可能被系统本地化，所以两者一起看。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KillClass {
    /// 没有找到进程（退出码 128，或本地化「没有找到/找不到/not found」）：不是错误。
    NotFound,
    /// 拒绝访问：需要管理员权限，调用方应改走提权路径。
    Denied,
    /// 其它失败。
    Failed,
}

/// 把 `taskkill` 的退出码 + 输出归类。**纯函数**，只做字符串判断，可单测。
///
/// 判定顺序按契约固定：NotFound 优先（退出码 128 是所有语言下最稳的信号），再看拒绝
/// 访问，最后才是普通失败。
pub fn classify_taskkill(exit_code: Option<i32>, text: &str) -> KillClass {
    let lower = text.to_lowercase();

    if exit_code == Some(128)
        || text.contains("没有找到")
        || text.contains("找不到")
        || lower.contains("not found")
    {
        return KillClass::NotFound;
    }

    if text.contains("拒绝访问") || lower.contains("access is denied") || lower.contains("access denied")
    {
        return KillClass::Denied;
    }

    KillClass::Failed
}

/// 把控制台字节按**当前系统 ANSI 代码页**（`GetACP()`）解码成 `String`。
///
/// 这是乱码修复点：`taskkill` 在中文系统上输出 cp936 字节，`String::from_utf8_lossy`
/// 会把它们逐字节变成 U+FFFD 替换字符，用户看到的就是「???????」。`GetACP()` 在英文
/// 系统 + 中文区域设置下同样是 936（ACP 与显示语言无关），所以按它解码才能拿到原文。
///
/// 先按 `MB_ERR_INVALID_CHARS` 严格解码；某些代码页不接受该标志，失败则退回普通
/// （`dwFlags = 0`）解码；再失败或结果不是合法 UTF-16，最后退回 `from_utf8_lossy`。
pub fn decode_console_output(bytes: &[u8]) -> String {
    if !bytes.is_empty() {
        let code_page = unsafe { windows_sys::Win32::Globalization::GetACP() };
        for strict in [true, false] {
            if let Some(buf) = multi_byte_to_wide(code_page, bytes, strict) {
                if let Ok(text) = String::from_utf16(&buf) {
                    return text;
                }
            }
        }
    }
    String::from_utf8_lossy(bytes).into_owned()
}

/// 一次 `MultiByteToWideChar` 转换；`strict` 为真时带 `MB_ERR_INVALID_CHARS`。
/// 返回 `None` 表示该代码页 + 标志组合无法转换（此时调用方回退其它方案）。
fn multi_byte_to_wide(code_page: u32, bytes: &[u8], strict: bool) -> Option<Vec<u16>> {
    use windows_sys::Win32::Globalization::{MultiByteToWideChar, MB_ERR_INVALID_CHARS};

    let flags: u32 = if strict { MB_ERR_INVALID_CHARS } else { 0 };
    unsafe {
        let len = MultiByteToWideChar(
            code_page,
            flags,
            bytes.as_ptr(),
            bytes.len() as i32,
            std::ptr::null_mut(),
            0,
        );
        if len <= 0 {
            return None;
        }
        let mut buf: Vec<u16> = vec![0u16; len as usize];
        let written = MultiByteToWideChar(
            code_page,
            flags,
            bytes.as_ptr(),
            bytes.len() as i32,
            buf.as_mut_ptr(),
            len,
        );
        if written <= 0 {
            return None;
        }
        buf.truncate(written as usize);
        Some(buf)
    }
}

/// `taskkill /IM <name> /F`。找不到进程（退出码 128 或本地化「没有找到」）不算错误；
/// 拒绝访问转成 [`ProcError::AccessDenied`]，让上层改走提权路径。
fn kill_procs(names: &[&str]) -> Result<(), ProcError> {
    use std::os::windows::process::CommandExt;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    for name in names {
        let output = std::process::Command::new("taskkill")
            .args(["/IM", name, "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| ProcError::Kill(format!("无法执行 taskkill（{name}）：{e}")))?;

        // taskkill 的文案随系统语言变化（中文 cp936 / 英文 ASCII），必须按 ACP 解码再分类。
        let mut raw = output.stdout.clone();
        raw.extend_from_slice(&output.stderr);
        let text = decode_console_output(&raw);

        if output.status.success() {
            continue;
        }

        match classify_taskkill(output.status.code(), &text) {
            KillClass::NotFound => continue,
            KillClass::Denied => return Err(ProcError::AccessDenied(text.trim().to_string())),
            KillClass::Failed => {
                return Err(ProcError::Kill(format!(
                    "taskkill {name} 失败（退出码 {:?}）：{}",
                    output.status.code(),
                    text.trim()
                )))
            }
        }
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
        // 未运行的服务端不可能被判定为提权：没有命中进程时 `server_elevated` 必为 false。
        if !info.server {
            assert!(!info.server_admin);
        }
        let _ = (
            info.server,
            info.client,
            info.client_variant,
            info.is_admin,
            info.client_admin,
            info.server_admin,
        );
    }

    #[test]
    fn decode_console_output_decodes_cp936_denied() {
        // 「拒绝访问」在 cp936（=本机 ACP/OEMCP，实测均为 936）下的字节是
        // BE DC BE F8 B7 C3 CE CA（用 codepage 936 编码得到，已核对）。
        //
        // 注意：任务书里给的 E6 8B 92 E7 BB 9D E8 AE BF E9 97 AE 其实是「拒绝访问」的
        // **UTF-8** 字节；按 ACP=936 解码它只会得到「鎷掔粷璁块棶」（UTF-8 被当 GBK 读的
        // 典型乱码）。本测试用的是真正的 cp936 字节。
        let bytes: [u8; 8] = [0xBE, 0xDC, 0xBE, 0xF8, 0xB7, 0xC3, 0xCE, 0xCA];
        let acp = unsafe { windows_sys::Win32::Globalization::GetACP() };
        if acp == 936 {
            // 这正是乱码 bug：GBK 字节不是合法 UTF-8，from_utf8_lossy 只会得到替换字符。
            assert!(
                !String::from_utf8_lossy(&bytes).contains("拒绝访问"),
                "GBK 字节不应被当成 UTF-8 解出来"
            );
            assert_eq!(decode_console_output(&bytes), "拒绝访问");
        } else {
            eprintln!("本机 ACP={acp}，跳过 cp936 断言（仅验证不 panic）");
            let _ = decode_console_output(&bytes);
        }
    }

    #[test]
    fn decode_console_output_passes_ascii_through() {
        assert_eq!(
            decode_console_output(b"ERROR: The process \"x\" not found.\r\n"),
            "ERROR: The process \"x\" not found.\r\n"
        );
        assert_eq!(decode_console_output(b""), "");
    }

    #[test]
    fn classify_taskkill_branches() {
        // ① 退出码 128：任何语言下都最稳的「没有找到」
        assert_eq!(classify_taskkill(Some(128), ""), KillClass::NotFound);
        // ② 本地化文案（中文）
        assert_eq!(
            classify_taskkill(Some(1), "错误: 没有找到进程 \"x.exe\"。"),
            KillClass::NotFound
        );
        assert_eq!(
            classify_taskkill(Some(1), "找不到进程 x.exe"),
            KillClass::NotFound
        );
        // ③ 英文 not found（大小写不敏感）
        assert_eq!(
            classify_taskkill(Some(1), "ERROR: The process \"x\" NOT FOUND."),
            KillClass::NotFound
        );
        // ④ 拒绝访问（中文 / 英文，大小写不敏感）
        assert_eq!(classify_taskkill(Some(1), "错误: 拒绝访问。"), KillClass::Denied);
        assert_eq!(
            classify_taskkill(Some(1), "ERROR: Access is denied."),
            KillClass::Denied
        );
        assert_eq!(
            classify_taskkill(Some(1), "ACCESS DENIED"),
            KillClass::Denied
        );
        // ⑤ 其它非零退出
        assert_eq!(
            classify_taskkill(Some(1), "ERROR: Invalid argument/option"),
            KillClass::Failed
        );
        assert_eq!(classify_taskkill(None, ""), KillClass::Failed);
    }

    #[test]
    fn process_is_elevated_returns_a_verdict_for_self() {
        // 当前进程一定存在、也一定打得开令牌，所以必须是 Some(_)（true 或 false 都合法）。
        // 这条断言只读，不结束任何进程。
        assert!(process_is_elevated(std::process::id()).is_some());
    }

    #[test]
    fn needs_elevation_does_not_panic() {
        let _ = needs_elevation(ServiceTarget::Server);
        let _ = needs_elevation(ServiceTarget::Client);
    }

    /// 拼一个只含客户端部分的扫描结果，不依赖本机进程表。
    fn client_scan(
        client_variant: Option<&str>,
        client_elevated: bool,
        client_elevation_known: bool,
    ) -> ScanResult {
        ScanResult {
            server: false,
            client: true,
            client_variant: client_variant.map(str::to_string),
            client_elevated,
            client_elevation_known,
            server_elevated: false,
        }
    }

    /// 「客户端是不是管理员」的三分支回退是本模块最要紧的纯逻辑：它同时决定状态栏紫色
    /// 指示与「重启是否需要提权」。这里逐条钉死。
    #[test]
    fn client_admin_prefers_token_verdict_over_variant_name() {
        // ① token 查询成功且命中提权进程 → 管理员（与变体名无关）
        assert!(client_admin_from(&client_scan(
            Some(CLIENT_EXE),
            true,
            true
        )));
        // ② token 查询成功但没有任何提权进程 → 不是管理员，即使变体是 admin 启动器
        //    （UAC 被关掉/被绕过时会出现这种组合：名字是 admin，令牌实为中等完整性）
        assert!(!client_admin_from(&client_scan(
            Some(CLIENT_ADMIN_EXE),
            false,
            true
        )));
        // ③ 变体是普通启动器、查询成功且未提权 → 不是管理员
        assert!(!client_admin_from(&client_scan(
            Some(CLIENT_EXE),
            false,
            true
        )));
    }

    #[test]
    fn client_admin_falls_back_to_variant_only_when_token_query_failed() {
        // ④ 所有 token 查询都失败（None）→ 回退变体名：admin 变体视为管理员
        assert!(client_admin_from(&client_scan(
            Some(CLIENT_ADMIN_EXE),
            false,
            false
        )));
        // ⑤ 回退时变体是普通启动器或压根没有变体 → 不是管理员（宁可让 kill 去拿明确的
        //    「拒绝访问」再由命令层转成 needsElevation，也不无端把用户引到 UAC）
        assert!(!client_admin_from(&client_scan(
            Some(CLIENT_EXE),
            false,
            false
        )));
        assert!(!client_admin_from(&client_scan(None, false, false)));
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
