//! 补丁应用：类型保真、decor（缩进与行尾注释）保真、动态表与数组的精确编辑，以及 unified diff。
//!
//! 三条硬性约束（规格 §7.4 实测结论）：
//! 1. 标量替换必须把旧 `Value` 的 `prefix`/`suffix` 搬到新 `Value`——行尾注释就存在 `suffix` 里；
//! 2. 动态表**禁止** `Table::clear()` 重建（会丢每个条目的行尾注释），只能逐项 `insert`/`remove`；
//! 3. 数组首元素的 `prefix` 必须是 `""`，否则输出成 `[ ["a", 0.5]]`（多一个空格）。

use std::collections::BTreeMap;

use toml_edit::{Array, DocumentMut, Formatted, InlineTable, Item, Table, Value};

use crate::config_doc::{ConfigDoc, TdError, TomlType};

/// 一个补丁的新值。JSON 形如 `{"kind":"str","value":"..."}`；`delete` 没有 `value` 字段。
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone)]
#[serde(tag = "kind", content = "value", rename_all = "camelCase")]
pub enum PatchValue {
    Str(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    StrArray(Vec<String>),
    PairArray(Vec<(String, f64)>),
    /// 动态表中的一个条目：segments 指向该条目的键，值是该条目的字段映射。
    TableRow(BTreeMap<String, String>),
    /// 删除一个键、一个数组的首元素，或一个动态表条目。
    Delete,
}

/// 一个补丁：`segments` 是精确路径（禁止点分字符串，见 §5.2），`value` 是新值或删除指令。
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone)]
pub struct Patch {
    pub segments: Vec<String>,
    pub value: PatchValue,
}

/// 单行键白名单：只有这 8 个多行提示词正文允许含 `\n`。
pub const LONG_TEXT_PATHS: [&[&str]; 8] = [
    &["client", "prompt_style", "prompt_official"],
    &["client", "prompt_style", "prompt_sweetheart"],
    &["client", "prompt_style", "prompt_social"],
    &["client", "prompt_style", "prompt_poetry"],
    &["client", "prompt_style", "prompt_english"],
    &["client", "prompt_style", "prompt_academic"],
    &["client", "prompt_style", "prompt_customer_service"],
    &["client", "prompt_style", "prompt_creative_writing"],
];

/// 动态表的父路径（`Table::insert` / `Table::remove` 只作用在这一层）。
const DYNAMIC_TABLE: [&str; 2] = ["client", "additional_special_apps"];

/// 依次应用补丁，返回被改动过的 segments（去重，保持首次出现顺序）。
///
/// 两趟：先非 `Delete`，后 `Delete`（规格 §5.4），避免「先删后建」时索引错位。
pub fn apply(doc: &mut ConfigDoc, patches: &[Patch]) -> Result<Vec<Vec<String>>, TdError> {
    let mut changed: Vec<Vec<String>> = Vec::new();
    for p in patches {
        if matches!(p.value, PatchValue::Delete) {
            continue;
        }
        apply_one(doc, p)?;
        note_changed(&mut changed, &p.segments);
    }
    for p in patches {
        if !matches!(p.value, PatchValue::Delete) {
            continue;
        }
        apply_one(doc, p)?;
        note_changed(&mut changed, &p.segments);
    }
    Ok(changed)
}

fn note_changed(changed: &mut Vec<Vec<String>>, segments: &[String]) {
    if !changed.iter().any(|s| s == segments) {
        changed.push(segments.to_vec());
    }
}

/// 生成 unified diff，context 3 行。
pub fn unified_diff(before: &str, after: &str) -> String {
    similar::TextDiff::from_lines(before, after)
        .unified_diff()
        .context_radius(3)
        .header("config.toml (当前)", "config.toml (保存后)")
        .to_string()
}

// ---------------------------------------------------------------- 分发

