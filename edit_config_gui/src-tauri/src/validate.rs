//! 校验层：十个校验器 + 对「补丁应用之后」文档的全量校验报告。
//!
//! 语义逐条对齐旧 PySide6 版 `util/edit_config_gui/value_check.py`（错误文案逐字相同）。
//! 新增的三项（规格 §8.0.1 与 §7.4 结论 4）：`ipPort`（`client.adb_addr`）、
//! `regexClass`（`client.trash_punc`）、`singleLine`（所有单行控件）。

use crate::config_doc::ConfigDoc;

/// 校验器种类；序列化成 camelCase 字符串，与前端 `FieldMeta.validators` 逐字对应。
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ValidatorId {
    Ip,
    LocalListenableIp,
    Port,
    FileExist,
    DirExist,
    Hotkey,
    Url,
    SingleLine,
    IpPort,
    RegexClass,
}

/// 一个字段的校验规则；`segments` 一律用数组，禁止点分字符串（`vlc.exe` 里的点不是分隔符）。
#[derive(serde::Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct FieldRule {
    pub segments: Vec<String>,
    pub validators: Vec<ValidatorId>,
    pub allow_empty: bool,
    pub file_suffix: Option<String>,
    /// true = 只产生 warning，不阻断保存（`model_paths.*` 用）。
    pub warn_only: bool,
}

/// 一条校验问题。`segments` 是该字段的完整路径。
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ValidationError {
    pub segments: Vec<String>,
    pub validator: ValidatorId,
    pub message: String,
}

/// 全量校验结果：阻断保存的 error 与只提示的 warning 分开。
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct ValidationReport {
    pub errors: Vec<ValidationError>,
    pub warnings: Vec<ValidationError>,
}

/// 单值校验，供 preview/commit 复用与单测。
pub fn check_value(raw: &str, id: ValidatorId, suffix: Option<&str>) -> Result<(), String> {
    match id {
        ValidatorId::Ip => check_ip(raw).map(|_| ()).ok_or("不是有效的IP地址".to_string()),
        ValidatorId::LocalListenableIp => check_local_listenable_ip(raw),
        ValidatorId::Port => check_port(raw),
        ValidatorId::FileExist => check_file_exist(raw, suffix),
        ValidatorId::DirExist => check_dir_exist(raw),
        ValidatorId::Hotkey => {
            if crate::hotkey::is_valid_hotkey(raw) {
                Ok(())
            } else {
                Err("快捷键格式不正确".into())
            }
        }
        // Python: 先判空再判前缀（"URL不能为空" 优先于 "必须以…开头"）
        ValidatorId::Url => {
            if raw.is_empty() {
                Err("URL不能为空".into())
            } else if !(raw.starts_with("http://") || raw.starts_with("https://")) {
                Err("URL必须以http://或https://开头".into())
            } else {
                Ok(())
            }
        }
        ValidatorId::SingleLine => {
            if raw.contains('\n') || raw.contains('\r') {
                Err("该配置项不能包含换行符".into())
            } else {
                Ok(())
            }
        }
        ValidatorId::IpPort => check_ip_port(raw),
        ValidatorId::RegexClass => {
            if raw.is_empty() {
                Err("该配置项不能为空".into())
            } else if raw.contains('\\') || raw.contains('^') || raw.contains('[') {
                Err("该字符不能用于此处".into())
            } else {
                Ok(())
            }
        }
    }
}

/// 严格 IPv4：正好 4 段、每段 1–3 位 ASCII 数字、0–255、无前导零。
///
/// 对齐 Python `ipaddress.IPv4Address`：前导零（`01.2.3.4`）、冒号十六进制
/// （`::1`、`1.2.3.4:5`）、首尾空白、段数不足/多余一律抛 `AddressValueError`，
/// 因为该解析器只接受「4 段十进制、段内无前导零」的窄语法。
fn check_ip(raw: &str) -> Option<[u8; 4]> {
    let parts: Vec<&str> = raw.split('.').collect();
    if parts.len() != 4 {
        return None;
    }
    let mut octets = [0u8; 4];
    for (i, part) in parts.iter().enumerate() {
        if part.is_empty() || part.len() > 3 {
            return None;
        }
        if !part.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        // Python 拒绝前导零（"01"），"0" 本身合法
        if part.len() > 1 && part.starts_with('0') {
            return None;
        }
        let n: u32 = part.parse().ok()?;
        if n > 255 {
            return None;
        }
        octets[i] = n as u8;
    }
    Some(octets)
}

