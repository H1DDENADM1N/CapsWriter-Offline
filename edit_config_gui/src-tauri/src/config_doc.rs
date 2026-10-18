//! TOML 文档模型：解析（先把 CRLF 归一化为 LF）、字节级保真输出（再还原 CRLF）、叶子枚举。

use std::path::{Path, PathBuf};

use toml_edit::{DocumentMut, Item, Table, Value};

/// 值的 TOML 类型。用于前端控件选择与补丁类型校验。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TomlType {
    String,
    Integer,
    Float,
    Boolean,
    Array,
    InlineTable,
}

/// `TomlType` 的唯一字符串表示（camelCase），前端 `FieldView.tomlType` 只认这个。
pub fn toml_type_name(t: TomlType) -> &'static str {
    match t {
        TomlType::String => "string",
        TomlType::Integer => "integer",
        TomlType::Float => "float",
        TomlType::Boolean => "boolean",
        TomlType::Array => "array",
        TomlType::InlineTable => "inlineTable",
    }
}

/// 一个叶子键：完整 segments、JSON 化的值、类型。
#[derive(Debug, Clone)]
pub struct FieldEntry {
    pub segments: Vec<String>,
    pub value: serde_json::Value,
    pub toml_type: TomlType,
}

/// 配置文档读写过程中的错误。segments 为出错键的完整路径（空表示与具体键无关）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TdError {
    Io(String),
    Parse(String),
    NotFound(Vec<String>),
    TypeMismatch(Vec<String>),
    NewlineInSingleLine(Vec<String>),
    NotAContainer(Vec<String>),
}

impl std::fmt::Display for TdError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TdError::Io(e) => write!(f, "读取失败：{e}"),
            TdError::Parse(e) => write!(f, "解析失败：{e}"),
            TdError::NotFound(p) => write!(f, "找不到配置项：{}", p.join(".")),
            TdError::TypeMismatch(p) => write!(f, "类型不匹配：{}", p.join(".")),
            TdError::NewlineInSingleLine(p) => write!(f, "单行配置项不能包含换行：{}", p.join(".")),
            TdError::NotAContainer(p) => write!(f, "不是表：{}", p.join(".")),
        }
    }
}

impl std::error::Error for TdError {}

/// 文件原本用的行尾。输出时按它还原，避免把用户文件的所有行尾改掉。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Eol {
    Crlf,
    Lf,
}

impl Eol {
    /// 探测输入文本的行尾风格：只要出现过 CRLF 就按 CRLF 处理。
    ///
    /// 本仓库 `core.autocrlf=true`，工作树里是 CRLF；但若某台机器 checkout 成 LF，
    /// 强制输出 CRLF 会让「只改一个键」的保存变成 852 行全变。所以按输入还原。
    pub fn detect(text: &str) -> Self {
        if text.contains("\r\n") {
            Eol::Crlf
        } else {
            Eol::Lf
        }
    }

    /// 行尾字符串。`to_toml_string` 直接 match `Eol` 而不用它，留着供后续
    /// （diff 标题、日志、测试文案）复用；`#[allow(dead_code)]` 以免整库构建时告警。
    #[allow(dead_code)]
    fn as_str(self) -> &'static str {
        match self {
            Eol::Crlf => "\r\n",
            Eol::Lf => "\n",
        }
    }
}

/// 内存中的 TOML 文档。`original_text` 保留磁盘原文（含 CRLF），供指纹与 diff 使用。
pub struct ConfigDoc {
    doc: DocumentMut,
    path: PathBuf,
    original_text: String,
    eol: Eol,
}

impl ConfigDoc {
    /// 输入为磁盘原始文本（可含 CRLF）；内部做 LF 归一化，并记住原行尾。
    pub fn parse(text: &str) -> Result<Self, TdError> {
        let original_text = text.to_string();
        let eol = Eol::detect(text);
        // 硬性：先归一化，否则 toml_edit 会把 CRLF 拆成 199 CRLF + 653 裸 LF。
        let lf = text.replace("\r\n", "\n");
        let doc: DocumentMut = lf
            .parse()
            .map_err(|e: toml_edit::TomlError| TdError::Parse(e.to_string()))?;
        Ok(Self {
            doc,
            path: PathBuf::new(),
            original_text,
            eol,
        })
    }

    /// 从磁盘读取并解析，记录路径。
    pub fn load(path: &Path) -> Result<Self, TdError> {
        let text = std::fs::read_to_string(path).map_err(|e| TdError::Io(e.to_string()))?;
        let mut doc = Self::parse(&text)?;
        doc.path = path.to_path_buf();
        Ok(doc)
    }

