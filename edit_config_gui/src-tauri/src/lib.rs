//! 各模块必须 `pub`：`tests/coverage.rs` 是独立 crate，只能走 `edit_config_gui_lib::…` 访问。
//! 写成私有会报 `error[E0603]: module is private`，且顺带多出几百条 dead_code 警告。
pub mod config_doc;
pub mod hotkey;
pub mod model_paths_resolve;
pub mod patch;
pub mod validate;

#[cfg(test)]
pub mod testutil;

/// Tauri 应用入口：装配插件并运行。
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
