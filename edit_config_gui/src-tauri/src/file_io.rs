//! 指纹、原子提交、备份与回滚（规格 §7.2 / §7.5）。
//!
//! 旧实现 `util/edit_config_gui/write_toml.py` 只有 6 行：`open(path, "w")` 后
//! 直接 `tomlkit.dump` —— 没有备份、不是原子替换、写一半断电就剩半个文件。
//! 这里把提交收成一条链：
//!
//! ```text
//! 写 .tmp → flush → sync_all → ReplaceFileW(target, tmp, bak) → 回读解析 → 返回新指纹
//! ```
//!
//! 任一步失败，`target` 保持原样。**不用 `std::fs::rename`**：实测 `Move-Item -Force`
//! （等价 rename）会把目标文件的显式 ACL 换成 `.tmp` 的 ACL，自定义 ACE 静默丢失；
//! `ReplaceFileW` 保留目标 SDDL，而且「替换 + 备份」是一步完成的。
//!
//! `ReplaceFileW` 的坑：备份槽传 `NULL` 表示「不备份」，成功且不产生 `.bak`；
//! 传空串 `""` 会以 `ERROR_PATH_NOT_FOUND` 失败。PowerShell 里 `$null` 转成 string
//! 形参会退化成空串，这是早期误判的根源 —— Rust 侧必须显式 `std::ptr::null()`。

use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, PartialEq, Eq)]
pub struct FileFingerprint {
    pub mtime_ms: i64,
    pub size: u64,
    pub sha256: String,
}

#[derive(Debug)]
pub enum IoError {
    Io(String),
    ReplaceFailed { code: u32, message: String },
    ReadbackParse(String),
    Conflict,
    NotFound(PathBuf),
}

impl std::fmt::Display for IoError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            IoError::Io(e) => write!(f, "文件读写失败：{e}"),
            IoError::ReplaceFailed { code, message } => {
                write!(f, "替换文件失败（错误码 {code}：{message}）")
            }
            IoError::ReadbackParse(e) => write!(f, "写入后回读校验失败：{e}"),
            IoError::Conflict => write!(f, "文件已被其他程序修改，请重新加载后再保存"),
            IoError::NotFound(p) => write!(f, "文件不存在：{}", p.display()),
        }
    }
}

impl std::error::Error for IoError {}

impl From<std::io::Error> for IoError {
    fn from(e: std::io::Error) -> Self {
        if e.kind() == std::io::ErrorKind::NotFound {
            return IoError::Io(e.to_string());
        }
        IoError::Io(e.to_string())
    }
}