fn apply_one(doc: &mut ConfigDoc, p: &Patch) -> Result<(), TdError> {
    let segments = p.segments.as_slice();
    if segments.is_empty() {
        return Err(TdError::NotFound(Vec::new()));
    }
    check_newline(segments, &p.value)?;

    if is_dynamic_table(segments) {
        return match segments.len() {
            3 => match &p.value {
                PatchValue::TableRow(map) => upsert_row(doc.doc_mut(), segments, map),
                PatchValue::Delete => remove_row(doc.doc_mut(), segments),
                _ => Err(TdError::TypeMismatch(segments.to_vec())),
            },
            4 => match &p.value {
                PatchValue::Delete => remove_inline_member(doc.doc_mut(), segments),
                other => set_inline_member(doc.doc_mut(), segments, other),
            },
            _ => Err(TdError::NotFound(segments.to_vec())),
        };
    }

    match &p.value {
        PatchValue::Delete => delete_target(doc.doc_mut(), segments),
        other => set_key(doc.doc_mut(), segments, other),
    }
}

fn is_dynamic_table(segments: &[String]) -> bool {
    segments.len() >= 2 && segments[0] == DYNAMIC_TABLE[0] && segments[1] == DYNAMIC_TABLE[1]
}

/// 单行键不得写入含换行的值（否则会被 `toml_edit` 升格成 `"""` 多行块）。
fn check_newline(segments: &[String], value: &PatchValue) -> Result<(), TdError> {
    let has_newline = match value {
        PatchValue::Str(s) => s.contains('\n') || s.contains('\r'),
        PatchValue::StrArray(items) => items.iter().any(|s| s.contains('\n') || s.contains('\r')),
        PatchValue::TableRow(map) => map
            .values()
            .any(|s| s.contains('\n') || s.contains('\r')),
        _ => false,
    };
    if has_newline && !is_long_text(segments) {
        return Err(TdError::NewlineInSingleLine(segments.to_vec()));
    }
    Ok(())
}

fn is_long_text(segments: &[String]) -> bool {
    LONG_TEXT_PATHS
        .iter()
        .any(|p| p.len() == segments.len() && p.iter().zip(segments).all(|(a, b)| *a == b.as_str()))
}

// ---------------------------------------------------------------- 定位

/// 沿 path 逐段下钻到表。用递归而不是循环，避免 NLL 下的 `&mut` 重借用问题。
fn table_mut<'a>(table: &'a mut Table, path: &[String]) -> Result<&'a mut Table, TdError> {
    let Some((head, rest)) = path.split_first() else {
        return Ok(table);
    };
    match table.get_mut(head.as_str()) {
        Some(Item::Table(inner)) => table_mut(inner, rest),
        Some(_) => Err(TdError::NotAContainer(path.to_vec())),
        None => Err(TdError::NotFound(path.to_vec())),
    }
}

fn value_type(v: &Value) -> TomlType {
    match v {
        Value::String(_) => TomlType::String,
        Value::Integer(_) => TomlType::Integer,
        Value::Float(_) => TomlType::Float,
        Value::Boolean(_) => TomlType::Boolean,
        Value::Array(_) => TomlType::Array,
        Value::InlineTable(_) => TomlType::InlineTable,
        // TomlType 没有日期时间项；配置里也没有，按字符串处理以免丢键。
        Value::Datetime(_) => TomlType::String,
    }
}

// ---------------------------------------------------------------- 标量写入

/// 一对一替换一个标量值，保留 prefix（缩进）与 suffix（行尾注释）。
fn set_scalar(item: &mut Item, new: Value) -> Result<(), TdError> {
    let Item::Value(old) = item else {
        return Err(TdError::TypeMismatch(Vec::new()));
    };
    set_scalar_value(old, new)
}

/// `set_scalar` 的内核：内联表成员也是 `&mut Value`，复用同一套 decor 搬运。
fn set_scalar_value(old: &mut Value, mut new: Value) -> Result<(), TdError> {
    let (prefix, suffix) = (old.decor().prefix().cloned(), old.decor().suffix().cloned());
    if let Some(prefix) = prefix {
        new.decor_mut().set_prefix(prefix);
    }
    if let Some(suffix) = suffix {
        // ← 行尾注释在 suffix 里，丢掉它就丢了 `# VLC 设置全局快捷键后需要重启 VLC 才能生效`
        new.decor_mut().set_suffix(suffix);
    }
    *old = new;
    Ok(())
}

