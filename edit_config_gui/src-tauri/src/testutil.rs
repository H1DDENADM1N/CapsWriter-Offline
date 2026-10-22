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

/// 构造一个补丁（Task 3 加入：引用 `crate::patch`，Task 2 阶段编译不过）
pub fn patch(parts: &[&str], v: crate::patch::PatchValue) -> crate::patch::Patch {
    crate::patch::Patch {
        segments: seg(parts),
        value: v,
    }
}

/// 单行标量键的探针补丁集合：165 = 178 叶子 − 8 个多行 prompt 正文 − 3 个数组 − 2 条内联表条目
pub fn single_line_probe_patches(doc: &crate::config_doc::ConfigDoc) -> Vec<crate::patch::Patch> {
    use crate::config_doc::TomlType::*;
    use crate::patch::PatchValue as P;
    let mut out = Vec::new();
    for f in doc.leaf_fields() {
        let in_prompt_style =
            f.segments.len() == 3 && f.segments[0] == "client" && f.segments[1] == "prompt_style";
        if in_prompt_style && !f.segments[2].ends_with("_shortcut") {
            continue;
        }
        if f.segments.len() >= 3
            && f.segments[0] == "client"
            && f.segments[1] == "additional_special_apps"
        {
            continue;
        }
        let v = match (f.toml_type, &f.value) {
            (String, serde_json::Value::String(s)) => P::Str(format!("{s}_probe")),
            (Integer, serde_json::Value::Number(n)) => P::Int(n.as_i64().unwrap() + 1),
            (Float, serde_json::Value::Number(n)) => P::Float(n.as_f64().unwrap() + 0.01),
            (Boolean, serde_json::Value::Bool(b)) => P::Bool(!b),
            _ => continue,
        };
        out.push(crate::patch::Patch {
            segments: f.segments,
            value: v,
        });
    }
    out
}
