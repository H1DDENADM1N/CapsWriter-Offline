#![cfg(test)]
/// Vec<&str> -> Vec<String>，所有测试用它构造 segments（禁止点分字符串）
pub fn seg(parts: &[&str]) -> Vec<String> {
    parts.iter().map(|s| s.to_string()).collect()
}

/// 读仓库根的真实 config.toml（cargo test 的 cwd 是 src-tauri）
pub const REAL: &str = "../../config.toml";

/// (解析后的文档, 磁盘原始文本)。名叫 load_real 以免和 ConfigDoc::load(path) 混淆
pub fn load_real() -> (crate::config_doc::ConfigDoc, String) {
    let raw = std::fs::read_to_string(REAL).unwrap();
    let doc = crate::config_doc::ConfigDoc::parse(&raw).unwrap();
    (doc, raw)
}

/// 以 `#` 开头的整行数（含前导空白）
pub fn comment_line_count(text: &str) -> usize {
    text.lines()
        .filter(|l| l.trim_start().starts_with('#'))
        .count()
}

/// 注释行的排序多重集，用于断言「注释内容一字未变」
pub fn comment_multiset(text: &str) -> Vec<String> {
    let mut v: Vec<String> = text
        .lines()
        .filter(|l| l.trim_start().starts_with('#'))
        .map(|l| l.trim_end().to_string())
        .collect();
    v.sort();
    v
}

/// 临时目录（每个测试独立）
pub fn tmpdir() -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!(
        "dsh_ecg_{}_{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// 在临时目录里放一份最小 config.toml 并返回其路径
pub fn seed(dir: &std::path::Path) -> std::path::PathBuf {
    let p = dir.join("config.toml");
    std::fs::write(&p, "a = 1\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    p
}

// 说明（与 brief 的差异）：brief Step 0 里还列了 `patch()` 与
// `single_line_probe_patches()` 两个构造器，它们直接引用 `crate::patch::PatchValue` /
// `crate::patch::Patch`，而 `src/patch.rs` 由 Task 3 建立。Task 2 阶段编译不过，
// 因此这两个函数留给 Task 3 在新增 `patch.rs` 时一并加入本文件（内容照 brief 原文）。
