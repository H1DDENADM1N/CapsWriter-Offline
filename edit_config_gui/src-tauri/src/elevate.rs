//! 提权助手：非管理员会话无法结束/拉起重启「以管理员权限运行的服务」时的唯一出路。
//!
//! 背景：非管理员 `edit_config_gui` 重启管理员客户端时 `taskkill` 返回「拒绝访问」。
//! 系统不允许低权限进程结束高权限进程，也没有任何降权技巧能绕开——必须让**用户亲自
//! 授权**一次 UAC，在提权上下文里完成「结束 + 拉起」。
//!
//! 本模块有两个身份，同一个 exe 靠命令行开关切换：
//!
//! - **父进程侧** [`spawn_elevated_helper`]：`ShellExecuteExW(verb = "runas")` 拉起自己，
//!   带上 `--elevated-restart=<target> --nonce=<hex>`；等助手退出后从
//!   `%TEMP%\edit_config_gui_elevated_<nonce>.txt` 读回结果。`nonce` 让这次调用的结果文件
//!   无法被上一次的残留（或别的进程）冒充：路径里含随机数，启动前还会先删掉同名残留。
//! - **助手侧** [`run_if_requested`]：在 `main()` 最开头调用；只有真的带了
//!   `--elevated-restart` 标志才接管，写完结果文件就 `exit`，绝不进入 Tauri、绝不显示窗口。
//!
//! 安全边界：`target` 只认 `server` / `client` 两个字面量，助手再把它们映射到
//! [`process`] 里固定的白名单启动器；父进程侧不接受任何可执行文件路径或任意命令行。

use std::path::{Path, PathBuf};

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};

use crate::process::{self, LaunchPolicy, RestartOutcome, ServiceTarget};

/// 助手模式标志。
const FLAG_ELEVATED_RESTART: &str = "--elevated-restart=";
/// 一次性随机数标志；同时用于结果文件名，隔离并发/残留。
const FLAG_NONCE: &str = "--nonce=";
/// 等待助手完成的时限（UAC 弹窗期间用户可能停留一会儿）。
const HELPER_TIMEOUT_MS: u32 = 120_000;

/// 助手模式下解析出的请求。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HelperRequest {
    pub target: ServiceTarget,
    pub nonce: String,
}

/// 结果文件路径：`%TEMP%\edit_config_gui_elevated_<nonce>.txt`。
///
/// 公开是为了让测试能直接验证命名约定与落盘内容，不必去猜路径。
pub fn result_path(nonce: &str) -> PathBuf {
    std::env::temp_dir().join(format!("edit_config_gui_elevated_{nonce}.txt"))
}

/// 纯函数：从命令行参数里解析助手请求。**不读环境、不碰磁盘、不启动进程**。
///
/// - 没有 `--elevated-restart=` 标志 → `Ok(None)`：这是普通的 GUI 启动。
/// - 目标不是 `server` / `client` → `Err`（绝不把任意字符串当目标）。
/// - 缺 `--nonce` 或 nonce 不匹配 `^[0-9a-fA-F]{1,64}$` → `Err`。nonce 会进文件名，
///   严格限制字符集（只允许十六进制）就同时杜绝了 `../` 之类的路径穿越。
pub fn parse_helper_args(args: &[String]) -> Result<Option<HelperRequest>, String> {
    let mut target: Option<ServiceTarget> = None;
    let mut nonce: Option<String> = None;

    for arg in args {
        if let Some(value) = arg.strip_prefix(FLAG_ELEVATED_RESTART) {
            let parsed = match value {
                "server" => ServiceTarget::Server,
                "client" => ServiceTarget::Client,
                other => {
                    return Err(format!(
                        "--elevated-restart 的目标非法（只允许 server 或 client）：{other}"
                    ))
                }
            };
            target = Some(parsed);
        } else if let Some(value) = arg.strip_prefix(FLAG_NONCE) {
            nonce = Some(value.to_string());
        }
    }

    let Some(target) = target else {
        return Ok(None);
    };

    let Some(nonce) = nonce else {
        return Err("提权助手缺少 --nonce 参数".to_string());
    };
    if !nonce_is_valid(&nonce) {
        return Err(format!(
            "--nonce 非法（必须匹配 ^[0-9a-fA-F]{{1,64}}$）：{nonce}"
        ));
    }

    Ok(Some(HelperRequest { target, nonce }))
}

