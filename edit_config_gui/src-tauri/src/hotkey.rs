//! 快捷键校验：等价移植 Python `keyboard.parse_hotkey()`。
//!
//! 旧编辑器用 `util/edit_config_gui/value_check.py` 的 `from keyboard import parse_hotkey`
//! 校验快捷键；新后端没有 Python 运行时，所以这里做逐条等价移植。验收口径是
//! `tests/fixtures/hotkey_cases.txt` 的 **841 例与 Python 实测结果 0 差异**
//! （432 合法 / 409 非法，见 `hotkey_parity` 测试）。
//!
//! 两张表由 `edit_config_gui/scripts/export_hotkey_tables.py` 从已装的 `keyboard` 包导出：
//! - `hotkey_names.json`：`_winkeyboard.from_name` 的键集（205 项），即「能被识别为扫描码的名字」
//! - `canonical_names.json`：`_canonical_names.canonical_names`（1171 项），别名 → 规范名
//!
//! # 移植时逐条实测确认的语义（都是旧 GUI 的实际行为，不能「顺手优化」）
//!
//! - **不 trim**：`"  ctrl  +  alt  +  f5  "` 非法，报错信息里保留空格。
//! - **分隔符最多吃一个空白**：`re.split(r',\s?')` 与 `re.split(r'\s?\+\s?')`，
//!   所以 `"ctrl  +  a"`（两个空格）非法，而 `"ctrl + a"` 合法。
//! - **空部件必错**：`""`、`"ctrl + "`、`"ctrl + shift + ,"` 都会走到空部件，
//!   `normalize_name("")` 抛异常。
//! - **单字符短路**：`len(hotkey) == 1` 时走 `key_to_scan_codes(hotkey)` 而非切分路径。
//!   注意这**不是**「单字符一律合法」——只有能映射到扫描码的那 95 个可打印 ASCII 才合法，
//!   `"中"`、`"€"` 非法。也**不是**「纯数字短路」：`"9"` 合法但 `"123"` 非法。
//! - **大小写**：`len > 1` 才 `lower()`，所以 `"Ctrl + F5"` 合法、单字符 `"A"` 保持大写
//!   （`"A"` 恰好在 `from_name` 里，所以也合法）。
//! - **下划线**：`name != "_"` 且含 `_` 时把 `_` 换成空格；单独一个 `"_"`
//!   原样保留（它映射到减号扫描码，合法）。
//! - **受控修饰符**：`sided_modifiers = {ctrl, alt, shift, windows}`，命中时递归试
//!   `left <n>` 与 `right <n>`，任一存在即算该键成立（`shift` → `(42, 54)` 左右两个扫描码）。
//! - **`f13`..`f24` 合法，`f25` 起非法**。

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

/// `keyboard` 的 `sided_modifiers`（实测值，顺序无关）。
const SIDED_MODIFIERS: [&str; 4] = ["ctrl", "alt", "shift", "windows"];

static ACCEPTED: OnceLock<HashSet<String>> = OnceLock::new();
static CANONICAL: OnceLock<HashMap<String, String>> = OnceLock::new();

/// `from_name` 的键集：名字 → 是否有扫描码。
fn accepted() -> &'static HashSet<String> {
    ACCEPTED.get_or_init(|| {
        serde_json::from_str(include_str!("hotkey_names.json")).expect("hotkey_names.json 损坏")
    })
}

/// 别名 → 规范名。
fn canonical() -> &'static HashMap<String, String> {
    CANONICAL.get_or_init(|| {
        serde_json::from_str(include_str!("canonical_names.json")).expect("canonical_names.json 损坏")
    })
}

/// 等价于 `keyboard.parse_hotkey(hk)` 不抛异常。
pub fn is_valid_hotkey(hk: &str) -> bool {
    // Python: `if _is_number(hotkey) or len(hotkey) == 1:` —— 入参恒为字符串，
    // `_is_number`（isinstance int）不适用，只剩单字符短路。按 Unicode 码点计数。
    if hk.chars().count() == 1 {
        return key_resolves(hk);
    }
    for step in split_steps(hk) {
        for key in split_plus(step) {
            if !key_resolves(key) {
                return false;
            }
        }
    }
    true
}

/// 等价于 `keyboard.key_to_scan_codes(key, error_if_missing=True)` 不抛异常。
fn key_resolves(key: &str) -> bool {
    let Some(normalized) = normalize_name(key) else {
        // normalize_name 对空串抛 ValueError
        return false;
    };
    if SIDED_MODIFIERS.contains(&normalized.as_str()) {
        // Python 用 error_if_missing=False 递归取左右扫描码，任一非空即成功
        let left = format!("left {normalized}");
        let right = format!("right {normalized}");
        return lookup(&left).is_some() || lookup(&right).is_some();
    }
    lookup(&normalized).is_some()
}

/// 等价于 `keyboard._winkeyboard.map_name(name)` 能产出至少一条扫描码。
fn lookup(normalized: &str) -> Option<()> {
    accepted().contains(normalized).then_some(())
}