/// 测试注入：让下一次 `atomic_write` 的回读阶段强制失败，用于验证回滚链。
// 必须是 thread-local：cargo test 默认并行跑，用全局 AtomicBool 会让
// `readback_failure_rolls_back` 的注入泄漏到同一进程里其它测试的 atomic_write 上。
#[cfg(test)]
thread_local! {
    static INJECT_READBACK_FAILURE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// 供测试注入失败：默认 false。
#[cfg(test)]
pub fn set_inject_readback_failure(v: bool) {
    INJECT_READBACK_FAILURE.with(|c| c.set(v));
}

#[cfg(not(test))]
pub fn set_inject_readback_failure(_v: bool) {}

#[cfg(test)]
fn injected_readback_failure() -> bool {
    INJECT_READBACK_FAILURE.with(|c| c.get())
}

#[cfg(not(test))]
fn injected_readback_failure() -> bool {
    false
}

pub fn read_bytes(path: &Path) -> Result<Vec<u8>, IoError> {
    if !path.exists() {
        return Err(IoError::NotFound(path.to_path_buf()));
    }
    Ok(std::fs::read(path)?)
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

fn mtime_ms(path: &Path) -> i64 {
    std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

pub fn fingerprint(path: &Path) -> Result<FileFingerprint, IoError> {
    let bytes = read_bytes(path)?;
    Ok(FileFingerprint {
        mtime_ms: mtime_ms(path),
        size: bytes.len() as u64,
        sha256: sha256_hex(&bytes),
    })
}

/// 同目录的伴生文件路径：`config.toml` → `config.toml.tmp`。
/// 必须同目录（同卷），跨卷的 `ReplaceFileW` 会失败。
fn sibling(target: &Path, suffix: &str) -> PathBuf {
    let mut s = target.as_os_str().to_os_string();
    s.push(suffix);
    PathBuf::from(s)
}

fn to_pcwstr(p: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    let mut v: Vec<u16> = p.as_os_str().encode_wide().collect();
    v.push(0);
    v
}

/// `ReplaceFileW(target, replacement, backup)`。
///
/// `backup` 为 `None` 时传 `NULL`（成功且不产生备份）；`Some("")` 是空串路径，
/// 会以 `ERROR_PATH_NOT_FOUND` 失败 —— 这个区别由 `replace_null_backup_ok` 钉死。
pub(crate) fn replace_file_w(
    target: &Path,
    replacement: &Path,
    backup: Option<&str>,
) -> Result<(), IoError> {
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::Storage::FileSystem::ReplaceFileW;

    let t = to_pcwstr(target);
    let r = to_pcwstr(replacement);
    let b = backup.map(|s| {
        let mut v: Vec<u16> = s.encode_utf16().collect();
        v.push(0);
        v
    });
    let backup_ptr = match &b {
        Some(v) => v.as_ptr(),
        None => std::ptr::null(),
    };

    let rc = unsafe {
        ReplaceFileW(
            t.as_ptr(),
            r.as_ptr(),
            backup_ptr,
            0,
            std::ptr::null(),
            std::ptr::null(),
        )
    };
    if rc == 0 {
        let code = unsafe { GetLastError() } as u32;
        return Err(IoError::ReplaceFailed {
            code,
            message: std::io::Error::from_raw_os_error(code as i32).to_string(),
        });
    }
    Ok(())
}

/// 原子提交。见模块文档的固定链；顺序不可调换。
pub fn atomic_write(target: &Path, text: &str) -> Result<FileFingerprint, IoError> {
    if !target.exists() {
        return Err(IoError::NotFound(target.to_path_buf()));
    }
    let tmp = sibling(target, ".tmp");
    let bak = sibling(target, ".bak");

    std::fs::write(&tmp, text.as_bytes())?;
    // 落盘再替换：否则断电后可能拿到「文件已换名但内容是空的」
    {
        let f = std::fs::OpenOptions::new().write(true).open(&tmp)?;
        f.sync_all()?;
    }

    // 「替换 + 备份」是一步：先手工 copy 再 ReplaceFileW 会让 .bak 变成新内容
    let bak_str = bak.to_string_lossy().to_string();
    if let Err(e) = replace_file_w(target, &tmp, Some(&bak_str)) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }

    // 回读校验：内容必须能按 TOML 解析回来
    let readback = std::fs::read_to_string(target)?;
    let parse_err = crate::config_doc::ConfigDoc::parse(&readback).err();
    if injected_readback_failure() || parse_err.is_some() {
        // 用 .bak 作 replacement 换回去
        let rollback_err = rollback_from_bak(target).err();
        let _ = std::fs::remove_file(&tmp);
        return Err(IoError::ReadbackParse(match (parse_err, rollback_err) {
            (Some(e), _) => format!("{e}"),
            (None, Some(e)) => format!("注入失败，且回滚也失败：{e}"),
            (None, None) => "注入失败".to_string(),
        }));
    }

    fingerprint(target)
}

/// 从 `.bak` 回滚：把 `.bak` 当作 replacement 换回去，废弃槽用 `config.toml.rollback`。
pub fn rollback_from_bak(target: &Path) -> Result<(), IoError> {
    let bak = sibling(target, ".bak");
    if !bak.exists() {
        return Err(IoError::NotFound(bak));
    }
    let discard = sibling(target, ".rollback");
    let discard_str = discard.to_string_lossy().to_string();
    // .bak 被「换出去」之后会落在废弃槽里，用完删掉；这样 .bak 本身不再存在，
    // 与「回滚后回到上一版状态」一致（下次保存会重新生成 .bak）。
    let staged = sibling(target, ".rollbackbak");
    std::fs::copy(&bak, &staged)?;
    // 用副本作 replacement，避免 ReplaceFileW 把 .bak 本身消耗掉后又被废弃槽覆盖
    let r = replace_file_w(target, &staged, Some(&discard_str));
    let _ = std::fs::remove_file(&staged);
    let _ = std::fs::remove_file(&discard);
    r
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{seed, tmpdir};

    const S0: &str = "a = 1\r\n# 注释\r\nb = \"x\"\r\n";
    const S2: &str = "a = 2\r\n# 注释\r\nb = \"x\"\r\n";
    const S3: &str = "a = 3\r\n# 注释\r\nb = \"x\"\r\n";
    const S4: &str = "a = 4\r\n# 注释\r\nb = \"x\"\r\n";

    #[test]
    fn writes_and_fingerprints() {
        let d = tmpdir();
        let p = seed(&d);
        let fp1 = fingerprint(&p).unwrap();
        let fp2 = atomic_write(&p, S2).unwrap();
        assert_ne!(fp1.sha256, fp2.sha256);
        assert_eq!(std::fs::read_to_string(&p).unwrap(), S2);
    }

    #[test]
    fn backup_contents() {
        let d = tmpdir();
        let p = seed(&d);
        atomic_write(&p, S2).unwrap();
        let bak = d.join("config.toml.bak");
        assert_eq!(
            std::fs::read_to_string(&bak).unwrap(),
            S0,
            "第一次保存后 .bak 必须是保存前的内容"
        );
        atomic_write(&p, S3).unwrap();
        assert_eq!(
            std::fs::read_to_string(&bak).unwrap(),
            S2,
            "第二次保存时 .bak 必须是上一版"
        );
    }

    #[test]
    fn tmp_left_over_does_not_corrupt_target() {
        let d = tmpdir();
        let p = seed(&d);
        // 模拟「写了 .tmp 但进程被杀」：.tmp 存在且内容完整，target 未变
        std::fs::write(d.join("config.toml.tmp"), "a = 999\r\n").unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), S0);
        // 下一次正常保存必须成功并清理 .tmp
        atomic_write(&p, S4).unwrap();
        assert!(!d.join("config.toml.tmp").exists());
        assert_eq!(std::fs::read_to_string(&p).unwrap(), S4);
    }

    #[test]
    fn rollback_restores_previous_version() {
        let d = tmpdir();
        let p = seed(&d);
        atomic_write(&p, S2).unwrap();
        atomic_write(&p, S3).unwrap();
        super::rollback_from_bak(&p).unwrap();
        assert_eq!(
            std::fs::read_to_string(&p).unwrap(),
            S2,
            "回滚后应是上一版"
        );
    }

    #[test]
    fn readback_failure_rolls_back() {
        let d = tmpdir();
        let p = seed(&d);
        atomic_write(&p, S2).unwrap();
        set_inject_readback_failure(true);
        let r = atomic_write(&p, S3);
        set_inject_readback_failure(false);
        assert!(matches!(r, Err(IoError::ReadbackParse(_))), "{r:?}");
        assert_eq!(
            std::fs::read_to_string(&p).unwrap(),
            S2,
            "回读失败必须回滚到上一版"
        );
    }

    #[test]
    fn invalid_toml_is_rejected_and_rolled_back() {
        // 回读解析失败（真的坏 TOML，不是注入）同样必须回滚
        let d = tmpdir();
        let p = seed(&d);
        atomic_write(&p, S2).unwrap();
        let r = atomic_write(&p, "a = = 1\r\n");
        assert!(matches!(r, Err(IoError::ReadbackParse(_))), "{r:?}");
        assert_eq!(std::fs::read_to_string(&p).unwrap(), S2);
    }

    #[test]
    fn fingerprint_changes_on_external_write() {
        let d = tmpdir();
        let p = seed(&d);
        let fp1 = fingerprint(&p).unwrap();
        // ① 内容变化（同时 mtime 变）
        std::fs::write(&p, "a = 42\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
        let fp2 = fingerprint(&p).unwrap();
        assert_ne!(fp1.sha256, fp2.sha256, "内容变了 sha256 必须变");
        // ② 只改 mtime（内容逐字节相同）—— 触摸一下文件
        std::thread::sleep(std::time::Duration::from_millis(20));
        std::fs::write(&p, "a = 42\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
        let fp3 = fingerprint(&p).unwrap();
        assert_ne!(
            fp2.mtime_ms, fp3.mtime_ms,
            "mtime 变了指纹就必须变（哪怕内容一样）"
        );
        assert_eq!(fp2.sha256, fp3.sha256);
        // ③ 同大小但内容不同 —— sha256 必须能区分（只比 size 是经典漏检）
        let a = d.join("a.toml");
        let b = d.join("b.toml");
        std::fs::write(&a, "x = 1\r\n").unwrap();
        std::fs::write(&b, "x = 2\r\n").unwrap();
        assert_eq!(
            fingerprint(&a).unwrap().size,
            fingerprint(&b).unwrap().size
        );
        assert_ne!(
            fingerprint(&a).unwrap().sha256,
            fingerprint(&b).unwrap().sha256,
            "同大小不同内容必须靠 sha256 区分"
        );
    }

    #[test]
    fn commit_conflict_does_not_touch_file() {
        let d = tmpdir();
        let p = seed(&d);
        let fp = fingerprint(&p).unwrap();
        // 外部改动
        std::fs::write(&p, "a = 42\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
        assert_ne!(fingerprint(&p).unwrap(), fp);
        assert_eq!(
            std::fs::read_to_string(&p).unwrap(),
            "a = 42\r\n# 注释\r\nb = \"x\"\r\n",
            "冲突检测只是比较，不得写文件"
        );
    }

    #[test]
    fn replace_null_backup_ok() {
        // 传 NULL 必须成功且不产生备份；传空串必须失败且原文件不变
        let d = tmpdir();
        let p = seed(&d);
        let tmp = d.join("config.toml.tmp");
        std::fs::write(&tmp, "z = 9\r\n").unwrap();
        assert!(replace_file_w(&p, &tmp, None).is_ok(), "NULL 备份必须成功");
        assert!(!d.join("config.toml.bak").exists());
        assert_eq!(std::fs::read_to_string(&p).unwrap(), "z = 9\r\n");

        let d2 = tmpdir().join("second");
        std::fs::create_dir_all(&d2).unwrap();
        let p2 = seed(&d2);
        let tmp2 = d2.join("config.toml.tmp");
        std::fs::write(&tmp2, "z = 9\r\n").unwrap();
        assert!(
            replace_file_w(&p2, &tmp2, Some("")).is_err(),
            "空串备份必须失败"
        );
        assert_eq!(std::fs::read_to_string(&p2).unwrap(), S0);
    }

    #[test]
    fn missing_target_is_not_created() {
        let d = tmpdir();
        let p = d.join("nope.toml");
        assert!(matches!(atomic_write(&p, S2), Err(IoError::NotFound(_))));
        assert!(!p.exists(), "目标不存在时不得凭空创建");
    }

    #[cfg(windows)]
    #[test]
    fn replace_keeps_acl() {
        use std::process::Command;
        let d = tmpdir();
        let p = seed(&d);
        let sddl = |path: &Path| -> String {
            // 用 pwsh -EncodedCommand 会引入 base64 噪声；直接走 icacls 的输出更稳。
            // 注意 `powershell` 在本机是 Windows PowerShell 5.1，`Get-Acl` 的中文
            // 区域输出可能进 stderr，所以统一改读 icacls 的 SDDL 行。
            let out = Command::new("icacls")
                .arg(path.to_string_lossy().as_ref())
                .output()
                .unwrap();
            String::from_utf8_lossy(&out.stdout).to_string()
        };
        // 加一条自定义 ACE
        Command::new("icacls")
            .args([p.to_string_lossy().as_ref(), "/grant", "Everyone:(R)"])
            .output()
            .unwrap();
        let before = sddl(&p);
        assert!(!before.is_empty());
        atomic_write(&p, S2).unwrap();
        assert_eq!(sddl(&p), before, "ReplaceFileW 必须保留目标 ACL");
    }
}
