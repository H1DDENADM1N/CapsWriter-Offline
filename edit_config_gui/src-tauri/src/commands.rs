//! IPC 命令层：把前端发来的补丁 / 校验规则落到磁盘，并把磁盘状态装配成前端可渲染的视图。
//!
//! 这一层只做「编排」：定位文件、读、预览、提交、重载、探测/重启服务进程。解析交给
//! `config_doc`，改值交给 `patch`，校验交给 `validate`，落盘交给 `file_io`；本模块不重复
//! 实现它们任何一条规则，预览与保存走的是**同一条** parse → apply → validate → serialize
//! 路径，保证「预览所见 = 保存所得」。
//!
//! 为什么状态是 `Mutex<Option<Session>>`：
//! - 前端可能并发 invoke（保存尚未返回时又点了重新加载，或双击保存），而 `ConfigDoc`
//!   是可就地修改的文档（`toml_edit`），两个补丁同时作用会互相覆盖、预览也可能读到改到
//!   一半的文档。命令之间必须串行化，所以需要一个真正的互斥锁，而不是每命令各拿一份。
//! - `Option` 表达「还没打开任何配置文件」这个**合法初始态**：首屏就可以 invoke 预览/
//!   重载，得到明确的「未打开配置文件」，而不是一个路径为空、字段为空的假会话。
//! - 用 `std::sync::Mutex` 而不是异步锁：临界区里全是同步文件读写（parse / patch /
//!   atomic_write），没有 `.await` 点。代价只是命令线程短暂等待，收益是「锁不可能在
//!   等待点被挂住」。因此本模块所有持有 `MutexGuard` 的函数都同步实现，命令里的 await
//!   一律发生在取锁之前（`pick_path` 甚至完全不碰会话状态）。
//!
//! 另外，`restart_service` 的 `base_dir` 只从会话取，绝不接受前端传路径：启动器会被
//! 以 SYSTEM/管理员身份拉起，前端若能把「基目录」指到任意位置，就等于把任意 exe 的
//! 启动权交给了渲染进程。

use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

use tauri::State;
use tauri_plugin_dialog::DialogExt;

use crate::{config_doc, elevate, file_io, patch, process, system_theme, validate};

/// 约定的配置文件名。定位、备份槽都以它为准。
const CONFIG_FILE: &str = "config.toml";
/// 前端把这条字符串当作可判别的冲突信号（而不是普通错误），所以值必须逐字稳定。
const CONFLICT: &str = "CONFLICT";
/// 未打开会话时所有依赖会话的命令返回同一条文案，前端可据此把用户导回「打开文件」一步。
const NO_SESSION: &str = "未打开配置文件";

/// 一次「打开」之后前端渲染所需的全部状态。
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocState {
    pub path: String,
    pub fingerprint: file_io::FileFingerprint,
    pub fields: Vec<FieldView>,
    pub base_dir: String,
}

/// 叶子字段的展示视图。`toml_type` 是字符串而不是 `TomlType` 本身：`TomlType` 没有实现
/// `Serialize`，且它的 wire 形态（"inlineTable" 这种 camelCase）由 `toml_type_name` 统一
/// 定义，避免两处各自序列化后出现不一致。
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FieldView {
    pub segments: Vec<String>,
    pub value: serde_json::Value,
    pub toml_type: String,
}

/// 预览结果：diff 给用户看，errors/warnings 给表单标红，changed 给前端定位脏字段。
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewResult {
    pub diff: String,
    pub errors: Vec<Problem>,
    pub warnings: Vec<Problem>,
    pub changed: Vec<Vec<String>>,
}

/// 校验问题（errors 与 warnings 共用）。`segments` 是数组而非点分字符串：`vlc.exe`
/// 这类键名里的点不能当分隔符。
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Problem {
    pub segments: Vec<String>,
    pub message: String,
}

/// 提交结果。`backup_path` 直接指向 `file_io::atomic_write` 生成的 `.bak`，前端可提供
/// 「打开备份所在目录」而无需自己拼路径。
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommitResult {
    pub fingerprint: file_io::FileFingerprint,
    pub backup_path: String,
}

/// 当前打开的文档及其磁盘基线。
pub struct Session {
    pub doc: config_doc::ConfigDoc,
    pub fingerprint: file_io::FileFingerprint,
    /// 服务进程的启动目录（配置文件所在目录）。只在这里固化，不接受前端输入。
    pub base_dir: PathBuf,
}

