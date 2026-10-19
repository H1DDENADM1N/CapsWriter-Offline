//! Windows 当前外观：深浅色 + 主题色种子。
//!
//! 前端不靠 `prefers-color-scheme` 判断深浅色：那个媒体查询跟随的是 WebView2
//! 自己的主题来源，在 Tauri 里并不保证等于「设置 → 个性化 → 颜色 → 应用模式」；
//! 这里直接读注册表，前端拿到的是和系统设置同一份事实。
//!
//! 主题色只给「候选」而不是一个定值，原因见 `assemble`：两处来源各自都不总是
//! 可信，挑选逻辑放在前端（有 HCT 彩度可用，也好写测试）。

use serde::Serialize;

/// 两处注册表都读不到（或读到的都不像主题色）时前端用的种子：Windows 默认蓝。
pub const FALLBACK_ACCENT: &str = "#0078d4";

/// 系统设置里「应用模式」是深色时 `AppsUseLightTheme` 为 0。
const DARK_FLAG: u32 = 0;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SystemAppearance {
    /// 深色模式。
    pub dark: bool,
    /// 候选种子色（`#rrggbb`），前面的比后面的更接近系统当前外观。
    pub accents: Vec<String>,
}

/// `0xAARRGGBB` → `#rrggbb`。DWM 的 `ColorizationColor` 就是这个打包方式。
pub fn argb_to_hex(argb: u32) -> String {
    format!(
        "#{:02x}{:02x}{:02x}",
        (argb >> 16) & 0xff,
        (argb >> 8) & 0xff,
        argb & 0xff
    )
}

/// `"0 120 212"` → `Some("#0078d4")`。
///
/// `HKCU\Control Panel\Colors` 里的颜色是空格分隔的十进制三元组。多一个分量、
/// 少一个分量、出现非数字或越界，都当读不到 —— 宁可回退到默认蓝，也不要把
/// 一个错误解析出来的颜色拿去生成整套配色。
pub fn rgb_triplet_to_hex(text: &str) -> Option<String> {
    let mut parts = text.split_whitespace();
    let mut rgb = [0u8; 3];
    for slot in &mut rgb {
        *slot = parts.next()?.parse().ok()?;
    }
    if parts.next().is_some() {
        return None;
    }
    Some(format!("#{:02x}{:02x}{:02x}", rgb[0], rgb[1], rgb[2]))
}

/// 把两处读到的原始值拼成回复给前端的结构。
///
/// * `colorization` —— DWM 给窗口边框上的色。用户手动选了主题色时它就是那个
///   颜色；但如果开着「自动从背景取色」，它可能是从壁纸混出来的、接近黑的深色，
///   拿它当种子会得到一整套灰调配色。所以它只算「候选」，由前端的彩度判断淘汰。
/// * `hilight` —— 系统强调/选中色，始终存在，且在自动取色时通常仍是可辨识的
///   那一支。
pub fn assemble(
    apps_use_light_theme: Option<u32>,
    colorization: Option<u32>,
    hilight: Option<String>,
) -> SystemAppearance {
    let dark = apps_use_light_theme == Some(DARK_FLAG);

    let mut accents: Vec<String> = Vec::new();
    if let Some(argb) = colorization {
        // 0 是「没设置过」，不是黑色
        if argb != 0 {
            accents.push(argb_to_hex(argb));
        }
    }
    if let Some(hex) = hilight.as_deref().and_then(rgb_triplet_to_hex) {
        accents.push(hex);
    }
    accents.dedup();
    if accents.is_empty() {
        accents.push(FALLBACK_ACCENT.to_string());
    }

    SystemAppearance { dark, accents }
}

/// 读一个 DWORD 值。读不到返回 `None`（键不存在、类型不对、无权限都算）。
#[cfg(windows)]
fn read_dword(subkey: &str, name: &str) -> Option<u32> {
    use std::ffi::c_void;
    use windows_sys::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD};

    let subkey: Vec<u16> = subkey.encode_utf16().chain(Some(0)).collect();
    let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    let mut data: u32 = 0;
    let mut size = std::mem::size_of::<u32>() as u32;
    // SAFETY: 两个字符串都以 NUL 结尾且在本函数内一直存活；`data`/`size`
    // 指向栈上合法的 u32，`RRF_RT_REG_DWORD` 让系统只写 4 个字节。
    let rc = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            subkey.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_DWORD,
            std::ptr::null_mut(),
            &mut data as *mut u32 as *mut c_void,
            &mut size,
        )
    };
    (rc == 0).then_some(data)
}