/// 先过 `Ip`，再限定到 10/8、172.16/12、192.168/16、127/8、169.254/16 与 `0.0.0.0`。
fn check_local_listenable_ip(raw: &str) -> Result<(), String> {
    let Some(ip) = check_ip(raw) else {
        return Err("不是有效的IP地址".into());
    };
    let listenable = ip[0] == 10
        || (ip[0] == 172 && (16..=31).contains(&ip[1]))
        || (ip[0] == 192 && ip[1] == 168)
        || ip[0] == 127
        || (ip[0] == 169 && ip[1] == 254)
        || ip == [0, 0, 0, 0];
    if listenable {
        Ok(())
    } else {
        Err("不是有效的本地可监听IP地址".into())
    }
}

/// 复刻 Python `int()` 的十进制解析：首尾空白、可选 `+`/`-`、数字间单个下划线。
///
/// 只用于端口与 IP:端口，所以超长数字直接饱和成 `i128::MAX`（必然越界，
/// 报「必须在1023到65535之间」而不是「不是有效的端口号」，与 Python 大整数一致）。
fn python_int(raw: &str) -> Option<i128> {
    let s = raw.trim();
    if s.is_empty() {
        return None;
    }
    let (negative, body) = match s.as_bytes()[0] {
        b'+' => (false, &s[1..]),
        b'-' => (true, &s[1..]),
        _ => (false, s),
    };
    let bytes = body.as_bytes();
    if bytes.is_empty() || bytes[0] == b'_' || bytes[bytes.len() - 1] == b'_' {
        return None;
    }
    let mut digits = String::with_capacity(bytes.len());
    let mut prev_underscore = false;
    for &b in bytes {
        match b {
            b'_' => {
                if prev_underscore {
                    return None;
                }
                prev_underscore = true;
            }
            b'0'..=b'9' => {
                prev_underscore = false;
                digits.push(b as char);
            }
            _ => return None,
        }
    }
    let trimmed = digits.trim_start_matches('0');
    let value: i128 = if trimmed.is_empty() {
        0
    } else if trimmed.len() > 18 {
        i128::MAX
    } else {
        trimmed.parse().ok()?
    };
    Some(if negative { -value } else { value })
}

fn check_port(raw: &str) -> Result<(), String> {
    match python_int(raw) {
        None => Err("不是有效的端口号".into()),
        Some(p) if (1023..=65535).contains(&p) => Ok(()),
        Some(_) => Err("端口号必须在1023到65535之间".into()),
    }
}

/// Python `Path.suffix` 语义（含点），比较大小写不敏感（brief 明确要求，比 Python 宽松）。
fn check_file_exist(raw: &str, suffix: Option<&str>) -> Result<(), String> {
    let path = std::path::Path::new(raw);
    if !path.exists() {
        return Err("文件不存在".into());
    }
    if !path.is_file() {
        return Err("不是有效的文件".into());
    }
    if let Some(suffix) = suffix {
        let actual = path
            .extension()
            .map(|e| format!(".{}", e.to_string_lossy()))
            .unwrap_or_default();
        if !actual.eq_ignore_ascii_case(suffix) {
            return Err(format!("文件格式不正确，预期后缀为{suffix}"));
        }
    }
    Ok(())
}

fn check_dir_exist(raw: &str) -> Result<(), String> {
    let path = std::path::Path::new(raw);
    if path.exists() && path.is_dir() {
        Ok(())
    } else {
        Err("目录不存在".into())
    }
}