fn set_key(
    doc: &mut DocumentMut,
    segments: &[String],
    value: &PatchValue,
) -> Result<(), TdError> {
    let (last, path) = segments
        .split_last()
        .ok_or_else(|| TdError::NotFound(segments.to_vec()))?;
    let table = table_mut(doc.as_table_mut(), path)?;
    let item = table
        .get_mut(last.as_str())
        .ok_or_else(|| TdError::NotFound(segments.to_vec()))?;
    write_item(item, segments, value)
}

fn write_item(item: &mut Item, segments: &[String], value: &PatchValue) -> Result<(), TdError> {
    let ty = match item {
        Item::Value(old) => value_type(old),
        _ => return Err(TdError::NotAContainer(segments.to_vec())),
    };
    let new = build_value(ty, value, segments)?;
    set_scalar(item, new)
}

/// `PatchValue` × 现有 `TomlType` 的类型矩阵（规格 §5.4 表）。
fn build_value(
    ty: TomlType,
    value: &PatchValue,
    segments: &[String],
) -> Result<Value, TdError> {
    let mismatch = || TdError::TypeMismatch(segments.to_vec());
    match ty {
        TomlType::String => match value {
            PatchValue::Str(s) => Ok(Value::String(Formatted::new(s.clone()))),
            PatchValue::Int(i) => Ok(Value::String(Formatted::new(i.to_string()))),
            PatchValue::Float(f) => Ok(Value::String(Formatted::new(f.to_string()))),
            _ => Err(mismatch()),
        },
        TomlType::Integer => match value {
            PatchValue::Int(i) => Ok(Value::Integer(Formatted::new(*i))),
            PatchValue::Float(f) => Ok(Value::Integer(Formatted::new(f.trunc() as i64))),
            PatchValue::Str(s) => s
                .trim()
                .parse::<i64>()
                .map(|i| Value::Integer(Formatted::new(i)))
                .map_err(|_| mismatch()),
            _ => Err(mismatch()),
        },
        TomlType::Float => match value {
            // 硬性：f64 必须走 Formatted::new，否则 `*f = nv.as_float()` 类型不匹配（E0308）
            PatchValue::Float(f) => Ok(Value::Float(Formatted::new(*f))),
            PatchValue::Int(i) => Ok(Value::Float(Formatted::new(*i as f64))),
            PatchValue::Str(s) => s
                .trim()
                .parse::<f64>()
                .map(|f| Value::Float(Formatted::new(f)))
                .map_err(|_| mismatch()),
            _ => Err(mismatch()),
        },
        TomlType::Boolean => match value {
            PatchValue::Bool(b) => Ok(Value::Boolean(Formatted::new(*b))),
            PatchValue::Str(s) => match s.trim() {
                "true" => Ok(Value::Boolean(Formatted::new(true))),
                "false" => Ok(Value::Boolean(Formatted::new(false))),
                _ => Err(mismatch()),
            },
            _ => Err(mismatch()),
        },
        TomlType::Array => match value {
            PatchValue::StrArray(items) => Ok(Value::Array(string_array(items))),
            PatchValue::PairArray(pairs) => Ok(Value::Array(pair_array(pairs))),
            _ => Err(mismatch()),
        },
        // 3 段动态表条目由 upsert_row 处理；走到这里说明补丁与目标类型不配。
        TomlType::InlineTable => Err(mismatch()),
    }
}

/// 重建字符串数组：首元素 `prefix = ""`，其余 `" "`（规格 §7.4 结论 6）。
fn string_array(items: &[String]) -> Array {
    let mut arr = Array::new();
    if items.is_empty() {
        // 占位语义（规格 §3.4）：空列表写回 [""]，不写 []
        let mut v = Value::String(Formatted::new(String::new()));
        v.decor_mut().set_prefix("");
        arr.push_formatted(v);
        return arr;
    }
    for (i, s) in items.iter().enumerate() {
        let mut v = Value::String(Formatted::new(s.clone()));
        v.decor_mut().set_prefix(if i == 0 { "" } else { " " });
        arr.push_formatted(v);
    }
    arr
}