    /// `parse` 不设路径，`path()` 返回空；只有 `load` 会填。
    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn original_text(&self) -> &str {
        &self.original_text
    }

    /// 输入文件原本的行尾风格。
    pub fn eol(&self) -> Eol {
        self.eol
    }

    /// 按 segments 精确查找（禁用点分字符串："vlc.exe" 里的点不是分隔符）。
    ///
    /// 只沿 `Item::Table` 下钻；内联表本身是 `Value::InlineTable`，它的成员
    /// 是 `&Value` 而不是 `&Item`，所以只能查到内联表这一层。
    ///
    /// **注意**：`…,"vlc.exe","hotkey"` 这类 4 段内联表成员这里返回 `None`，
    /// 而 `toml_type_at` 同一路径返回 `Some(String)`。两者不同时为 `Some` 是设计行为
    /// （签名是 `Option<&Item>`，内联表成员借不出 `&Item`）。要改内联表成员的值，
    /// 用 `doc_mut()` 逐层 `get_mut` 到 `&mut Value`，不要走 `get()`。
    pub fn get(&self, segments: &[String]) -> Option<&Item> {
        let mut table: &Table = self.doc.as_table();
        let (last, init) = segments.split_last()?;
        for seg in init {
            match table.get(seg)? {
                Item::Table(t) => table = t,
                _ => return None,
            }
        }
        table.get(last)
    }

    /// 该 segments 处的 TOML 类型；表/缺失返回 None。
    ///
    /// 与 `get` 不同，这里可以下钻到内联表成员内部（`…,"vlc.exe","hotkey"`），
    /// 因为判定类型不需要把成员借出成 `&Item`。
    pub fn toml_type_at(&self, segments: &[String]) -> Option<TomlType> {
        type_in_table(self.doc.as_table(), segments)
    }

    /// 按输入文件原本的行尾输出（CRLF 进 CRLF 出，LF 进 LF 出）。
    pub fn to_toml_string(&self) -> String {
        let lf = self.doc.to_string();
        match self.eol {
            Eol::Crlf => lf.replace('\n', "\r\n"),
            Eol::Lf => lf,
        }
    }

    /// 全部叶子：(segments, 值 JSON, TomlType)。数组与内联表整体作为叶子。
    pub fn leaf_fields(&self) -> Vec<FieldEntry> {
        let mut out = Vec::new();
        let mut prefix = Vec::new();
        collect_table(self.doc.as_table(), &mut prefix, &mut out);
        out
    }

    pub fn doc_mut(&mut self) -> &mut DocumentMut {
        &mut self.doc
    }
}

fn collect_table(table: &Table, prefix: &mut Vec<String>, out: &mut Vec<FieldEntry>) {
    for (key, item) in table.iter() {
        prefix.push(key.to_string());
        collect_item(item, prefix, out);
        prefix.pop();
    }
}

/// 递归规则（叶子数 162 的口径，逐字照 brief）：
/// - `Item::Table` → 递归，自身不计；
/// - `Item::Value(Value::InlineTable)` → 只把每个子字段各输出一条，自身不计；
/// - `Item::ArrayOfTables` → 一条 Array 叶子；
/// - `Item::Value(其他)` → 一条叶子；
/// - `Item::None` → 跳过。
fn collect_item(item: &Item, prefix: &mut Vec<String>, out: &mut Vec<FieldEntry>) {
    match item {
        Item::Table(t) => collect_table(t, prefix, out),
        Item::Value(Value::InlineTable(t)) => {
            for (key, value) in t.iter() {
                prefix.push(key.to_string());
                out.push(FieldEntry {
                    segments: prefix.clone(),
                    value: value_to_json(value),
                    toml_type: value_toml_type(value),
                });
                prefix.pop();
            }
        }
        // 配置里没有 [[table]]；真出现时整体作为一条 Array 叶子，值展开成 JSON 对象数组。
        Item::ArrayOfTables(aot) => out.push(FieldEntry {
            segments: prefix.clone(),
            value: serde_json::Value::Array(
                aot.iter().map(|t| table_to_json(t)).collect(),
            ),
            toml_type: TomlType::Array,
        }),
        Item::Value(v) => out.push(FieldEntry {
            segments: prefix.clone(),
            value: value_to_json(v),
            toml_type: value_toml_type(v),
        }),
        Item::None => {}
    }
}