impl Session {
    /// 从磁盘建立会话。
    ///
    /// 顺序是「先指纹、后正文」，不是笔误：两次 IO 之间文件若被外部程序改掉，存下来的
    /// 指纹会偏旧，下一次保存会因指纹不一致报 `CONFLICT`（宁可多一次冲突提示）；反过来
    /// 先读正文再取指纹，就会把别人的修改当成基线，随后的保存会把它静默覆盖掉。
    fn load(path: &Path) -> Result<Self, String> {
        let fingerprint = file_io::fingerprint(path)
            .map_err(|e| format!("无法读取文件状态（{}）：{e}", path.display()))?;
        let doc = config_doc::ConfigDoc::load(path)
            .map_err(|e| format!("无法打开配置文件（{}）：{e}", path.display()))?;
        Ok(Self {
            base_dir: base_dir_of(path),
            doc,
            fingerprint,
        })
    }
}

/// 全局会话槽。见模块文档：为什么要锁、为什么是 Option。
pub struct AppState {
    pub session: Mutex<Option<Session>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            session: Mutex::new(None),
        }
    }
}

impl AppState {
    /// 打开（或替换）会话。
    ///
    /// 先把文件完整读成 `Session` 再上锁：load 失败时已有的会话必须原样保留，否则用户
    /// 在文件对话框里点错一个路径，就会把「尚未保存但正在编辑」的基线清掉。
    fn open_path(&self, path: &Path) -> Result<DocState, String> {
        let session = Session::load(path)?;
        let view = doc_state(&session);
        *lock_session(self)? = Some(session);
        Ok(view)
    }

    /// 从磁盘重新加载当前会话；加载失败时不改动旧会话（用户还能继续在旧基线上看 diff）。
    fn reload(&self) -> Result<DocState, String> {
        let mut guard = lock_session(self)?;
        let session = guard.as_mut().ok_or_else(|| NO_SESSION.to_string())?;
        let path = session.doc.path().to_path_buf();
        let fresh = Session::load(&path)?;
        *session = fresh;
        Ok(doc_state(session))
    }
}

/// 取会话锁；锁被 poison 说明持锁线程 panic 过，继续用可能拿到半改状态，直接让用户重启。
fn lock_session(state: &AppState) -> Result<MutexGuard<'_, Option<Session>>, String> {
    state
        .session
        .lock()
        .map_err(|_| "配置状态锁已损坏，请重启应用".to_string())
}

/// 配置文件所在目录；路径没有父目录（卷根等异常输入）时返回空路径，保留「未知」语义，
/// 而不是伪造一个 `.` 让人误以为基目录就是进程 cwd。
fn base_dir_of(path: &Path) -> PathBuf {
    path.parent().map(Path::to_path_buf).unwrap_or_default()
}

/// 装配前端视图。`leaf_fields()` 每次现算：文档可能在命令之间被替换（提交/重载），
/// 缓存字段列表只会带来失效问题，而 162 个叶子的成本远低于一次文件 IO。
fn doc_state(session: &Session) -> DocState {
    DocState {
        path: session.doc.path().to_string_lossy().into_owned(),
        fingerprint: session.fingerprint.clone(),
        fields: session
            .doc
            .leaf_fields()
            .into_iter()
            .map(|field| FieldView {
                segments: field.segments,
                value: field.value,
                toml_type: config_doc::toml_type_name(field.toml_type).to_string(),
            })
            .collect(),
        base_dir: session.base_dir.to_string_lossy().into_owned(),
    }
}

fn to_problems(items: &[validate::ValidationError]) -> Vec<Problem> {
    items
        .iter()
        .map(|e| Problem {
            segments: e.segments.clone(),
            message: e.message.clone(),
        })
        .collect()
}

/// 把多条校验错误拼成一行可直接展示的文本。`segments` 为空的规则没有字段可标注，
/// 只留文案，避免出现开头就是 `: ` 的怪串。
fn summarize_errors(errors: &[validate::ValidationError]) -> String {
    errors
        .iter()
        .map(|e| {
            if e.segments.is_empty() {
                e.message.clone()
            } else {
                format!("{}: {}", e.segments.join("."), e.message)
            }
        })
        .collect::<Vec<_>>()
        .join("；")
}

/// 定位配置文件：
/// ① 显式传入的路径（原样返回，哪怕不存在）
/// ② 可执行文件旁边的 `config.toml`
/// ③ 当前工作目录下的 `config.toml`
/// ④ 都不存在 → `NotFound`
///
/// ① 之所以不做 `exists()` 预检：调用方紧接着会真正 `load`，让「用户显式指定的这个路径
/// 为什么读不到」由真实错误来回答；预检会把「用户指定」和「自动探测」两种完全不同的
/// 情形压成同一个笼统错误，也让相对路径的解析结果白白丢掉。
///
/// 整个函数只做只读探测，绝不创建文件或目录：定位失败必须无副作用，否则在只读目录里
/// 点一次「打开」就会留下垃圾。
pub(crate) fn locate(
    cli: Option<&Path>,
    exe_dir: &Path,
    cwd: &Path,
) -> Result<PathBuf, file_io::IoError> {
    if let Some(path) = cli {
        return Ok(path.to_path_buf());
    }

    let beside_exe = exe_dir.join(CONFIG_FILE);
    if beside_exe.exists() {
        return Ok(beside_exe);
    }

    let in_cwd = cwd.join(CONFIG_FILE);
    if in_cwd.exists() {
        return Ok(in_cwd);
    }

    Err(file_io::IoError::NotFound(in_cwd))
}