/// 重建二维数组 `[["进程名", 延迟], ...]`，内外两层都按首元素无前缀处理。
fn pair_array(pairs: &[(String, f64)]) -> Array {
    let mut arr = Array::new();
    for (i, (name, delay)) in pairs.iter().enumerate() {
        let mut inner = Array::new();
        let mut name_value = Value::String(Formatted::new(name.clone()));
        name_value.decor_mut().set_prefix("");
        let mut delay_value = Value::Float(Formatted::new(*delay));
        delay_value.decor_mut().set_prefix(" ");
        inner.push_formatted(name_value);
        inner.push_formatted(delay_value);

        let mut pair = Value::Array(inner);
        pair.decor_mut().set_prefix(if i == 0 { "" } else { " " });
        arr.push_formatted(pair);
    }
    arr
}

// ---------------------------------------------------------------- 动态表

/// 新增或就地改写动态表的一个条目。**禁止 `Table::clear()` 重建**（会丢条目的行尾注释）。
fn upsert_row(
    doc: &mut DocumentMut,
    segments: &[String],
    map: &BTreeMap<String, String>,
) -> Result<(), TdError> {
    let key = segments[2].as_str();
    let table = table_mut(doc.as_table_mut(), &segments[..2])?;
    match table.get_mut(key) {
        Some(Item::Value(Value::InlineTable(row))) => {
            for (field, text) in map {
                match row.get_mut(field.as_str()) {
                    Some(member) => {
                        // 逐字段改写，每个字段的 decor（含行尾注释）单独搬运
                        set_scalar_value(member, Value::String(Formatted::new(text.clone())))?;
                    }
                    None => {
                        row.insert(field.as_str(), Value::String(Formatted::new(text.clone())));
                    }
                }
            }
            Ok(())
        }
        Some(_) => Err(TdError::TypeMismatch(segments.to_vec())),
        None => {
            let mut row = InlineTable::new();
            for (field, text) in map {
                row.insert(field.as_str(), Value::String(Formatted::new(text.clone())));
            }
            // `Table::insert` 自己会给特殊键名加引号（实测 `"my app.exe"` 等）
            table.insert(key, Item::Value(Value::InlineTable(row)));
            Ok(())
        }
    }
}

fn remove_row(doc: &mut DocumentMut, segments: &[String]) -> Result<(), TdError> {
    let key = segments[2].as_str();
    let table = table_mut(doc.as_table_mut(), &segments[..2])?;
    if table.remove(key).is_none() {
        return Err(TdError::NotFound(segments.to_vec()));
    }
    Ok(())
}

fn set_inline_member(
    doc: &mut DocumentMut,
    segments: &[String],
    value: &PatchValue,
) -> Result<(), TdError> {
    let row = inline_row_mut(doc, segments)?;
    let member = row
        .get_mut(segments[3].as_str())
        .ok_or_else(|| TdError::NotFound(segments.to_vec()))?;
    let ty = value_type(member);
    let new = build_value(ty, value, segments)?;
    set_scalar_value(member, new)
}

fn remove_inline_member(doc: &mut DocumentMut, segments: &[String]) -> Result<(), TdError> {
    let row = inline_row_mut(doc, segments)?;
    if row.remove(segments[3].as_str()).is_none() {
        return Err(TdError::NotFound(segments.to_vec()));
    }
    Ok(())
}

fn inline_row_mut<'a>(
    doc: &'a mut DocumentMut,
    segments: &[String],
) -> Result<&'a mut InlineTable, TdError> {
    let table = table_mut(doc.as_table_mut(), &segments[..2])?;
    match table.get_mut(segments[2].as_str()) {
        Some(Item::Value(Value::InlineTable(row))) => Ok(row),
        Some(_) => Err(TdError::TypeMismatch(segments.to_vec())),
        None => Err(TdError::NotFound(segments.to_vec())),
    }
}

// ---------------------------------------------------------------- 删除

