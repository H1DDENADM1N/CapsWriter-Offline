#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // 提权助手模式：带上 --elevated-restart 时，在进入 Tauri 之前就完成「结束 + 拉起」并
    // 退出。放在最前面是必须的——助手绝不能弹出任何窗口，也不能初始化 GUI 运行时。
    if let Some(code) = edit_config_gui_lib::elevate::run_if_requested() {
        std::process::exit(code);
    }

    edit_config_gui_lib::run()
}
