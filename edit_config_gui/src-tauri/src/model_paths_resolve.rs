//! 13 个派生只读键的只读解析（规格 §6.5）。
//!
//! `config.toml` 里这 13 个键的值是 `${model_paths.xxx}` 形式的占位符，
//! 而真正被业务代码读取的是 `model_paths` 段的对应键（`util/config.py`
//! 的 `FunASRArgs` / `SenseVoiceArgs` / `ParaformerArgs` / `QwenCTCArgs`
//! 全部直接读 `config["model_paths"][...]`）。也就是说占位符从来没有被任何人解析过。
//!
//! 本模块只做「展示用」的解析：界面上给只读字段显示「实际生效：…」，
//! 并提供一个跳到 `model_paths` 的链接。
//!
//! **刻意不提供写入 / 同步函数。** TOML 里这 13 个键保持原样，保存时既不删除
//! 也不改写。一旦出现「把占位符替换成真实路径」的入口，配置文件就会分叉成
//! 「有的机器是占位符、有的机器是绝对路径」，那正是这次重构要消灭的旧问题。

use crate::config_doc::ConfigDoc;

/// (派生键 segments, 真实来源键 segments)
pub const DERIVED: [(&[&str], &[&str]); 13] = [
    (
        &["funasr_args", "encoder_onnx_path"],
        &["model_paths", "funasr_encoder_adaptor_path"],
    ),
    (
        &["funasr_args", "ctc_onnx_path"],
        &["model_paths", "funasr_ctc_path"],
    ),
    (
        &["funasr_args", "decoder_gguf_path"],
        &["model_paths", "funasr_llm_path"],
    ),
    (
        &["funasr_args", "tokens_path"],
        &["model_paths", "funasr_tokens_path"],
    ),
    (
        &["funasr_args", "hotwords_path"],
        &["model_paths", "funasr_hotwords_path"],
    ),
    (
        &["sensevoice_args", "model"],
        &["model_paths", "sensevoice_path"],
    ),
    (
        &["sensevoice_args", "tokens"],
        &["model_paths", "sensevoice_tokens_path"],
    ),
    (
        &["paraformer_args", "paraformer"],
        &["model_paths", "paraformer_path"],
    ),
    (
        &["paraformer_args", "tokens"],
        &["model_paths", "paraformer_tokens_path"],
    ),
    (
        &["qwen_ctc_args", "encoder_onnx_path"],
        &["model_paths", "qwen_ctc_encoder_path"],
    ),
    (
        &["qwen_ctc_args", "ctc_onnx_path"],
        &["model_paths", "qwen_ctc_ctc_path"],
    ),
    (
        &["qwen_ctc_args", "tokens_path"],
        &["model_paths", "qwen_ctc_tokens_path"],
    ),
    (
        &["qwen_ctc_args", "preprocessor_path"],
        &["model_paths", "qwen_ctc_preprocessor_path"],
    ),
];

/// 派生键当前「应当」显示的值；来源键缺失时返回 `None`。
///
/// 用户可能手工删掉 `model_paths` 里的某个键，所以这里一路 `?`，绝不 `unwrap`。
pub fn resolve(doc: &ConfigDoc, derived: &[String]) -> Option<String> {
    let (_, source) = DERIVED
        .iter()
        .find(|(d, _)| d.iter().map(|s| s.to_string()).collect::<Vec<_>>() == derived)?;
    let source: Vec<String> = source.iter().map(|s| s.to_string()).collect();
    doc.get(&source)?.as_str().map(|s| s.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{comment_line_count, load_real};

    fn to_vec(parts: &[&str]) -> Vec<String> {
        parts.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn resolve_all_thirteen() {
        let (doc, _) = load_real();
        for (derived, source) in DERIVED {
            let expect = doc
                .get(&to_vec(source))
                .and_then(|i| i.as_str())
                .unwrap()
                .to_string();
            assert_eq!(resolve(&doc, &to_vec(derived)).unwrap(), expect, "{derived:?}");
        }
    }

    #[test]
    fn read_only_resolve_does_not_touch_text() {
        // 解析派生键是纯读操作：不得改写 Item、不得影响 emit 出来的文本
        let (doc, raw) = load_real();
        let before = doc.to_toml_string();
        for (derived, _) in DERIVED {
            let _ = resolve(&doc, &to_vec(derived));
        }
        assert_eq!(doc.to_toml_string(), before, "resolve 不得改动文档");
        assert_eq!(comment_line_count(&raw), 333);
    }

    #[test]
    fn all_thirteen_are_placeholders_in_toml() {
        // 13 个派生键在 TOML 里必须仍是 ${...} 占位符；若哪天被同步成真实路径，
        // 说明有人加了写入入口 —— 那是配置文件分叉，必须在这里红掉
        let (doc, _) = load_real();
        for (derived, _) in DERIVED {
            let got = doc.get(&to_vec(derived)).and_then(|i| i.as_str()).unwrap();
            assert!(got.starts_with("${model_paths."), "{derived:?} = {got}");
        }
    }

    #[test]
    fn resolve_missing_source_returns_none() {
        // 用户手工删掉来源键时不得 panic
        let mut doc = ConfigDoc::parse("x = 1\n").unwrap();
        assert_eq!(resolve(&doc, &to_vec(&["funasr_args", "tokens_path"])), None);
        doc.doc_mut()
            .as_table_mut()
            .insert("model_paths", toml_edit::Item::Table(Default::default()));
        assert_eq!(resolve(&doc, &to_vec(&["funasr_args", "tokens_path"])), None);
    }

    #[test]
    fn resolve_unknown_key_returns_none() {
        let (doc, _) = load_real();
        assert_eq!(resolve(&doc, &to_vec(&["server", "addr"])), None);
    }
}
