//! 各模块必须 `pub`：`tests/coverage.rs` 是独立 crate，只能走 `edit_config_gui_lib::…` 访问。
//! 写成私有会报 `error[E0603]: module is private`，且顺带多出几百条 dead_code 警告。
pub mod commands;
pub mod config_doc;
pub mod file_io;
pub mod hotkey;
pub mod model_paths_resolve;
pub mod patch;
pub mod process;
pub mod validate;

#[cfg(test)]
pub mod testutil;

/// Tauri 应用入口：装配插件、登记命令并运行。
///
/// `generate_handler!` 是命令的**注册表**，不是派生宏：`#[tauri::command]` 只生成包装函数，
/// 没写进这里的命令前端 invoke 时会直接报 "command not found"，而 Rust 侧连警告都没有。
/// 所以七个命令必须与 `AppState` 的 manage 注册保持一致。
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::AppState {
            session: std::sync::Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            commands::open_config,
            commands::pick_path,
            commands::preview_save,
            commands::commit_save,
            commands::reload_config,
            commands::running_processes,
            commands::restart_service
        ])
        .run(tauri::generate_context!())
        .expect("运行 Tauri 应用失败");
}