/// 备份槽路径必须与 `file_io::atomic_write` 的约定逐字一致（文件名后直接加 `.bak`）：
/// 用 `with_extension` 会把 `config.toml` 变成 `config.bak`，前端拿到的就是一个不存在的
/// 路径。原子写的实现里同样是对完整文件名追加后缀。
pub(crate) fn backup_path_for(path: &Path) -> PathBuf {
    let mut name = path
        .file_name()
        .map(|n| n.to_os_string())
        .unwrap_or_else(|| CONFIG_FILE.into());
    name.push(".bak");
    path.with_file_name(name)
}

/// 预览：只在内存副本上演练，绝不写盘。
///
/// 为什么必须从 `original_text()` 重新 parse 一份副本，而不是直接改 `session.doc`：
/// 1) 预览要可重复、可丢弃。编辑过程中用户会反复点预览，基线必须始终是「磁盘原文」；
///    在会话文档上累积补丁会让 diff 越滚越大，还会把未保存改动带进下一次预览。
/// 2) `ConfigDoc::parse` 不碰文件系统，副本解析/应用失败时会话完全不受影响，预览天然
///    是只读、可失败的。
/// 3) 保存走的是同一套 parse → apply → validate → to_toml_string，所以预览看到的 diff
///    与错误就是保存时会发生的，不存在「预览一套、保存另一套」。
fn preview_with(
    state: &AppState,
    patches: &[patch::Patch],
    rules: &[validate::FieldRule],
) -> Result<PreviewResult, String> {
    let guard = lock_session(state)?;
    let session = guard.as_ref().ok_or_else(|| NO_SESSION.to_string())?;

    let original = session.doc.original_text();
    let mut copy = config_doc::ConfigDoc::parse(original)
        .map_err(|e| format!("解析当前配置失败，预览已中止：{e}"))?;
    let changed = patch::apply(&mut copy, patches)
        .map_err(|e| format!("应用修改失败，预览已中止：{e}"))?;
    let report = validate::validate_all(&copy, rules);
    let after = copy.to_toml_string();

    Ok(PreviewResult {
        diff: patch::unified_diff(original, &after),
        errors: to_problems(&report.errors),
        warnings: to_problems(&report.warnings),
        changed,
    })
}

/// 提交：三道闸依次通过才落盘。
/// 1) 指纹闸（`force == false` 时）：前端拿到的基线 sha256 必须与磁盘当前内容一致，
///    否则说明有别的程序（或另一个编辑器窗口）改过文件，直接 `CONFLICT` 让用户重载，
///    绝不基于过期基线上写，避免丢更新。
/// 2) 校验闸：`errors` 非空一律拒绝，且必须发生在 `atomic_write` 之前（写后回滚虽然
///    有 .bak，但会让用户看到「保存失败但其实文件变过一次」的混乱）；warnings 只提示。
/// 3) 原子写闸：交给 `file_io::atomic_write`（.tmp → fsync → ReplaceFileW + .bak →
///    回读解析），它保证失败时目标文件保持原样。
///
/// 写成功后用磁盘上的新内容重建会话（doc 重新 load、fingerprint 用 atomic_write 的
/// 返回值、base_dir 不变），否则下一次预览会拿旧基线算 diff，把刚保存的改动又算一遍。
fn commit_with(
    state: &AppState,
    patches: &[patch::Patch],
    rules: &[validate::FieldRule],
    expected: &file_io::FileFingerprint,
    force: bool,
) -> Result<CommitResult, String> {
    let mut guard = lock_session(state)?;
    let session = guard.as_mut().ok_or_else(|| NO_SESSION.to_string())?;
    let path = session.doc.path().to_path_buf();

    if !force {
        let current = file_io::fingerprint(&path)
            .map_err(|e| format!("无法确认磁盘上的文件状态，已取消保存：{e}"))?;
        if current.sha256 != expected.sha256 {
            return Err(CONFLICT.to_string());
        }
    }

    let original = session.doc.original_text();
    let mut copy = config_doc::ConfigDoc::parse(original)
        .map_err(|e| format!("解析当前配置失败，未写入任何内容：{e}"))?;
    patch::apply(&mut copy, patches)
        .map_err(|e| format!("应用修改失败，未写入任何内容：{e}"))?;
    let report = validate::validate_all(&copy, rules);
    if !report.errors.is_empty() {
        // 校验失败时一次都不调用 atomic_write：不产生 .tmp/.bak，磁盘一个字节都不动。
        return Err(format!("校验未通过：{}", summarize_errors(&report.errors)));
    }

    let after = copy.to_toml_string();
    let written =
        file_io::atomic_write(&path, &after).map_err(|e| format!("保存配置文件失败：{e}"))?;
    let reloaded = config_doc::ConfigDoc::load(&path)
        .map_err(|e| format!("保存后重新读取配置失败：{e}"))?;

    session.doc = reloaded;
    session.fingerprint = written.clone();
    // base_dir 不重算：它只取决于文件位置，位置没变。保留它是为了让“重启服务”始终
    // 指向同一个目录，即使将来配置文件名/位置有变，也不会因为这里重新推导而漂移。

    Ok(CommitResult {
        fingerprint: written,
        backup_path: backup_path_for(&path).to_string_lossy().into_owned(),
    })
}