/// 等价于 `keyboard._canonical_names.normalize_name(name)`；空串返回 `None`（对应抛异常）。
fn normalize_name(name: &str) -> Option<String> {
    if name.is_empty() {
        return None;
    }
    // Python: `if len(name) > 1: name = name.lower()` —— 按字符数判断，不是字节数
    let mut out = if name.chars().count() > 1 {
        name.to_lowercase()
    } else {
        name.to_string()
    };
    // Python: `if name != '_' and '_' in name: name = name.replace('_', ' ')`
    if out != "_" && out.contains('_') {
        out = out.replace('_', " ");
    }
    // Python: `return canonical_names.get(name, name)`
    Some(canonical().get(&out).cloned().unwrap_or(out))
}

/// 等价于 `re.split(r',\s?', hotkey)`。
///
/// 逗号后**最多**吃掉一个空白字符，多出来的空格会成为下一段的开头（进而导致解析失败）。
fn split_steps(hk: &str) -> Vec<&str> {
    let chars: Vec<(usize, char)> = hk.char_indices().collect();
    let mut out = Vec::new();
    let mut start = 0usize; // 当前段在 hk 里的字节起点
    let mut i = 0usize;
    while i < chars.len() {
        let (byte_idx, c) = chars[i];
        if c == ',' {
            out.push(&hk[start..byte_idx]);
            let mut next = i + 1;
            // `\s?` 只吃一个空白
            if next < chars.len() && is_py_whitespace(chars[next].1) {
                next += 1;
            }
            start = if next < chars.len() { chars[next].0 } else { hk.len() };
            i = next;
            continue;
        }
        i += 1;
    }
    out.push(&hk[start..]);
    out
}

/// 等价于 `re.split(r'\s?\+\s?', step)`。
///
/// 正则从左到右取最左匹配，且 `\s?` 贪婪：若 `+` 前是空白就先吃掉那个空白；
/// 若 `+` 前是连续两个空白，只吃紧邻的那一个，前面那个留在上一段末尾（导致解析失败）。
fn split_plus(step: &str) -> Vec<&str> {
    let chars: Vec<(usize, char)> = step.char_indices().collect();
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        let (byte_idx, c) = chars[i];
        // 情况 A：`\s?` 吃一个空白，`\+` 吃紧随其后的 '+'
        if is_py_whitespace(c) && i + 1 < chars.len() && chars[i + 1].1 == '+' {
            out.push(&step[start..byte_idx]);
            let mut next = i + 2;
            if next < chars.len() && is_py_whitespace(chars[next].1) {
                next += 1;
            }
            start = if next < chars.len() { chars[next].0 } else { step.len() };
            i = next;
            continue;
        }
        // 情况 B：`\s?` 匹配空，直接吃 '+'
        if c == '+' {
            out.push(&step[start..byte_idx]);
            let mut next = i + 1;
            if next < chars.len() && is_py_whitespace(chars[next].1) {
                next += 1;
            }
            start = if next < chars.len() { chars[next].0 } else { step.len() };
            i = next;
            continue;
        }
        i += 1;
    }
    out.push(&step[start..]);
    out
}