/// `host[:port]`，按**最后一个** `:` 切分；无 `:` 时整串是 host。
///
/// host 非空、不含空白与 `:`；port 部分套 `Port`。这是新增校验器（规格 §7.4），
/// 对齐 `adb connect` 的地址写法：主机名可省端口，但端口写错必须拦。
fn check_ip_port(raw: &str) -> Result<(), String> {
    let (host, port) = match raw.rsplit_once(':') {
        Some((host, port)) => (host, Some(port)),
        None => (raw, None),
    };
    if host.is_empty() || host.chars().any(char::is_whitespace) || host.contains(':') {
        return Err("不是有效的地址".into());
    }
    if let Some(port) = port {
        check_port(port)?;
    }
    Ok(())
}

/// 对「补丁应用之后」的文档全量校验（不是只校验脏字段）。
pub fn validate_all(doc: &ConfigDoc, rules: &[FieldRule]) -> ValidationReport {
    let mut report = ValidationReport::default();
    for rule in rules {
        // 前端 schema 与磁盘不同步（缺键 / 类型不是标量）→ 跳过，不 panic 也不报错
        let Some(raw) = scalar_at(doc, &rule.segments) else {
            continue;
        };
        if rule.allow_empty && raw.trim().is_empty() {
            continue;
        }
        for &id in &rule.validators {
            if let Err(message) = check_value(&raw, id, rule.file_suffix.as_deref()) {
                let problem = ValidationError {
                    segments: rule.segments.clone(),
                    validator: id,
                    message,
                };
                // 一个字段只报第一条：前端 errors 是 Record<fieldId, string>，多报无处显示
                if rule.warn_only {
                    report.warnings.push(problem);
                } else {
                    report.errors.push(problem);
                }
                break;
            }
        }
    }
    report
}

/// 取某路径上的标量字面量；表 / 数组 / 内联表整体 / 缺失返回 `None`。
fn scalar_at(doc: &ConfigDoc, segments: &[String]) -> Option<String> {
    let (head, tail) = segments.split_first()?;
    // `ConfigDoc::get` 只沿 `Item::Table` 下钻，所以先取到第一段，
    // 之后的段（可能穿过内联表成员）由下面的递归负责。
    item_scalar(doc.get(std::slice::from_ref(head))?, tail)
}

fn item_scalar(item: &toml_edit::Item, rest: &[String]) -> Option<String> {
    match item {
        toml_edit::Item::Table(table) => table_scalar(table, rest),
        toml_edit::Item::Value(value) => value_scalar(value, rest),
        _ => None,
    }
}

fn table_scalar(table: &toml_edit::Table, rest: &[String]) -> Option<String> {
    let (head, tail) = rest.split_first()?;
    item_scalar(table.get(head)?, tail)
}