/// nonce 必须非空、长度 ≤ 64、且全部是 ASCII 十六进制字符。
fn nonce_is_valid(nonce: &str) -> bool {
    !nonce.is_empty() && nonce.len() <= 64 && nonce.bytes().all(|b| b.is_ascii_hexdigit())
}

/// 在参数里**尽量**找一个可用于结果文件名的 nonce；解析失败时也要能写结果文件，
/// 所以这里不校验十六进制，只保留文件名安全字符，避免路径穿越。
fn nonce_for_result(args: &[String]) -> String {
    let raw = args
        .iter()
        .find_map(|arg| arg.strip_prefix(FLAG_NONCE))
        .unwrap_or("invalid");
    let safe: String = raw
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .take(64)
        .collect();
    if safe.is_empty() {
        "invalid".to_string()
    } else {
        safe
    }
}

/// 助手入口：解析 `std::env::args()`，必要时执行重启并在结果文件里留下结论。
///
/// 返回值语义：
/// - `None` → 不是助手模式，调用方继续正常启动 GUI。
/// - `Some(0)` → 重启成功（`degraded` 时结果文件写 `degraded`）。
/// - `Some(1)` → 重启失败，结果文件写 `err:<msg>`。
/// - `Some(2)` → 参数非法（含目标非法），结果文件写 `err:<msg>`。
///
/// 助手只 `exit`，绝不显示窗口，也绝不进入 Tauri。
pub fn run_if_requested() -> Option<i32> {
    let args: Vec<String> = std::env::args().collect();

    match parse_helper_args(&args) {
        Ok(None) => None,
        Ok(Some(request)) => {
            // ShellExecuteExW 把 lpDirectory 设成了 base_dir（仓库根），所以 current_dir
            // 就是服务端 / 客户端需要的工作目录。
            let base_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
            // Server：助手的父进程（GUI）可能已经是管理员，降权语义要保持不变；
            // Client：用户要的就是「管理员形态的客户端」，直接继承助手的 elevated 令牌。
            let policy = match request.target {
                ServiceTarget::Server => LaunchPolicy::DowngradeWhenAdmin,
                ServiceTarget::Client => LaunchPolicy::InheritToken,
            };
            let variant = process::detect().client_variant;

            let outcome =
                process::restart_with_policy(request.target, &base_dir, variant.as_deref(), policy);

            let (text, code) = match outcome {
                Ok(outcome) if outcome.degraded => ("degraded".to_string(), 0),
                Ok(_) => ("ok".to_string(), 0),
                Err(err) => (format!("err:{err}"), 1),
            };
            let _ = std::fs::write(result_path(&request.nonce), text);
            Some(code)
        }
        Err(msg) => {
            let _ = std::fs::write(
                result_path(&nonce_for_result(&args)),
                format!("err:{msg}"),
            );
            Some(2)
        }
    }
}

/// 生成一次性 nonce：`SystemTime` 纳秒 + 当前 PID 的十六进制。不引入新依赖。
fn generate_nonce() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{nanos:x}{:x}", std::process::id())
}

/// 助手进程句柄 + 结果文件的统一清理者。
///
/// 成功、超时、读结果失败都必须关掉 `hProcess` 并删掉结果文件；用 `Drop` 兜底，
/// 早退路径就不可能漏清理（早先实现在 `read_to_string` 失败时两条都漏了）。
///
/// 注意：over-the-shoulder UAC（用户改用**另一个**管理员账号授权）时，助手把结果写进
/// 那个账号的 `%TEMP%`，父进程既读不到也删不掉那份残留——这里只保证父进程这一侧干净。
struct HelperGuard {
    process: Option<HANDLE>,
    result: PathBuf,
}