/// `Delete` 的三种目标：动态表条目（走 `remove_row`）、数组（删首个元素）、普通键（整键移除）。
fn delete_target(doc: &mut DocumentMut, segments: &[String]) -> Result<(), TdError> {
    let (last, path) = segments
        .split_last()
        .ok_or_else(|| TdError::NotFound(segments.to_vec()))?;
    let table = table_mut(doc.as_table_mut(), path)?;
    let is_array = match table.get(last.as_str()) {
        None => return Err(TdError::NotFound(segments.to_vec())),
        Some(Item::Value(Value::Array(_))) => true,
        Some(_) => false,
    };
    if is_array {
        if let Some(Item::Value(Value::Array(arr))) = table.get_mut(last.as_str()) {
            if !arr.is_empty() {
                arr.remove(0);
                // 删掉首元素后，原第二元素的 prefix 会变成新首元素的前缀，必须清掉
                if let Some(first) = arr.get_mut(0) {
                    first.decor_mut().set_prefix("");
                }
            }
        }
        Ok(())
    } else {
        table.remove(last.as_str());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config_doc::ConfigDoc;
    use crate::testutil::{
        comment_line_count, comment_multiset, load_real, patch, seg, single_line_probe_patches,
        REAL,
    };

    #[test]
    fn type_fidelity_string() {
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[patch(
                &["server", "speech_recognition_port"],
                PatchValue::Int(9999),
            )],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert!(
            out.contains(r#"speech_recognition_port = "9999""#),
            "原为字符串，写入后必须仍是字符串"
        );
    }

    #[test]
    fn type_fidelity_int_and_float() {
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[patch(&["client", "audio_name_len"], PatchValue::Int(30))],
        )
        .unwrap();
        apply(
            &mut doc,
            &[patch(&["client", "threshold"], PatchValue::Float(0.75))],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert!(out.contains("audio_name_len = 30"));
        assert!(out.contains("threshold = 0.75"));
    }

    #[test]
    fn type_mismatch_rejected() {
        let (mut doc, _) = load_real();
        let e = apply(
            &mut doc,
            &[patch(
                &["client", "addr"],
                PatchValue::PairArray(vec![("a".into(), 0.5)]),
            )],
        );
        assert!(matches!(e, Err(TdError::TypeMismatch(_))));
    }

    #[test]
    fn single_line_key_touches_one_line() {
        let raw = std::fs::read_to_string(REAL).unwrap();
        let doc = ConfigDoc::parse(&raw).unwrap();
        let base_lines = raw.lines().count();
        // 149 = 162 叶子 − 8 个多行 prompt 正文 − 3 个数组 − 2 条内联表条目（均已用 tomllib 实测）
        let probes = single_line_probe_patches(&doc);
        assert_eq!(probes.len(), 149);
        for p in probes {
            let mut d = ConfigDoc::parse(&raw).unwrap();
            apply(&mut d, &[p]).unwrap();
            let out = d.to_toml_string();
            assert_eq!(out.lines().count(), base_lines, "单行键改动不得改变行数");
            let changed = raw.lines().zip(out.lines()).filter(|(a, b)| a != b).count();
            assert_eq!(changed, 1, "只允许 1 行不同");
            assert_eq!(comment_line_count(&out), 306);
        }
    }

    #[test]
    fn comments_preserved_on_set() {
        let (mut doc, raw) = load_real();
        apply(
            &mut doc,
            &[
                patch(
                    &["client", "QQMusic_global_pause_hotkey"],
                    PatchValue::Str("ctrl + alt + f11".into()),
                ),
                patch(&["client", "threshold"], PatchValue::Float(0.9)),
                patch(&["server", "model"], PatchValue::Str("Sensevoice".into())),
            ],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert_eq!(comment_line_count(&out), 306);
        assert_eq!(
            comment_multiset(&out),
            comment_multiset(&raw),
            "注释内容也必须不变"
        );
    }

    #[test]
    fn inline_comment_survives_scalar_edit() {
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[patch(
                &["client", "additional_special_apps", "vlc.exe", "hotkey"],
                PatchValue::Str("ctrl + alt + f10".into()),
            )],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert!(
            out.contains("# VLC 设置全局快捷键后需要重启 VLC 才能生效"),
            "行尾注释必须随 decor 搬运保留"
        );
    }

    #[test]
    fn newline_rejected_in_single_line() {
        let (mut doc, _) = load_real();
        let e = apply(
            &mut doc,
            &[patch(&["server", "addr"], PatchValue::Str("a\nb".into()))],
        );
        assert!(matches!(e, Err(TdError::NewlineInSingleLine(_))));
    }

    #[test]
    fn multiline_prompt_allows_newline() {
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[patch(
                &["client", "prompt_style", "prompt_official"],
                PatchValue::Str("第一行\n第二行".into()),
            )],
        )
        .unwrap();
        let out = doc.to_toml_string();
        ConfigDoc::parse(&out).expect("写回后必须仍可解析");
    }

    #[test]
    fn multiline_quote_and_backslash_roundtrip() {
        let (mut doc, _) = load_real();
        let evil = "含\"\"\"三引号\\与\\反斜杠#井号\t制表";
        apply(
            &mut doc,
            &[patch(
                &["client", "prompt_style", "prompt_official"],
                PatchValue::Str(evil.into()),
            )],
        )
        .unwrap();
        let out = doc.to_toml_string();
        let back = ConfigDoc::parse(&out).unwrap();
        let got = back
            .get(&seg(&["client", "prompt_style", "prompt_official"]))
            .unwrap();
        assert_eq!(got.as_str().unwrap(), evil);
    }

    #[test]
    fn scalar_trailing_comment_preserved() {
        // 补强：brief 的 16 个测试里没有任何一条能失败地守护「标量值自身的行尾注释」。
        // config.toml 里只有 logger_level（L3）这一个普通标量带行尾注释，
        // 把它删掉后 `single_line_key_touches_one_line` 仍只看到「1 行不同」而通过。
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[patch(&["debug", "logger_level"], PatchValue::Str("INFO".into()))],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert!(
            out.contains("logger_level = \"INFO\" # 调试日志级别"),
            "标量值的行尾注释必须随 decor 的 suffix 搬运保留"
        );
    }

    #[test]
    fn dynamic_table_row_update_keeps_trailing_comment() {
        // 补强：brief 的 16 个测试没有一条能让「逐项 insert vs Table::clear() 重建」真伪可辨。
        // 改写既有条目（3 段 TableRow）必须不动行数、不丢该条目的行尾注释。
        let (mut doc, raw) = load_real();
        let base = raw.lines().count();
        apply(
            &mut doc,
            &[Patch {
                segments: seg(&["client", "additional_special_apps", "vlc.exe"]),
                value: PatchValue::TableRow(
                    [
                        ("hotkey".into(), "ctrl + alt + f10".into()),
                        ("name".into(), "VLC Media Player".into()),
                    ]
                    .into(),
                ),
            }],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert_eq!(out.lines().count(), base, "改写既有条目不得改变行数");
        assert!(out.contains(r#""vlc.exe" = { hotkey = "ctrl + alt + f10", name = "VLC Media Player" } # VLC 设置全局快捷键后需要重启 VLC 才能生效"#));
        assert_eq!(comment_line_count(&out), 306);
    }

    #[test]
    fn dynamic_table_add_remove() {
        let (mut doc, raw) = load_real();
        let base = raw.lines().count();
        apply(
            &mut doc,
            &[Patch {
                segments: seg(&["client", "additional_special_apps", "test.exe"]),
                value: PatchValue::TableRow(
                    [
                        ("hotkey".into(), "ctrl + alt + f11".into()),
                        ("name".into(), "Test App".into()),
                    ]
                    .into(),
                ),
            }],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert_eq!(out.lines().count(), base + 1);
        assert_eq!(comment_line_count(&out), 306);
        assert!(out.contains("# VLC 设置全局快捷键后需要重启 VLC 才能生效"));

        let mut d2 = ConfigDoc::parse(&out).unwrap();
        apply(
            &mut d2,
            &[Patch {
                segments: seg(&["client", "additional_special_apps", "vlc.exe"]),
                value: PatchValue::Delete,
            }],
        )
        .unwrap();
        let out2 = d2.to_toml_string();
        assert_eq!(out2.lines().count(), base);
        assert_eq!(comment_line_count(&out2), 306, "删条目不得删注释");
    }

    #[test]
    fn dynamic_table_weird_key_quoted() {
        let (doc, _) = load_real();
        for key in ["my app.exe", "a\"b.exe", "中文进程.exe", "a.b.c"] {
            let mut d = ConfigDoc::parse(&doc.original_text()).unwrap();
            apply(
                &mut d,
                &[Patch {
                    segments: vec![
                        "client".into(),
                        "additional_special_apps".into(),
                        key.into(),
                    ],
                    value: PatchValue::TableRow(
                        [("hotkey".into(), "".into()), ("name".into(), "n".into())].into(),
                    ),
                }],
            )
            .unwrap();
            let out = d.to_toml_string();
            let back = ConfigDoc::parse(&out).expect("含特殊字符的键名必须写出合法 TOML");
            assert!(back
                .get(&vec![
                    "client".into(),
                    "additional_special_apps".into(),
                    key.into()
                ])
                .is_some());
        }
    }

    #[test]
    fn array_prefix_normalized() {
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[patch(
                &["client", "enter_apps"],
                PatchValue::PairArray(vec![("hexin.exe".into(), 0.5)]),
            )],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert!(
            out.contains(r#"enter_apps = [["hexin.exe", 0.5]]"#),
            "不得出现 [ [ 的额外空格"
        );
    }

    #[test]
    fn empty_string_list_placeholder_roundtrip() {
        let (mut doc, _) = load_real();
        // 前端把「只含空串」规整为空数组，保存时必须写回 [""]
        apply(
            &mut doc,
            &[patch(
                &["client", "disable_exe_list"],
                PatchValue::StrArray(vec![]),
            )],
        )
        .unwrap();
        assert!(doc
            .to_toml_string()
            .contains(r#"disable_exe_list = [""]"#));
    }

    #[test]
    fn tolerant_load_of_out_of_range_int() {
        // 超范围值只影响控件提示，不得影响解析或其它字段
        let mut txt = std::fs::read_to_string(REAL).unwrap();
        txt = txt.replace("mic_seg_duration = 60", "mic_seg_duration = 120");
        let mut doc = ConfigDoc::parse(&txt).unwrap();
        apply(
            &mut doc,
            &[patch(&["client", "audio_name_len"], PatchValue::Int(25))],
        )
        .unwrap();
        assert!(doc.to_toml_string().contains("audio_name_len = 25"));
    }

    #[test]
    fn diff_only_changed() {
        let raw = std::fs::read_to_string(REAL).unwrap();
        let mut doc = ConfigDoc::parse(&raw).unwrap();
        apply(
            &mut doc,
            &[
                patch(&["client", "threshold"], PatchValue::Float(0.7)),
                patch(&["server", "model"], PatchValue::Str("Sensevoice".into())),
                patch(&["debug", "logger_level"], PatchValue::Str("INFO".into())),
            ],
        )
        .unwrap();
        let d = unified_diff(&raw, &doc.to_toml_string());
        let added = d
            .lines()
            .filter(|l| l.starts_with('+') && !l.starts_with("+++"))
            .count();
        let removed = d
            .lines()
            .filter(|l| l.starts_with('-') && !l.starts_with("---"))
            .count();
        assert_eq!((added, removed), (3, 3));
    }

    #[test]
    fn delete_applied_after_non_delete() {
        // 同一批里既有删除又追加，删除必须后跑，避免索引错位
        let (mut doc, _) = load_real();
        apply(
            &mut doc,
            &[
                Patch {
                    segments: seg(&["client", "enter_apps"]),
                    value: PatchValue::Delete,
                },
                Patch {
                    segments: seg(&["client", "disable_exe_list"]),
                    value: PatchValue::StrArray(vec!["a.exe".into()]),
                },
            ],
        )
        .unwrap();
        let out = doc.to_toml_string();
        assert!(!out.contains("happ.exe"));
        assert!(out.contains(r#"disable_exe_list = ["a.exe"]"#));
    }
}