/// 打开配置文件：`path` 为 Some 时用显式路径，否则按 `locate` 的四级优先级自动探测。
#[tauri::command]
pub async fn open_config(
    state: State<'_, AppState>,
    path: Option<String>,
) -> Result<DocState, String> {
    let cwd = std::env::current_dir()
        .map_err(|e| format!("无法获取当前工作目录：{e}"))?;
    // exe 目录优先于 cwd：安装版把 config.toml 放在 exe 旁边，从任意快捷方式启动都应
    // 命中它；current_exe 失败属于极端情形，退回 cwd 让自动探测至少还能工作。
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| cwd.clone());

    let cli = path.as_deref().map(Path::new);
    let target = locate(cli, &exe_dir, &cwd).map_err(|e| e.to_string())?;
    state.inner().open_path(&target)
}

/// 文件/目录选择框。`mode == "dir"` 选目录，其余一律按文件处理（前端目前只会传这两个值，
/// 但默认分支选文件比默认选目录更保守：选错文件最多打开失败，选错目录会被当成配置文件）。
///
/// 用 `blocking_*` 版本是安全的：Tauri 的异步命令跑在异步运行时线程上，不在主线程；
/// 插件文档明确说明 blocking 版本只能用于非主线程，否则会和事件循环互锁。这个命令
/// 不碰会话状态，所以也不需要会话锁。
#[tauri::command]
pub async fn pick_path(
    app: tauri::AppHandle,
    mode: String,
    title: String,
) -> Result<Option<String>, String> {
    let dialog = app.dialog().file().set_title(title);
    let picked = if mode == "dir" {
        dialog.blocking_pick_folder()
    } else {
        dialog.blocking_pick_file()
    };

    let Some(file) = picked else {
        // 用户取消是正常路径，不是错误：返回 None 让前端保持原选择。
        return Ok(None);
    };
    let path = file
        .into_path()
        .map_err(|e| format!("无法解析所选路径：{e}"))?;
    Ok(Some(path.to_string_lossy().into_owned()))
}

/// 预览保存：不写盘，返回 diff / 校验结果 / 受影响字段。
#[tauri::command]
pub async fn preview_save(
    state: State<'_, AppState>,
    patches: Vec<patch::Patch>,
    rules: Vec<validate::FieldRule>,
) -> Result<PreviewResult, String> {
    preview_with(state.inner(), &patches, &rules)
}

/// 提交保存：三道闸（指纹 / 校验 / 原子写）全部通过才落盘。
#[tauri::command]
pub async fn commit_save(
    state: State<'_, AppState>,
    patches: Vec<patch::Patch>,
    rules: Vec<validate::FieldRule>,
    fingerprint: file_io::FileFingerprint,
    force: bool,
) -> Result<CommitResult, String> {
    commit_with(state.inner(), &patches, &rules, &fingerprint, force)
}

/// 重新从磁盘加载：用户在外部改过文件后，用它把基线刷新到最新。
#[tauri::command]
pub async fn reload_config(state: State<'_, AppState>) -> Result<DocState, String> {
    state.inner().reload()
}

/// 探测服务/客户端进程是否在跑（以及是否管理员、客户端是否 admin 变体）。
#[tauri::command]
pub async fn running_processes() -> Result<process::RunningInfo, String> {
    Ok(process::detect())
}