/// 读一个字符串值（`REG_SZ`）。只用来读 `"0 120 212"` 这种短三元组。
#[cfg(windows)]
fn read_string(subkey: &str, name: &str) -> Option<String> {
    use std::ffi::c_void;
    use windows_sys::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_SZ};

    let subkey: Vec<u16> = subkey.encode_utf16().chain(Some(0)).collect();
    let name: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    let mut buf = [0u16; 64];
    let mut size = (buf.len() * std::mem::size_of::<u16>()) as u32;
    // SAFETY: 同上；`buf` 是 128 字节的栈缓冲区，`size` 声明了它的字节数。
    let rc = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            subkey.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_SZ,
            std::ptr::null_mut(),
            buf.as_mut_ptr() as *mut c_void,
            &mut size,
        )
    };
    if rc != 0 {
        return None;
    }
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    Some(String::from_utf16_lossy(&buf[..end]))
}

/// 读当前系统外观。读不到的项按「浅色 + 默认蓝」兜底。
#[cfg(windows)]
pub fn appearance() -> SystemAppearance {
    const PERSONALIZE: &str =
        "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize";
    const DWM: &str = "Software\\Microsoft\\Windows\\DWM";
    const COLORS: &str = "Control Panel\\Colors";

    assemble(
        read_dword(PERSONALIZE, "AppsUseLightTheme"),
        read_dword(DWM, "ColorizationColor"),
        read_string(COLORS, "Hilight"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn argb_dword_drops_alpha_and_keeps_channel_order() {
        // 0xC4 是 DWM 常见的 alpha，不能漏进颜色里；R/G/B 顺序不能反
        assert_eq!(argb_to_hex(0xC4_00_78_d4), "#0078d4");
        assert_eq!(argb_to_hex(0xFF_ff_00_00), "#ff0000");
        assert_eq!(argb_to_hex(0), "#000000");
    }

    #[test]
    fn rgb_triplet_parses_control_panel_colors() {
        assert_eq!(rgb_triplet_to_hex("0 120 212"), Some("#0078d4".to_string()));
        assert_eq!(rgb_triplet_to_hex("255 255 255"), Some("#ffffff".to_string()));
        // 前后多余空白不该影响
        assert_eq!(rgb_triplet_to_hex(" 0  120 212 "), Some("#0078d4".to_string()));
    }

    #[test]
    fn rgb_triplet_rejects_shapes_it_cannot_trust() {
        assert_eq!(rgb_triplet_to_hex(""), None);
        assert_eq!(rgb_triplet_to_hex("0 120"), None);
        assert_eq!(rgb_triplet_to_hex("0 120 212 44"), None);
        assert_eq!(rgb_triplet_to_hex("0 120 256"), None); // 越界
        assert_eq!(rgb_triplet_to_hex("0 120 x"), None);
    }

    #[test]
    fn light_theme_flag_is_read_backwards() {
        // AppsUseLightTheme: 1 = 浅色，0 = 深色，缺失 = 浅色
        assert!(!assemble(Some(1), None, None).dark);
        assert!(assemble(Some(0), None, None).dark);
        assert!(!assemble(None, None, None).dark);
    }

    #[test]
    fn accents_prefer_colorization_then_hilight() {
        let a = assemble(Some(0), Some(0xC4_12_34_56), Some("9 9 9".into()));
        assert_eq!(a.accents, vec!["#123456".to_string(), "#090909".to_string()]);
    }

    #[test]
    fn null_colorization_is_skipped_not_black() {
        let a = assemble(Some(1), Some(0), Some("0 120 212".into()));
        assert_eq!(a.accents, vec!["#0078d4".to_string()]);
    }

    #[test]
    fn unreadable_everything_falls_back_to_windows_blue() {
        assert_eq!(
            assemble(None, None, None).accents,
            vec![FALLBACK_ACCENT.to_string()]
        );
        // 三元组解析失败也不能让候选列表变空
        assert_eq!(
            assemble(None, None, Some("not a color".into())).accents,
            vec![FALLBACK_ACCENT.to_string()]
        );
    }

    #[test]
    fn duplicate_sources_yield_one_candidate() {
        let a = assemble(Some(1), Some(0xC4_00_78_d4), Some("0 120 212".into()));
        assert_eq!(a.accents, vec!["#0078d4".to_string()]);
    }
}
