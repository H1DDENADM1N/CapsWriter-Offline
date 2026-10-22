//! schema ↔ 真实配置文件的闭合断言。
//!
//! `schema_paths.json` 由 `edit_config_gui/scripts/gen-schema-paths.mjs` 从前端
//! schema 生成（170→见脚本头），前端侧的 `coverage.test.ts` 保证 schema 与 JSON
//! 同步。这个测试负责链条的另一半：**JSON 与仓库里真实的 config.toml 同步**。
//!
//! 只用 `configs/default config.toml` 而不是根目录的 `config.toml`：前者是出厂
//! 模板，188 个键齐全且不会被用户改坏；后者在某些机器上会被 debug 模板覆盖
//! （`logger_level` 不同）。

use std::collections::BTreeSet;
use std::path::PathBuf;

use edit_config_gui_lib::config_doc::ConfigDoc;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// 动态表 `client.additional_special_apps` 的条目：`…,"vlc.exe","hotkey"` 这种
/// 4 段路径。它不属于固定 schema（用户可增删任意条），所以要从两边都排除掉。
fn is_dynamic_table_entry(segments: &[String]) -> bool {
    segments.len() == 4 && segments[0] == "client" && segments[1] == "additional_special_apps"
}

/// 派生只读键：值仍是 `${model_paths.…}` 占位符。
///
/// 仓库里没有任何代码解析这种占位符（`util/config.py:249-308` 直接读
/// `model_paths` 段），所以这 16 个键改了不生效 —— UI 把它们显示成只读视图，
/// 也就不该出现在「可编辑键」清单里。
fn is_derived_placeholder(field: &edit_config_gui_lib::config_doc::FieldEntry) -> bool {
    field
        .value
        .as_str()
        .map(|s| s.starts_with("${model_paths."))
        .unwrap_or(false)
}

fn key(segments: &[String]) -> String {
    segments.join("\u{0}")
}

fn load_schema_paths() -> Vec<Vec<String>> {
    let path = manifest_dir().join("tests").join("schema_paths.json");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("读不到 {}：{e}", path.display()));
    serde_json::from_str(&text).expect("schema_paths.json 不是 [[string]]")
}

fn load_template_leaves() -> Vec<Vec<String>> {
    let path = manifest_dir()
        .join("..")
        .join("..")
        .join("configs")
        .join("default config.toml");
    let doc = ConfigDoc::load(&path)
        .unwrap_or_else(|e| panic!("读不到 {}：{e}", path.display()));
    doc.leaf_fields()
        .into_iter()
        .filter(|f| !is_dynamic_table_entry(&f.segments))
        .filter(|f| !is_derived_placeholder(f))
        .map(|f| f.segments)
        .collect()
}

#[test]
fn schema_paths_cover_every_leaf_of_the_shipped_template() {
    let schema: BTreeSet<String> = load_schema_paths().iter().map(|s| key(s)).collect();
    let template: BTreeSet<String> = load_template_leaves().iter().map(|s| key(s)).collect();

    // 先报「具体哪几个键对不上」，再报数量 —— 否则少一个键时只会看到
    // 「150 ≠ 151」，还得自己二分去找是哪一条
    let missing: Vec<String> = template.difference(&schema).cloned().collect();
    let extra: Vec<String> = schema.difference(&template).cloned().collect();

    assert!(
        missing.is_empty(),
        "模板里有、schema 里没有的键（UI 里会看不到）：{:?}",
        missing.iter().map(|k| k.replace('\u{0}', ".")).collect::<Vec<_>>()
    );
    assert!(
        extra.is_empty(),
        "schema 里有、模板里没有的键（会写坏配置）：{:?}",
        extra.iter().map(|k| k.replace('\u{0}', ".")).collect::<Vec<_>>()
    );

    // 170 = 188 个叶子 − 2 条动态表条目 − 16 个派生只读键
    assert_eq!(schema.len(), 170, "schema_paths.json 应恰好 170 条");
}

#[test]
fn template_leaf_count_matches_the_documented_188() {
    // 这个数字是整份规格的基准（188 个叶子键）。它变了就意味着有人动了
    // config.toml 的结构，那么规格 §3.1、计划里的 175/170/186 全要重算。
    let path = manifest_dir()
        .join("..")
        .join("..")
        .join("configs")
        .join("default config.toml");
    let doc = ConfigDoc::load(&path).expect("读模板失败");
    let all = doc.leaf_fields();
    assert_eq!(all.len(), 188, "configs/default config.toml 应恰好 188 个叶子键");

    let dynamic = all.iter().filter(|f| is_dynamic_table_entry(&f.segments)).count();
    assert_eq!(dynamic, 2, "动态表应贡献 2 条（vlc.exe 的 hotkey 与 name）");

    // 16 个派生只读键：值仍是 ${model_paths.…} 占位符
    let placeholders = all
        .iter()
        .filter(|f| {
            f.value
                .as_str()
                .map(|s| s.starts_with("${model_paths."))
                .unwrap_or(false)
        })
        .count();
    assert_eq!(placeholders, 16, "应有 16 个 ${{model_paths.…}} 占位符键");

    assert_eq!(all.len() - dynamic - placeholders, 170);
}