/// Python `str.isspace()` 的等价判定（`re` 的 `\s` 用它）。
///
/// 与 Rust `char::is_whitespace()` 的差集只有 U+001C..U+001F：Python 认为是空白，
/// Unicode White_Space 属性不认。实测 `"a\x1c+b"` 在 Python 里会被 `\s?` 吃掉 `\x1c`。
fn is_py_whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validate_hotkey_minimal_regression() {
        for ok in [
            "caps lock",
            "ctrl + alt + f5",
            "Ctrl + Alt + F5",
            "left shift",
            "ctrl + alt + [",
            "f13",
            "f24",
            "space",
            "enter",
            "shift",
            "+",
            "_",
            "esc",
            "escape",
            "ctrl+alt+f5",
            "alt+a, alt+b",
            "volume up",
            "left windows",
            "alt+f4",
        ] {
            assert!(is_valid_hotkey(ok), "应合法: {ok:?}");
        }
        for bad in [
            "f999",
            "f25",
            "",
            "ctrl + ",
            "mouse left",
            "  ctrl  +  alt  +  f5  ",
            "ctrl + shift + ,",
            "鼠标",
        ] {
            assert!(!is_valid_hotkey(bad), "应非法: {bad:?}");
        }
    }

    #[test]
    fn hotkey_parity() {
        let cases = include_str!("../tests/fixtures/hotkey_cases.txt");
        let expect = include_str!("../tests/fixtures/hotkey_expected.txt");
        let (mut ok_n, mut diff) = (0usize, 0usize);
        for (c, e) in cases.lines().zip(expect.lines()) {
            let got = if is_valid_hotkey(c) { "ok" } else { "err" };
            if got == "ok" {
                ok_n += 1;
            }
            if got != e {
                diff += 1;
                eprintln!("diff: {c:?} expected {e} got {got}");
            }
        }
        assert_eq!(cases.lines().count(), 841);
        assert_eq!(expect.lines().count(), 841);
        assert_eq!(diff, 0, "与 Python keyboard 的对拍必须 0 差异");
        assert_eq!(ok_n, 432);
    }

    /// 别名穷举对拍：1171 个 canonical 键 + 205 个 from_name 名字及其 left/right/大写变体，
    /// 共 1887 例。手工挑的 841 例无法覆盖「某个别名到底认不认」，这里逐个比。
    ///
    /// fixture 是 JSON 而非行式文本：`canonical_names` 里有两个键本身是 `"\n"` 与 `"\r"`，
    /// 写进行式文件会把文件切碎并让后续逐行错位。
    #[test]
    fn hotkey_alias_parity() {
        let rows: Vec<(String, String)> =
            serde_json::from_str(include_str!("../tests/fixtures/hotkey_alias.json"))
                .expect("hotkey_alias.json 损坏");
        assert_eq!(rows.len(), 1887);
        let mut diff = 0usize;
        for (case, want) in &rows {
            let got = if is_valid_hotkey(case) { "ok" } else { "err" };
            if got != want {
                diff += 1;
                if diff <= 40 {
                    eprintln!("alias diff: {case:?} expected {want} got {got}");
                }
            }
        }
        assert_eq!(diff, 0, "别名穷举对拍必须 0 差异");
    }

    /// 空白字符语义对拍（110 例）：`re` 的 `\s` 把 U+001C..U+001F 也算空白，
    /// Unicode White_Space 属性不认 —— 这直接改变 `\s?` 能吃掉哪个字符。
    /// 另含「分隔符后跟 2 个以上空白」的判别用例：只吃一个 vs 吃光，真值必然不同。
    #[test]
    fn hotkey_whitespace_parity() {
        let rows: Vec<(String, String)> =
            serde_json::from_str(include_str!("../tests/fixtures/hotkey_whitespace.json"))
                .expect("hotkey_whitespace.json 损坏");
        assert_eq!(rows.len(), 110);
        let mut diff = 0usize;
        for (case, want) in &rows {
            let got = if is_valid_hotkey(case) { "ok" } else { "err" };
            if got != want {
                diff += 1;
                eprintln!("ws diff: {case:?} expected {want} got {got}");
            }
        }
        assert_eq!(diff, 0, "空白语义对拍必须 0 差异");
    }

    /// 两张表的规模钉死：`export_hotkey_tables.py` 重跑后若数字变了，
    /// 说明 upstream `keyboard` 包换了键名表 —— 必须重新对拍。
    #[test]
    fn exported_tables_have_expected_size() {
        assert_eq!(accepted().len(), 205, "hotkey_names.json 应含 205 个键名");
        assert_eq!(canonical().len(), 1171, "canonical_names.json 应含 1171 条映射");
    }

    /// 单字符短路不是「一律合法」：只有能映射到扫描码的那批可打印 ASCII 成立。
    #[test]
    fn single_char_is_not_blanket_valid() {
        for ok in ["a", "A", "0", "9", "+", "_", ",", "[", "`", " ", "~"] {
            assert!(is_valid_hotkey(ok), "单字符应合法: {ok:?}");
        }
        for bad in ["中", "€", "\u{7f}"] {
            assert!(!is_valid_hotkey(bad), "无扫描码的单字符应非法: {bad:?}");
        }
    }

    /// 纯数字不短路：`"9"` 合法（单字符），`"12"` / `"123"` 非法。
    #[test]
    fn multi_digit_is_not_a_number_shortcut() {
        assert!(is_valid_hotkey("9"));
        assert!(!is_valid_hotkey("12"));
        assert!(!is_valid_hotkey("123"));
    }

    /// 分隔符最多吃一个空白：一个空格合法、两个空格非法。
    #[test]
    fn separator_consumes_at_most_one_space() {
        assert!(is_valid_hotkey("ctrl + a"));
        assert!(!is_valid_hotkey("ctrl  +  a"));
        assert!(is_valid_hotkey("alt+a, alt+b"));
        assert!(!is_valid_hotkey("alt+a ,  alt+b"));
    }

    /// 下划线单独成键合法（映射到减号）；`name != '_'` 时才把 `_` 换成空格。
    #[test]
    fn underscore_rules() {
        assert!(is_valid_hotkey("_"));
        assert!(is_valid_hotkey("ctrl+_"));
        // `_` 作为**单独的部件**时原样保留（不换空格），所以组合里也成立
        assert!(is_valid_hotkey("ctrl+_+a"));
        assert!(is_valid_hotkey("ctrl + _ + a"));
        // 但 `_` 出现在**名字内部**时要换成空格，`caps_lock` 等价于 `caps lock`
        assert!(is_valid_hotkey("caps_lock"));
        assert!(!is_valid_hotkey("no_such_key_name"));
    }
}