/// 重启服务或客户端。
///
/// 安全边界：`base_dir` 只从会话取。启动器会以（可能提升的）权限被执行，如果允许前端
/// 传目录，渲染进程被攻破时就等于拿到了「在任意目录启动白名单 exe」的能力；这里改成
/// 「只信任用户亲手打开的那个配置文件所在目录」。
///
/// `variant` 取 `detect()` 的结果原样传递，让重启后的客户端保持原来的普通/admin 形态；
/// `degraded == true` 也必须原样返回——它表示「提权失败、已降级为普通启动」，前端要据此
/// 提示用户，绝不能在这里吞成成功。
///
/// 预检在这里、也在 `process::restart` 里各做一次：目标以管理员权限运行时，本函数**在
/// kill 之前**就返回 `needsElevation`，一个进程都不结束。安全网覆盖「预检为假、真正 kill
/// 时才被拒绝访问」的竞态（例如目标进程恰在两次扫描之间被提权重启）。
#[tauri::command]
pub async fn restart_service(
    state: State<'_, AppState>,
    target: process::ServiceTarget,
) -> Result<process::RestartOutcome, String> {
    let base_dir = {
        let guard = lock_session(state.inner())?;
        let session = guard.as_ref().ok_or_else(|| NO_SESSION.to_string())?;
        session.base_dir.clone()
    }; // 锁在这里就释放：restart 会结束/拉起进程，可能耗时数秒，不该让预览/重载干等。

    if process::needs_elevation(target) {
        return Ok(process::RestartOutcome {
            degraded: false,
            needs_elevation: true,
        });
    }

    let variant = process::detect().client_variant;
    match process::restart(target, &base_dir, variant.as_deref()) {
        Ok(outcome) => Ok(outcome),
        Err(process::ProcError::AccessDenied(_)) => Ok(process::RestartOutcome {
            degraded: false,
            needs_elevation: true,
        }),
        Err(e) => Err(e.to_string()),
    }
}

/// 提权重启：前端在收到 `needsElevation == true` 后，用户点「以管理员身份重启」时调用。
///
/// 安全边界与 [`restart_service`] 相同：`base_dir` 只从会话取，绝不接受前端传路径。
/// 本函数自身不做任何结束/启动，只是以 `runas` 拉起同一个 exe 的助手模式，由助手在提权
/// 上下文里完成「结束 + 拉起」。用户取消 UAC 时返回明确文案且磁盘/进程零改动。
#[tauri::command]
pub async fn restart_service_elevated(
    state: State<'_, AppState>,
    target: process::ServiceTarget,
) -> Result<process::RestartOutcome, String> {
    let base_dir = {
        let guard = lock_session(state.inner())?;
        let session = guard.as_ref().ok_or_else(|| NO_SESSION.to_string())?;
        session.base_dir.clone()
    }; // 同样先放锁：UAC 弹窗期间的等待不该占住会话，让预览/重载还能用。

    elevate::spawn_elevated_helper(target, &base_dir)
}

/// 「关于」页打开项目主页用。
///
/// 安全边界：只放行 `https://`。这个命令把字符串交给系统协议处理器，如果允许任意
/// scheme，`file://` 能打开本地文件、`ms-settings:`/各类应用自定义协议能拉起别的程序
/// ——渲染进程一旦被注入，这就是一条现成的命令执行链。关于页只需要打开几个 GitHub
/// 链接，没有别的需求，所以这里按最窄的形状实现。
pub fn check_url(url: &str) -> Result<&str, String> {
    let trimmed = url.trim();
    if trimmed.is_empty() {
        return Err("链接为空".to_string());
    }
    if !trimmed.starts_with("https://") {
        return Err("只支持以 https:// 开头的链接".to_string());
    }
    if trimmed.len() > 2048 {
        return Err("链接过长".to_string());
    }
    if trimmed.chars().any(|c| c.is_control() || c == '"' || c == ' ') {
        return Err("链接含有非法字符".to_string());
    }
    Ok(trimmed)
}

#[cfg(windows)]
fn shell_open(url: &str) -> Result<(), String> {
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let verb: Vec<u16> = "open\0".encode_utf16().collect();
    let file: Vec<u16> = url.encode_utf16().chain(std::iter::once(0)).collect();

    // SAFETY: 两个指针都指向以 NUL 结尾的 UTF-16 缓冲，且在调用期间存活；
    // 其余参数为 null，表示不传参数、继承当前工作目录。
    let ret = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            file.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL as i32,
        )
    };

    // ShellExecuteW 的返回值约定：> 32 表示成功，<= 32 是错误码（不是 GetLastError）。
    if ret as isize <= 32 {
        return Err(format!("系统未能打开链接（ShellExecuteW 返回 {}）", ret as isize));
    }
    Ok(())
}

#[cfg(not(windows))]
fn shell_open(_url: &str) -> Result<(), String> {
    Err("当前平台不支持打开链接".to_string())
}