/// 内联表成员是 `&Value` 而不是 `&Item`，只能在这里逐层下钻。
fn value_scalar(value: &toml_edit::Value, rest: &[String]) -> Option<String> {
    match rest.split_first() {
        None => match value {
            toml_edit::Value::String(s) => Some(s.value().to_string()),
            toml_edit::Value::Integer(i) => Some(i.value().to_string()),
            toml_edit::Value::Float(f) => Some(f.value().to_string()),
            toml_edit::Value::Boolean(b) => Some(b.value().to_string()),
            toml_edit::Value::Datetime(d) => Some(d.value().to_string()),
            // 数组与内联表整体都不是标量，不参与校验
            toml_edit::Value::Array(_) | toml_edit::Value::InlineTable(_) => None,
        },
        Some((head, tail)) => match value {
            toml_edit::Value::InlineTable(table) => value_scalar(table.get(head)?, tail),
            _ => None,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config_doc::ConfigDoc;
    use crate::testutil::{load_real, patch, seg};

    fn ck(v: &str, id: ValidatorId) -> Result<(), String> {
        check_value(v, id, None)
    }

    fn rule(parts: &[&str], validators: Vec<ValidatorId>) -> FieldRule {
        FieldRule {
            segments: seg(parts),
            validators,
            allow_empty: false,
            file_suffix: None,
            warn_only: false,
        }
    }

    #[test]
    fn validate_ip() {
        for ok in ["127.0.0.1", "192.168.3.5", "8.8.8.8", "0.0.0.0", "255.255.255.255"] {
            assert!(ck(ok, ValidatorId::Ip).is_ok(), "{ok}");
        }
        // "01.2.3.4" 在 Python ipaddress.IPv4Address 里是非法（前导零歧义），必须一致拒绝
        for bad in [
            "256.1.1.1",
            "1.2.3",
            "abc",
            "",
            " 1.2.3.4",
            "1.2.3.4.5",
            "01.2.3.4",
            "1.2.3.4 ",
        ] {
            assert_eq!(ck(bad, ValidatorId::Ip).unwrap_err(), "不是有效的IP地址", "{bad:?}");
        }
    }

    #[test]
    fn validate_local_listenable_ip() {
        for ok in ["127.0.0.1", "192.168.1.1", "10.0.0.5", "172.16.0.1", "169.254.1.1", "0.0.0.0"] {
            assert!(ck(ok, ValidatorId::LocalListenableIp).is_ok(), "{ok}");
        }
        assert!(ck("8.8.8.8", ValidatorId::LocalListenableIp).is_err(), "公网 IP 不得通过");
        assert_eq!(
            ck("8.8.8.8", ValidatorId::LocalListenableIp).unwrap_err(),
            "不是有效的本地可监听IP地址"
        );
    }

    #[test]
    fn validate_port() {
        for ok in ["1023", "1024", "6016", "65535"] {
            assert!(ck(ok, ValidatorId::Port).is_ok(), "{ok}");
        }
        assert_eq!(ck("80", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
        assert_eq!(ck("1022", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
        assert_eq!(ck("65536", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
        assert_eq!(ck("0", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
        assert_eq!(ck("abc", ValidatorId::Port).unwrap_err(), "不是有效的端口号");
    }

    #[test]
    fn validate_url() {
        assert!(ck("http://x", ValidatorId::Url).is_ok());
        assert!(ck("https://x/y", ValidatorId::Url).is_ok());
        assert_eq!(ck("ftp://x", ValidatorId::Url).unwrap_err(), "URL必须以http://或https://开头");
        assert_eq!(ck("", ValidatorId::Url).unwrap_err(), "URL不能为空");
    }

    #[test]
    fn validate_regex_class() {
        assert!(ck("，。,.", ValidatorId::RegexClass).is_ok());
        assert_eq!(ck("", ValidatorId::RegexClass).unwrap_err(), "该配置项不能为空");
        for bad in ["\\", "^", "[", "a[b", "a\\b", "^a"] {
            assert_eq!(ck(bad, ValidatorId::RegexClass).unwrap_err(), "该字符不能用于此处", "{bad:?}");
        }
        // 防止禁用集开得过大
        for good in [
            "，", "。", "、", "；", "：", "？", "！", "…", "—", "～", "·", "「", "」", "『", "』", "（",
            "）", "【", "】", "《", "》", "〈", "〉", "“", "”", "‘", "’", "｡", "､", "｢", "｣", "]", "(",
            ")", "*", "+", "?", ".", "-", "~", ",", ";", "!", "@", "$", "%", "&", "/",
        ] {
            assert!(ck(good, ValidatorId::RegexClass).is_ok(), "应允许: {good:?}");
        }
    }

    #[test]
    fn validate_ip_port() {
        for ok in ["192.168.3.127:10101", "192.168.3.127", "localhost", "my-phone:5555", "10.0.0.2:1024"] {
            assert!(ck(ok, ValidatorId::IpPort).is_ok(), "{ok}");
        }
        assert_eq!(ck("host:70000", ValidatorId::IpPort).unwrap_err(), "端口号必须在1023到65535之间");
        assert_eq!(ck("host:abc", ValidatorId::IpPort).unwrap_err(), "不是有效的端口号");
        assert_eq!(ck("", ValidatorId::IpPort).unwrap_err(), "不是有效的地址");
        assert_eq!(ck("a:b:c", ValidatorId::IpPort).unwrap_err(), "不是有效的地址");
    }

    #[test]
    fn validate_single_line() {
        assert!(ck("普通文本", ValidatorId::SingleLine).is_ok());
        assert_eq!(ck("a\nb", ValidatorId::SingleLine).unwrap_err(), "该配置项不能包含换行符");
        assert!(ck("a\rb", ValidatorId::SingleLine).is_err());
    }

    #[test]
    fn validate_file_and_dir() {
        let tmp = std::env::temp_dir().join("dsh_validate_probe.txt");
        std::fs::write(&tmp, b"x").unwrap();
        let p = tmp.to_string_lossy().to_string();
        assert!(check_value(&p, ValidatorId::FileExist, Some(".txt")).is_ok());
        assert_eq!(
            check_value(&p, ValidatorId::FileExist, Some(".onnx")).unwrap_err(),
            "文件格式不正确，预期后缀为.onnx"
        );
        assert_eq!(
            check_value("C:/绝对不存在的路径/x.txt", ValidatorId::FileExist, None).unwrap_err(),
            "文件不存在"
        );
        assert_eq!(check_value("C:/绝对不存在的路径", ValidatorId::DirExist, None).unwrap_err(), "目录不存在");
        let dir = std::env::temp_dir();
        assert!(check_value(&dir.to_string_lossy(), ValidatorId::DirExist, None).is_ok());
        assert_eq!(
            check_value(&dir.to_string_lossy(), ValidatorId::FileExist, None).unwrap_err(),
            "不是有效的文件"
        );
    }

    #[test]
    fn allow_empty_skips_validation() {
        let rules = vec![FieldRule {
            segments: seg(&["client", "QQMusic_global_pause_hotkey"]),
            validators: vec![ValidatorId::Hotkey],
            allow_empty: true,
            file_suffix: None,
            warn_only: false,
        }];
        let (doc, _) = load_real();
        let report = validate_all(&doc, &rules);
        assert!(report.errors.is_empty(), "allow_empty 的空值不得报错");
    }

    #[test]
    fn warn_only_goes_to_warnings() {
        // 真实 config 里的默认模型文件在本机是存在的（models/Fun-ASR-Nano-…q8_0.gguf），
        // 所以把路径改成确定不存在的一份，才能证明「缺失 = warning 而非 error」。
        let (doc, _) = load_real();
        let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
        crate::patch::apply(
            &mut broken,
            &[patch(
                &["model_paths", "funasr_llm_path"],
                crate::patch::PatchValue::Str("models/绝对不存在的模型.q8_0.gguf".into()),
            )],
        )
        .unwrap();
        let rules = vec![FieldRule {
            segments: seg(&["model_paths", "funasr_llm_path"]),
            validators: vec![ValidatorId::FileExist],
            allow_empty: false,
            file_suffix: Some(".gguf".into()),
            warn_only: true,
        }];
        let report = validate_all(&broken, &rules);
        assert!(report.errors.is_empty());
        assert_eq!(report.warnings.len(), 1, "模型未下载只警告");
        assert_eq!(report.warnings[0].message, "文件不存在");
    }

    #[test]
    fn hidden_field_not_validated() {
        // adb 关闭时前端不下发 adb_addr 的规则；这里验证「不下发 = 不校验」，
        // 同时反向证明「一旦下发，坏值确实会被拦」——两半都断言，否则这条测试恒真。
        let (doc, _) = load_real();
        let adb_rule = FieldRule {
            segments: seg(&["client", "adb_addr"]),
            validators: vec![ValidatorId::IpPort],
            allow_empty: false,
            file_suffix: None,
            warn_only: false,
        };

        // ① 不下发规则 → 文档里那条（合法的）adb_addr 不产生任何 error
        let without = validate_all(&doc, &[]);
        assert!(without.errors.is_empty());

        // ② 下发规则但值是坏的 → 必须报错（证明 ① 不是因为校验器失效才为空）
        let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
        crate::patch::apply(
            &mut broken,
            &[patch(&["client", "adb_addr"], crate::patch::PatchValue::Str("a:b:c".into()))],
        )
        .unwrap();
        let with = validate_all(&broken, &[adb_rule]);
        assert_eq!(with.errors.len(), 1, "坏值必须被 IpPort 拦下");
        assert_eq!(with.errors[0].message, "不是有效的地址");
    }

    #[test]
    fn error_aggregation() {
        // 三个字段同时非法 → 一次返回三条错误，不能只报第一条就停
        let (doc, _) = load_real();
        let rules = vec![
            FieldRule {
                segments: seg(&["server", "addr"]),
                validators: vec![ValidatorId::LocalListenableIp],
                allow_empty: false,
                file_suffix: None,
                warn_only: false,
            },
            FieldRule {
                segments: seg(&["server", "speech_recognition_port"]),
                validators: vec![ValidatorId::Port],
                allow_empty: false,
                file_suffix: None,
                warn_only: false,
            },
            FieldRule {
                segments: seg(&["libretranslate", "api"]),
                validators: vec![ValidatorId::Url],
                allow_empty: false,
                file_suffix: None,
                warn_only: false,
            },
        ];
        let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
        use crate::patch::PatchValue;
        crate::patch::apply(
            &mut broken,
            &[
                patch(&["server", "addr"], PatchValue::Str("8.8.8.8".into())),
                patch(&["server", "speech_recognition_port"], PatchValue::Str("80".into())),
                patch(&["libretranslate", "api"], PatchValue::Str("ftp://x".into())),
            ],
        )
        .unwrap();
        let report = validate_all(&broken, &rules);
        assert_eq!(report.errors.len(), 3, "三个非法字段必须报三条");
        assert!(report.warnings.is_empty());
        // 顺序按 rules 顺序，保证前端错误表可稳定覆盖
        assert_eq!(report.errors[0].segments, seg(&["server", "addr"]));
        assert_eq!(report.errors[1].segments, seg(&["server", "speech_recognition_port"]));
        assert_eq!(report.errors[2].segments, seg(&["libretranslate", "api"]));
    }

    #[test]
    fn rule_for_missing_segment_is_ignored() {
        // 前端 schema 与磁盘文件不同步（例如用户手删了某键）时，规则不能 panic
        let (doc, _) = load_real();
        let rules = vec![FieldRule {
            segments: seg(&["client", "不存在的键"]),
            validators: vec![ValidatorId::Ip],
            allow_empty: false,
            file_suffix: None,
            warn_only: false,
        }];
        let report = validate_all(&doc, &rules);
        assert!(report.errors.is_empty(), "找不到的值跳过校验，不得 panic 也不得报错");
    }

    // ——— 以下为 brief 之外的补强用例：brief 的 allow_empty 用例里值本来就合法，
    // 无法证明「空串被跳过」，所以补一条把值真改成空串的。

    #[test]
    fn allow_empty_really_skips_empty_value() {
        let (doc, _) = load_real();
        let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
        let skip = FieldRule {
            segments: seg(&["client", "QQMusic_global_pause_hotkey"]),
            validators: vec![ValidatorId::Hotkey],
            allow_empty: true,
            file_suffix: None,
            warn_only: false,
        };
        let rules = [skip];
        for empty in ["", "   "] {
            crate::patch::apply(
                &mut broken,
                &[patch(&["client", "QQMusic_global_pause_hotkey"], crate::patch::PatchValue::Str(empty.into()))],
            )
            .unwrap();
            let report = validate_all(&broken, &rules);
            assert!(report.errors.is_empty(), "allow_empty=true 时 {empty:?} 必须跳过校验");
        }

        let strict = FieldRule {
            segments: seg(&["client", "QQMusic_global_pause_hotkey"]),
            validators: vec![ValidatorId::Hotkey],
            allow_empty: false,
            file_suffix: None,
            warn_only: false,
        };
        let report = validate_all(&broken, &[strict]);
        assert_eq!(report.errors.len(), 1, "allow_empty=false 时空串必须报错");
        assert_eq!(report.errors[0].message, "快捷键格式不正确");
    }

    #[test]
    fn port_follows_python_int_semantics() {
        // Python int(" 6016 ") / int("+6016") / int("6_016") 都等于 6016；int("6016.0") 抛 ValueError。
        assert!(ck(" 6016 ", ValidatorId::Port).is_ok());
        assert!(ck("+6016", ValidatorId::Port).is_ok());
        assert!(ck("6_016", ValidatorId::Port).is_ok());
        assert_eq!(ck("6016.0", ValidatorId::Port).unwrap_err(), "不是有效的端口号");
        assert_eq!(ck("-80", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
    }

    #[test]
    fn file_suffix_is_case_insensitive() {
        let tmp = std::env::temp_dir().join("dsh_validate_suffix.txt");
        std::fs::write(&tmp, b"x").unwrap();
        let p = tmp.to_string_lossy().to_string();
        assert!(check_value(&p, ValidatorId::FileExist, Some(".TXT")).is_ok(), "后缀比较必须大小写不敏感");
    }

    #[test]
    fn array_and_table_rules_are_skipped() {
        let (doc, _) = load_real();
        let rules = vec![
            rule(&["client", "enter_apps"], vec![ValidatorId::Ip]), // 数组
            rule(&["client", "prompt_style"], vec![ValidatorId::RegexClass]), // 表
            rule(&["client", "additional_special_apps", "vlc.exe"], vec![ValidatorId::Ip]), // 整行内联表
        ];
        let report = validate_all(&doc, &rules);
        assert!(report.errors.is_empty(), "数组 / 表 / 整行内联表都不能按标量校验");
    }

    #[test]
    fn integer_value_is_validated_as_text() {
        // audio_name_len = 20（TOML Integer）；Port 校验器要拿到 "20" 才会报越界。
        let (doc, _) = load_real();
        let rules = vec![rule(&["client", "audio_name_len"], vec![ValidatorId::Port])];
        let report = validate_all(&doc, &rules);
        assert_eq!(report.errors.len(), 1, "Integer 叶子必须按字面量参与校验");
        assert_eq!(report.errors[0].message, "端口号必须在1023到65535之间");
    }

    #[test]
    fn inline_table_member_is_validated() {
        // 4 段内联表成员 ConfigDoc::get 拿不到（&Value 借不出 &Item），必须回退到叶子视图，
        // 否则动态表条目的坏快捷键会被静默跳过。
        let (doc, _) = load_real();
        let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
        crate::patch::apply(
            &mut broken,
            &[patch(
                &["client", "additional_special_apps", "vlc.exe", "hotkey"],
                crate::patch::PatchValue::Str("f999".into()),
            )],
        )
        .unwrap();
        let rules = vec![rule(
            &["client", "additional_special_apps", "vlc.exe", "hotkey"],
            vec![ValidatorId::Hotkey],
        )];
        let report = validate_all(&broken, &rules);
        assert_eq!(report.errors.len(), 1, "动态表条目的快捷键必须被校验");
        assert_eq!(report.errors[0].message, "快捷键格式不正确");
    }

    #[test]
    fn first_failing_validator_wins() {
        // 一个字段只报第一条失败：前端 errors 是 Record<fieldId, string>，多报无处显示。
        let doc = ConfigDoc::parse("a = \"\"\n").unwrap();
        let rules = vec![rule(&["a"], vec![ValidatorId::Url, ValidatorId::FileExist])];
        let report = validate_all(&doc, &rules);
        assert_eq!(report.errors.len(), 1, "一个字段只报一条");
        assert_eq!(report.errors[0].validator, ValidatorId::Url);
        assert_eq!(report.errors[0].message, "URL不能为空");
    }
}