impl HelperGuard {
    fn new(process: HANDLE, result: PathBuf) -> Self {
        Self {
            process: Some(process),
            result,
        }
    }
}

impl Drop for HelperGuard {
    fn drop(&mut self) {
        if let Some(handle) = self.process.take() {
            unsafe { CloseHandle(handle) };
        }
        let _ = std::fs::remove_file(&self.result);
    }
}

/// 父进程侧：以 `runas` 拉起提权助手，等它结束后读回结果。
///
/// 失败路径的文案必须是前端可直接展示的：用户取消 UAC（错误码 1223）与真正的失败要
/// 能区分——取消时「未做任何改动」，不是错误。
pub fn spawn_elevated_helper(
    target: ServiceTarget,
    base_dir: &Path,
) -> Result<RestartOutcome, String> {
    use windows_sys::Win32::Foundation::{GetLastError, ERROR_CANCELLED, WAIT_OBJECT_0, WAIT_TIMEOUT};
    use windows_sys::Win32::System::Threading::{TerminateProcess, WaitForSingleObject};
    use windows_sys::Win32::UI::Shell::{
        ShellExecuteExW, SEE_MASK_NOCLOSEPROCESS, SHELLEXECUTEINFOW,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_HIDE;

    let nonce = generate_nonce();
    let path = result_path(&nonce);
    // 先删残留：同名文件只可能来自上次异常退出的调用，留着会被误当成本次结果。
    let _ = std::fs::remove_file(&path);

    let exe = std::env::current_exe().map_err(|e| format!("无法定位当前程序：{e}"))?;
    let target_arg = match target {
        ServiceTarget::Server => "server",
        ServiceTarget::Client => "client",
    };
    let parameters = format!("{FLAG_ELEVATED_RESTART}{target_arg} {FLAG_NONCE}{nonce}");

    let verb = wide("runas");
    let file = wide_os(exe.as_os_str());
    let params = wide(&parameters);
    let directory = wide_os(base_dir.as_os_str());

    let mut info: SHELLEXECUTEINFOW = unsafe { std::mem::zeroed() };
    info.cbSize = std::mem::size_of::<SHELLEXECUTEINFOW>() as u32;
    info.fMask = SEE_MASK_NOCLOSEPROCESS;
    info.lpVerb = verb.as_ptr();
    info.lpFile = file.as_ptr();
    info.lpParameters = params.as_ptr();
    info.lpDirectory = directory.as_ptr();
    info.nShow = SW_HIDE;

    let ok = unsafe { ShellExecuteExW(&mut info) };
    if ok == 0 {
        let code = unsafe { GetLastError() };
        return Err(if code == ERROR_CANCELLED {
            "已取消管理员授权（UAC），未做任何改动".to_string()
        } else {
            format!("拉起提权助手失败（ShellExecuteExW 错误码 {code}）")
        });
    }

    if info.hProcess.is_null() {
        return Err("提权助手未返回进程句柄".to_string());
    }

    let wait = unsafe { WaitForSingleObject(info.hProcess, HELPER_TIMEOUT_MS) };
    // 句柄与结果文件的清理全部交给 guard：读结果失败等早退路径同样会清干净。
    let _guard = HelperGuard::new(info.hProcess, path.clone());

    match wait {
        WAIT_OBJECT_0 => {}
        WAIT_TIMEOUT => {
            // 助手卡在启动逻辑里：先终止，再让 guard 回收句柄与结果文件。
            unsafe { TerminateProcess(info.hProcess, 1) };
            return Err("等待提权助手超时".to_string());
        }
        other => {
            // WAIT_FAILED / WAIT_ABANDONED：句柄可能已失效，不要 TerminateProcess。
            return Err(format!(
                "等待提权助手失败（WaitForSingleObject 返回 {other}）"
            ));
        }
    }

    let text = std::fs::read_to_string(&path)
        .map_err(|e| format!("读取提权助手结果失败：{e}"))?
        .trim()
        .to_string();

    match text.as_str() {
        "ok" => Ok(RestartOutcome {
            degraded: false,
            needs_elevation: false,
        }),
        "degraded" => Ok(RestartOutcome {
            degraded: true,
            needs_elevation: false,
        }),
        other => Err(other
            .strip_prefix("err:")
            .unwrap_or(other)
            .to_string()),
    }
}

/// NUL 结尾的 UTF-16 缓冲（ShellExecuteExW 的所有字符串参数都要求它）。
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// 同上，但对 OS 路径按原始宽字符编码，避免非 UTF-8 路径被有损转换。
fn wide_os(s: &std::ffi::OsStr) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;

    s.encode_wide().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn parse_helper_args_accepts_valid_request() {
        let parsed = parse_helper_args(&args(&[
            "edit_config_gui.exe",
            "--elevated-restart=client",
            "--nonce=a1B2c3",
        ]))
        .expect("合法参数不应报错")
        .expect("带了标志就必须返回请求");
        assert_eq!(parsed.target, ServiceTarget::Client);
        assert_eq!(parsed.nonce, "a1B2c3");

        let server = parse_helper_args(&args(&["--elevated-restart=server", "--nonce=DEADbeef"]))
            .unwrap()
            .unwrap();
        assert_eq!(server.target, ServiceTarget::Server);
    }

    #[test]
    fn parse_helper_args_returns_none_without_flag() {
        // 普通 GUI 启动：绝不能因为别的参数就进助手模式。
        assert_eq!(
            parse_helper_args(&args(&["edit_config_gui.exe", "--nonce=abc"])).unwrap(),
            None
        );
        assert_eq!(parse_helper_args(&args(&[])).unwrap(), None);
    }

    #[test]
    fn parse_helper_args_rejects_bad_target() {
        let err = parse_helper_args(&args(&["--elevated-restart=bogus", "--nonce=zz"]))
            .expect_err("非法目标必须报错");
        assert!(err.contains("bogus"), "错误里要能看出非法值：{err}");
    }

    #[test]
    fn parse_helper_args_rejects_missing_nonce() {
        let err = parse_helper_args(&args(&["--elevated-restart=server"]))
            .expect_err("缺 nonce 必须报错");
        assert!(err.contains("nonce"), "错误应提到 nonce：{err}");
    }

    #[test]
    fn parse_helper_args_rejects_non_hex_nonce() {
        // `../` 是路径穿越的典型输入：因为只允许十六进制，它连文件名都进不去。
        for bad in ["../", "zz", "a-b", "a b", "", &"a".repeat(65)] {
            let err = parse_helper_args(&args(&[
                "--elevated-restart=client",
                &format!("--nonce={bad}"),
            ]))
            .expect_err("非十六进制 / 超长 nonce 必须报错");
            assert!(!err.is_empty());
        }
    }

    #[test]
    fn result_path_is_under_temp_and_contains_nonce() {
        let path = result_path("deadbeef");
        assert_eq!(
            path.file_name().and_then(|n| n.to_str()),
            Some("edit_config_gui_elevated_deadbeef.txt")
        );
        assert_eq!(path.parent().map(Path::to_path_buf), Some(std::env::temp_dir()));
    }

    #[test]
    fn generate_nonce_is_filename_safe_and_hex() {
        let nonce = generate_nonce();
        assert!(nonce_is_valid(&nonce), "生成的 nonce 必须过校验：{nonce}");
    }

    #[test]
    fn nonce_for_result_sanitizes_unsafe_input() {
        let safe = nonce_for_result(&args(&["--nonce=../evil"]));
        assert!(safe.chars().all(|c| c.is_ascii_alphanumeric()), "{safe}");
        assert!(!safe.contains(".."), "{safe}");
    }
}