#[tauri::command]
pub fn open_url(url: String) -> Result<(), String> {
    let url = check_url(&url)?;
    shell_open(url)
}

/// 系统外观：深色还是浅色、主题色种子候选。
///
/// 同步命令：只读两个注册表值（微秒级），不值得为它开异步任务；也不碰会话状态，
/// 因此不需要会话锁。前端拿它生成 MD3 配色令牌，用户在 Windows 设置里改主题后
/// 前端轮询本命令即可跟上，不需要额外的「主题变更」事件通道。
#[tauri::command]
pub fn system_appearance() -> Result<system_theme::SystemAppearance, String> {
    Ok(system_theme::appearance())
}

/// 页面缩放。
///
/// 用 webview 自己的缩放而不是 CSS `zoom`：只有前者会连 `vw`/`vh`、媒体查询和
/// 固定定位一起重算，观感才和浏览器里按 Ctrl+滚轮一致。档位（50%–200%）由前端
/// 算好再传进来，这里只做范围兜底——WebView2 收到 0 或负数会直接把整页缩没。
#[tauri::command]
pub fn set_zoom(window: tauri::WebviewWindow, scale: f64) -> Result<(), String> {
    check_zoom_range(scale)?;
    window
        .set_zoom(scale)
        .map_err(|e| format!("设置缩放失败：{e}"))
}