/// 沿 segments 逐段下钻判定类型：表继续下行，内联表成员再下钻（成员是 `Value` 而非 `Item`）。
fn type_in_table(table: &Table, segments: &[String]) -> Option<TomlType> {
    let (head, rest) = segments.split_first()?;
    match table.get(head)? {
        Item::Table(t) => {
            if rest.is_empty() {
                None
            } else {
                type_in_table(t, rest)
            }
        }
        Item::ArrayOfTables(_) => {
            if rest.is_empty() {
                Some(TomlType::Array)
            } else {
                None
            }
        }
        Item::Value(v) => {
            if rest.is_empty() {
                Some(value_toml_type(v))
            } else {
                type_in_value(v, rest)
            }
        }
        Item::None => None,
    }
}

fn type_in_value(v: &Value, segments: &[String]) -> Option<TomlType> {
    let (head, rest) = segments.split_first()?;
    let Value::InlineTable(t) = v else {
        return None;
    };
    let member = t.get(head)?;
    if rest.is_empty() {
        Some(value_toml_type(member))
    } else {
        type_in_value(member, rest)
    }
}

fn value_toml_type(v: &Value) -> TomlType {
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

/// `Item::ArrayOfTables` 的每个元素展开成 JSON 对象。
fn table_to_json(t: &Table) -> serde_json::Value {
    let mut map = serde_json::Map::new();
    for (key, item) in t.iter() {
        let value = match item {
            Item::Value(v) => value_to_json(v),
            Item::Table(inner) => table_to_json(inner),
            Item::ArrayOfTables(inner) => {
                serde_json::Value::Array(inner.iter().map(table_to_json).collect())
            }
            Item::None => continue,
        };
        map.insert(key.to_string(), value);
    }
    serde_json::Value::Object(map)
}

/// TOML 值 → JSON 值。数组内联表递归；浮点走 `Number::from_f64` 保精度。
fn value_to_json(v: &Value) -> serde_json::Value {
    match v {
        Value::String(s) => serde_json::Value::String(s.value().to_string()),
        Value::Integer(i) => serde_json::Value::Number((*i.value()).into()),
        Value::Float(f) => serde_json::Number::from_f64(*f.value())
            .map(serde_json::Value::Number)
            // NaN/Inf 无法用 JSON 数字表示，退化成一个字符串，保证键不丢。
            .unwrap_or_else(|| serde_json::Value::String(f.value().to_string())),
        Value::Boolean(b) => serde_json::Value::Bool(*b.value()),
        Value::Datetime(d) => serde_json::Value::String(d.value().to_string()),
        Value::Array(a) => serde_json::Value::Array(a.iter().map(value_to_json).collect()),
        Value::InlineTable(t) => {
            let mut map = serde_json::Map::new();
            for (key, value) in t.iter() {
                map.insert(key.to_string(), value_to_json(value));
            }
            serde_json::Value::Object(map)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{comment_line_count, load_real, seg, REAL};

    #[test]
    fn parse_real_config() {
        let (doc, _) = load_real();
        let fields = doc.leaf_fields();
        assert_eq!(fields.len(), 162, "叶子键数必须是 162");
        // 非 ASCII 键（seg 是各测试模块共用的 helper：Vec<&str> -> Vec<String>）
        assert!(fields
            .iter()
            .any(|f| f.segments == seg(&["client", "多音字"])));
        // 含点的表键必须是 4 段
        assert!(fields.iter().any(|f| f.segments
            == seg(&["client", "additional_special_apps", "vlc.exe", "hotkey"])));
    }

    #[test]
    fn byte_identical_roundtrip() {
        let (doc, raw) = load_real();
        assert_eq!(doc.to_toml_string(), raw);
    }

    #[test]
    fn crlf_preserved() {
        let (doc, raw) = load_real();
        let out = doc.to_toml_string();
        // 三重条件，缺一不可（单看「CRLF 数 == LF 数」几乎恒真，抓不住「忘了归一化」）：
        // ① 不得叠成 \r\r\n（忘了 parse 端归一化的典型症状）
        assert!(!out.contains("\r\r\n"), "CRLF 还原不得叠成 \\r\\r\\n");
        // ② CRLF 数量必须与输入一致
        assert_eq!(out.matches("\r\n").count(), raw.matches("\r\n").count());
        // ③ 去掉合法 CRLF 后不得残留任何裸 CR / 裸 LF
        let stripped = out.replace("\r\n", "");
        assert!(
            !stripped.contains('\r') && !stripped.contains('\n'),
            "不得出现裸 LF / 裸 CR"
        );
    }

    #[test]
    fn lf_input_stays_lf() {
        // 若某台机器 core.autocrlf=false（工作树是 LF），保存不得把全文改成 CRLF
        let raw = std::fs::read_to_string(REAL).unwrap();
        let lf = raw.replace("\r\n", "\n");
        let doc = ConfigDoc::parse(&lf).unwrap();
        assert_eq!(doc.eol(), Eol::Lf);
        let out = doc.to_toml_string();
        assert_eq!(out, lf, "LF 输入必须 LF 输出，否则一次保存会改掉全文行尾");
        assert!(!out.contains('\r'));
    }

    #[test]
    fn empty_document_has_lf_and_parses() {
        let doc = ConfigDoc::parse("").unwrap();
        assert_eq!(doc.eol(), Eol::Lf);
        assert_eq!(doc.to_toml_string(), "");
        assert!(doc.leaf_fields().is_empty());
    }

    #[test]
    fn comment_lines_preserved() {
        let (doc, raw) = load_real();
        assert_eq!(
            comment_line_count(&doc.to_toml_string()),
            comment_line_count(&raw)
        );
        assert_eq!(
            comment_line_count(&raw),
            306,
            "基准：真实 config.toml 有 306 行整行注释"
        );
    }

    #[test]
    fn toml_type_reported() {
        let (doc, _) = load_real();
        let t = |s: &[&str]| doc.toml_type_at(&seg(s));
        assert_eq!(
            t(&["server", "speech_recognition_port"]),
            Some(TomlType::String)
        );
        assert_eq!(t(&["client", "audio_name_len"]), Some(TomlType::Integer));
        assert_eq!(t(&["client", "threshold"]), Some(TomlType::Float));
        assert_eq!(t(&["client", "hold_mode"]), Some(TomlType::Boolean));
        assert_eq!(t(&["client", "enter_apps"]), Some(TomlType::Array));
        assert_eq!(
            t(&["client", "additional_special_apps", "vlc.exe"]),
            Some(TomlType::InlineTable)
        );
    }

    #[test]
    fn toml_type_deep_inline_member() {
        // 动态表条目内部字段也要能判类型（"vlc.exe" 里的点不是分隔符）
        let (doc, _) = load_real();
        let t = |s: &[&str]| doc.toml_type_at(&seg(s));
        assert_eq!(
            t(&["client", "additional_special_apps", "vlc.exe", "hotkey"]),
            Some(TomlType::String)
        );
        assert_eq!(
            t(&["client", "additional_special_apps", "vlc.exe", "name"]),
            Some(TomlType::String)
        );
        // 不存在的键必须返回 None，不能误命中邻居
        assert_eq!(
            t(&["client", "additional_special_apps", "vlc.exe", "no_such_field"]),
            None
        );
        assert_eq!(
            t(&["client", "additional_special_apps", "no_such_app.exe", "hotkey"]),
            None
        );
        // 表本身不是可编辑值
        assert_eq!(t(&["client", "prompt_style"]), None);
    }

    #[test]
    fn get_and_toml_type_are_asymmetric_by_design() {
        // 锁死这个不对称，防止后人「顺手修好」→ 改坏 patch 的定位逻辑。
        let (doc, _) = load_real();
        let row = seg(&["client", "additional_special_apps", "vlc.exe"]);
        let member = seg(&["client", "additional_special_apps", "vlc.exe", "hotkey"]);
        // 内联表自身：两者都能拿到
        assert!(doc.get(&row).is_some());
        assert_eq!(doc.toml_type_at(&row), Some(TomlType::InlineTable));
        // 内联表成员：get 拿不到（&Value 借不出 &Item），toml_type_at 拿得到
        assert!(doc.get(&member).is_none());
        assert_eq!(doc.toml_type_at(&member), Some(TomlType::String));
    }

    #[test]
    fn parse_sets_no_path() {
        // parse 出来的文档没有路径；只有 load 会填。DocState 必须用 load。
        let (doc, _) = load_real();
        assert_eq!(doc.path(), std::path::Path::new(""));
    }

    #[test]
    fn fixture_roundtrip_is_byte_identical() {
        // 让 fixture 真正被用起来：它是 Task 3+ 各测试的最小输入
        let raw = std::fs::read_to_string("tests/fixtures/config_fixture.toml").unwrap();
        let doc = ConfigDoc::parse(&raw).unwrap();
        assert_eq!(doc.to_toml_string(), raw, "fixture 必须字节级往返");
        assert_eq!(doc.leaf_fields().len(), 14, "fixture 有 14 个叶子");
    }
}