/// 合法缩放区间。单独提出来的原因只有一个：不依赖窗口就能测。
pub fn check_zoom_range(scale: f64) -> Result<(), String> {
    if (0.25..=5.0).contains(&scale) {
        Ok(())
    } else {
        Err(format!("缩放比例超出范围：{scale}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config_doc::{toml_type_name, TomlType};
    use crate::file_io;
    use crate::patch::PatchValue;
    use crate::testutil::{patch as mk_patch, seg, seed, tmpdir};

    /// 真实的默认配置模板；cargo test 的 cwd 是 `edit_config_gui/src-tauri`。
    const TEMPLATE: &str = "../../configs/default config.toml";

    #[test]
    fn config_location_precedence() {
        let base = tmpdir();
        let exe_dir = base.join("app");
        let cwd = base.join("cwd");
        std::fs::create_dir_all(&exe_dir).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();
        let exe_cfg = exe_dir.join("config.toml");
        let cwd_cfg = cwd.join("config.toml");
        std::fs::write(&exe_cfg, "a = 1\n").unwrap();
        std::fs::write(&cwd_cfg, "a = 2\n").unwrap();

        // ① 显式路径始终优先；即使文件不存在也原样返回，把真实读取错误留给 load
        let explicit = base.join("explicit.toml");
        assert_eq!(
            locate(Some(&explicit), &exe_dir, &cwd).unwrap(),
            explicit,
            "显式路径必须原样返回"
        );
        assert!(!explicit.exists(), "显式路径这个文件本就不存在");

        // ② exe 旁边存在时优先于 cwd
        assert_eq!(
            locate(None, &exe_dir, &cwd).unwrap(),
            exe_cfg,
            "exe 目录应优先于 cwd"
        );

        // ③ exe 旁边没有 → 退到 cwd
        std::fs::remove_file(&exe_cfg).unwrap();
        assert_eq!(
            locate(None, &exe_dir, &cwd).unwrap(),
            cwd_cfg,
            "exe 目录缺失时应退到 cwd"
        );

        // ④ 都没有 → NotFound，而且探测过程不得创建任何目录或文件
        std::fs::remove_file(&cwd_cfg).unwrap();
        let empty_exe = base.join("empty_exe");
        let empty_cwd = base.join("empty_cwd");
        match locate(None, &empty_exe, &empty_cwd) {
            Err(file_io::IoError::NotFound(p)) => {
                assert_eq!(p, empty_cwd.join("config.toml"), "NotFound 应报告最后尝试的路径")
            }
            Err(other) => panic!("应当返回 NotFound，实际：{other}"),
            Ok(found) => panic!("应当返回 NotFound，实际定位到：{}", found.display()),
        }
        assert!(!empty_exe.exists(), "定位失败不得创建 exe 目录");
        assert!(!empty_cwd.exists(), "定位失败不得创建 cwd 目录");
    }

    #[test]
    fn toml_type_is_camel_string() {
        // 这六个字面量是前端 `FieldMeta.tomlType` 的判别依据，改一个字界面就会静默不渲染。
        assert_eq!(toml_type_name(TomlType::String), "string");
        assert_eq!(toml_type_name(TomlType::Integer), "integer");
        assert_eq!(toml_type_name(TomlType::Float), "float");
        assert_eq!(toml_type_name(TomlType::Boolean), "boolean");
        assert_eq!(toml_type_name(TomlType::Array), "array");
        assert_eq!(toml_type_name(TomlType::InlineTable), "inlineTable");
    }

    #[test]
    fn doc_state_fields_reflect_document() {
        let app = AppState::default();
        let view = app
            .open_path(Path::new(TEMPLATE))
            .expect("默认模板必须能打开");

        assert_eq!(view.fields.len(), 162, "模板叶子数必须与文档约定一致");
        assert_eq!(Path::new(&view.base_dir), Path::new("../../configs"));
        assert!(
            view.path.ends_with("default config.toml"),
            "DocState.path 应是打开的模板路径：{}",
            view.path
        );

        let port = view
            .fields
            .iter()
            .find(|f| f.segments == seg(&["server", "offline_translate_port"]))
            .expect("模板必须包含 server.offline_translate_port");
        assert_eq!(port.toml_type, "string", "该端口在模板里是字符串而非整数");
        assert_eq!(port.value, serde_json::Value::String("6017".into()));
    }

    #[test]
    fn preview_does_not_write() {
        let dir = tmpdir();
        let path = seed(&dir);
        let before = std::fs::read(&path).unwrap();

        let app = AppState::default();
        app.open_path(&path).expect("打开种子配置");
        let preview = preview_with(&app, &[mk_patch(&["a"], PatchValue::Int(2))], &[])
            .expect("合法补丁应能预览");

        assert!(!preview.diff.is_empty(), "有改动时 diff 不能为空");
        assert!(
            preview.diff.contains("a = 2"),
            "diff 应展示新值：{}",
            preview.diff
        );
        assert_eq!(preview.changed, vec![seg(&["a"])]);
        assert!(preview.errors.is_empty(), "合法值不应产生 error");

        assert_eq!(std::fs::read(&path).unwrap(), before, "预览绝不能写盘");
        assert!(!dir.join("config.toml.bak").exists(), "预览不得生成备份");
        assert!(!dir.join("config.toml.tmp").exists(), "预览不得留下临时文件");
    }

    #[test]
    fn preview_rejects_when_no_session() {
        let app = AppState::default();
        let err = preview_with(&app, &[], &[]).expect_err("没有会话时预览必须失败");
        assert_eq!(err, NO_SESSION);
    }

    #[test]
    fn issue_with_validation_error_is_rejected() {
        let dir = tmpdir();
        let path = dir.join("config.toml");
        std::fs::write(&path, "[server]\n\noffline_translate_port = \"6017\"\n").unwrap();
        let before = std::fs::read(&path).unwrap();

        let app = AppState::default();
        let opened = app.open_path(&path).expect("打开端口配置");
        let rules = vec![validate::FieldRule {
            segments: seg(&["server", "offline_translate_port"]),
            validators: vec![validate::ValidatorId::Port],
            allow_empty: false,
            file_suffix: None,
            warn_only: false,
        }];
        let patches = vec![mk_patch(
            &["server", "offline_translate_port"],
            PatchValue::Str("80".into()),
        )];

        let err = commit_with(&app, &patches, &rules, &opened.fingerprint, false)
            .expect_err("非法端口必须拒绝保存");
        assert!(
            err.starts_with("校验未通过："),
            "错误应带统一前缀，前端才好分支：{err}"
        );
        assert!(
            err.contains("server.offline_translate_port"),
            "错误必须指出是哪个字段：{err}"
        );
        assert!(err.contains("1023"), "错误必须带原始校验文案：{err}");

        assert_eq!(std::fs::read(&path).unwrap(), before, "校验失败时磁盘不得变化");
        assert!(
            !dir.join("config.toml.bak").exists(),
            "校验失败不得生成备份"
        );
        assert!(
            !dir.join("config.toml.tmp").exists(),
            "校验失败说明 atomic_write 根本没被调用"
        );
    }

    #[test]
    fn backup_path_points_at_config_toml_bak() {
        // 备份槽必须与 file_io::atomic_write 的命名一致（完整文件名 + .bak），
        // 用 with_extension 会拼出 config.bak 这个不存在的路径。
        let target = Path::new(
            r"C:\Users\user0\Documents\CapsWriter-Offline\config.toml",
        );
        assert_eq!(
            backup_path_for(target),
            PathBuf::from(
                r"C:\Users\user0\Documents\CapsWriter-Offline\config.toml.bak"
            )
        );
        assert_eq!(
            backup_path_for(Path::new("config.toml")),
            PathBuf::from("config.toml.bak")
        );
    }

    #[test]
    fn commit_conflicts_when_disk_changed() {
        let dir = tmpdir();
        let path = seed(&dir);
        let before = std::fs::read(&path).unwrap();

        let app = AppState::default();
        let opened = app.open_path(&path).expect("打开种子配置");
        let mut stale = opened.fingerprint.clone();
        stale.sha256 = "0".repeat(64); // 模拟前端拿到的是过期基线（内容已被外部改过）

        let err = commit_with(&app, &[mk_patch(&["a"], PatchValue::Int(2))], &[], &stale, false)
            .expect_err("指纹不一致必须拒绝保存");
        assert_eq!(err, CONFLICT, "冲突必须是可判别的字面量");
        assert_eq!(std::fs::read(&path).unwrap(), before, "冲突时不得写盘");
        assert!(!dir.join("config.toml.bak").exists(), "冲突时不得生成备份");
    }

    #[test]
    fn commit_writes_backup_and_refreshes_session() {
        let dir = tmpdir();
        let path = seed(&dir);
        let original = std::fs::read(&path).unwrap();

        let app = AppState::default();
        let opened = app.open_path(&path).expect("打开种子配置");
        let result = commit_with(
            &app,
            &[mk_patch(&["a"], PatchValue::Int(2))],
            &[],
            &opened.fingerprint,
            false,
        )
        .expect("合法补丁应保存成功");

        let after = std::fs::read_to_string(&path).unwrap();
        assert!(after.contains("a = 2"), "磁盘内容应更新：{after}");
        assert!(after.contains("# 注释"), "注释不得丢失：{after}");
        assert!(after.contains("b = \"x\""), "未改动字段必须保留：{after}");

        let bak = dir.join("config.toml.bak");
        assert_eq!(
            Path::new(&result.backup_path),
            bak,
            "CommitResult.backup_path 必须指向同目录的 config.toml.bak"
        );
        assert_eq!(
            std::fs::read(&bak).unwrap(),
            original,
            ".bak 必须是保存前的内容"
        );

        let disk = file_io::fingerprint(&path).expect("读取写后指纹");
        assert_eq!(
            result.fingerprint.sha256, disk.sha256,
            "返回值指纹必须对应写后的文件"
        );

        // 会话必须换成写后的文档，否则下一次预览会以旧基线算 diff。
        let view = {
            let guard = app.session.lock().unwrap();
            doc_state(guard.as_ref().expect("提交成功后会话必须存在"))
        };
        let a = view
            .fields
            .iter()
            .find(|f| f.segments == seg(&["a"]))
            .expect("保存后仍应有字段 a");
        assert_eq!(a.value, serde_json::json!(2));
        assert_eq!(view.fingerprint.sha256, disk.sha256);
    }

    #[test]
    fn check_url_rejects_non_https_schemes() {
        // 这几条是真实风险：file:// 能读本地文件，自定义协议能拉起任意已注册程序。
        for bad in [
            "http://github.com/H1DDENADM1N/CapsWriter-Offline",
            "file:///C:/Windows/System32/cmd.exe",
            "ms-settings:privacy",
            "javascript:alert(1)",
            "https:/github.com",
            "",
            "   ",
        ] {
            assert!(check_url(bad).is_err(), "必须拒绝：{bad}");
        }
    }

    #[test]
    fn check_url_rejects_control_chars_and_spaces() {
        assert!(check_url("https://example.com/a b").is_err());
        assert!(check_url("https://example.com/a\nb").is_err());
        assert!(check_url("https://example.com/a\tb").is_err());
        assert!(check_url(&format!("https://example.com/{}", "a".repeat(2048))).is_err());
    }

    #[test]
    fn check_url_accepts_project_links_and_trims() {
        let url = "https://github.com/H1DDENADM1N/CapsWriter-Offline";
        assert_eq!(check_url(url).unwrap(), url);
        // 从别处复制来的链接常带首尾空白
        assert_eq!(check_url("  https://example.com/x  ").unwrap(), "https://example.com/x");
        assert!(check_url("https://github.com/H1DDENADM1N/CapsWriter-Offline/issues").is_ok());
    }

    #[test]
    fn check_zoom_range_accepts_the_frontend_steps() {
        // 前端档位表的两端与 100%
        for ok in [0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0] {
            assert!(check_zoom_range(ok).is_ok(), "应当接受：{ok}");
        }
    }

    #[test]
    fn check_zoom_range_rejects_zero_negative_and_absurd() {
        // 0 / 负数会让 WebView2 把整页缩没，NaN 则根本不构成比例
        for bad in [0.0, -1.0, 0.1, 5.1, f64::NAN, f64::INFINITY] {
            assert!(check_zoom_range(bad).is_err(), "必须拒绝：{bad}");
        }
        assert!(check_zoom_range(0.25).is_ok());
        assert!(check_zoom_range(5.0).is_ok());
    }
}
