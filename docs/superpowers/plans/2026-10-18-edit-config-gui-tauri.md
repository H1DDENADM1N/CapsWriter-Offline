# 配置编辑器重构（Tauri 2 + Svelte 5）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Tauri 2 + Svelte 5 重写 `edit_config_gui`，覆盖 `config.toml` 全部 162 个叶子键，在保留注释、键顺序、CRLF 与值类型的前提下提供更安全（预览 diff + 原子写入 + 冲突检测）和更便捷（命令面板搜索 + 声明式显隐 + 快捷键录制）的配置编辑体验，并删除旧的 PySide6 + siui 实现。

**Architecture:** 前端只提供元数据（162 个 `FieldMeta`）与纯 UI 状态，不含任何文件能力；所有 TOML 解析、补丁应用、校验、备份与原子替换都在 Rust 侧完成。保存分两步：`preview_save` 在内存副本上应用补丁并返回真实 unified diff，`commit_save` 用同一批补丁重新校验后走「写 `.tmp` → `ReplaceFileW`（同时生成 `.bak`）→ 回读解析」的原子链。路径一律用 `segments: string[]` 定位，避免 `vlc.exe` 这类含点键名产生歧义。

**Tech Stack:** Tauri 2.12.4 / toml_edit 0.22.27 / windows-sys 0.59.0 / similar 3.2.0 / sha2 0.10.9 / sysinfo 0.39.6 ｜ Svelte 5.57.2（runes）/ Vite 8.3.4 / Vitest 5.0.5 / TypeScript 5.9.3 / pnpm 12.11.2

**Spec:** `docs/superpowers/specs/2026-10-18-edit-config-gui-tauri-design.md`

## Global Constraints

- 目标平台 **Windows 10+ x64**。所有 Windows API 调用通过 `windows-sys 0.59`，不得引入 `winapi` 或手写 `extern "system"`。
- 工具链下限：`rustc >= 1.77.2`（本机实测 1.99.1，位于 `%USERPROFILE%\.cargo\bin`，PATH 里没有，需手动前置）、`node >= 20.19`（实测 24.21.0）、`pnpm >= 9`（实测 12.11.2）。
- **不允许**向 `config.toml` 引入任何新键、删除任何键、重排键序或改写既有注释。基准：852 个 CRLF 行、306 行整行注释、162 个叶子键、无 BOM、文件末尾有 CRLF。
- 运行 `toml_edit` 前**必须** `raw.replace("\r\n", "\n")`，输出后**必须** `.replace('\n', "\r\n")`。直接 parse CRLF 会产生混合换行（实测 852 CRLF → 199 CRLF + 653 裸 LF）。
- 一对一替换动态表条目时必须**先搬运 decor**（`prefix`/`suffix`），否则行尾注释丢失。
- 禁止 `Table::clear()` + 重建动态表；禁止用 `std::fs::rename` 做替换（会覆盖目标 ACL）。
- `ReplaceFileW` 的 `lpBackupFileName` 跳过备份时传 `std::ptr::null()`，**不能**传 `""`（返回 0 / `ERROR_PATH_NOT_FOUND`）。
- `capabilities/default.json` 只含 `core:default`；**不授予** `fs:*`、`shell:*`、`process:*`。文件对话框从 **Rust 侧**调用（不经 IPC，因此不需要 `dialog:*` 权限）。
- `restart_service` 的参数只能是 `ServiceTarget::{Server, Client}` 枚举，exe 路径由 Rust 白名单解析，前端无法传入任意路径。
- 前端 `dependencies` 里**不得**出现 `pinyin-pro`（只在 `devDependencies`，且仅用于构建期生成 `pinyin-map.json`）。
- 所有跨语言路径一律 `segments: string[]`，禁止点分字符串（`client.additional_special_apps."vlc.exe".hotkey` 会被错误切分）。
- 界面全中文，文案与 `config.toml` 注释保持一致。
- 提交信息用中文、动词开头；多行提交信息必须走 `git commit -F <file>`（PowerShell 会把消息里的中文引号当路径）。
- 版本锁定（已在本机实测编译/运行通过，不得随意升级）：前端 `svelte 5.57.2`、`vite 8.3.4`、`@sveltejs/vite-plugin-svelte 7.3.1`、`vitest 5.0.5`、`jsdom 30.1.3`、`typescript 5.9.3`、`svelte-check 4.7.7`、`@tauri-apps/cli 2.12.3`、`@tauri-apps/api 2.12.4`、`pinyin-pro 3.29.5`；Rust `tauri 2`、`tauri-plugin-dialog 2`、`toml_edit 0.22`、`similar 3`、`sha2 0.10`、`sysinfo 0.39`、`windows-sys 0.59`。

### 测试代码约定（每个 Rust 任务都适用）

计划里各任务的测试片段只展示**测试体**，不是完整文件。每个模块的 `#[cfg(test)] mod tests` 顶部统一这样导入，后续片段里的 `seg` / `patch` / `load_real` / `comment_line_count` / `comment_multiset` / `tmpdir` / `seed` / `REAL` 全部来自 `crate::testutil`（Task 2 Step 0 建立）：

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::{
        seg, patch, load_real, comment_line_count, comment_multiset, tmpdir, seed, REAL,
    };
    use crate::config_doc::{ConfigDoc, TomlType};
    use crate::patch::PatchValue;
    // ...测试体
}
```

- 同一个测试模块内用不到的导入会产生 `unused import` 警告；按需删减即可，但**不得**改掉 `seg`（禁止点分字符串）与 `load_real`（读真实 `config.toml`）这两个核心辅助的用法。
- 所有 Rust 单测都必须能离线跑（不联网、不依赖键盘/浏览器），只读仓库内的 `config.toml` 与 `tests/fixtures/`。
- 前端单测统一放 `edit_config_gui/src/**/*.test.ts`，用 `vitest` + `@testing-library/svelte`，不得引入快照测试（Svelte 5 快照易脆）。

## Review Focus

规格是愿景文档，它没提到的输入不代表可以让程序坏掉。以下 5 类最可能被真实用户撞到、且规格没给现成断言，每条都在所属任务里有对应测试：

1. **`config.toml` 在编辑器打开后被外部改动**（另一个编辑器、`config_selector.exe` 切换配置、或用户自己在 VSCode 保存）——用户点保存时不得静默覆盖外部改动，必须报冲突并让用户选「重新加载」或「强制覆盖」。测试落在 Task 6（`fingerprint_changes_on_external_write`、`commit_conflict_does_not_touch_file`）。
2. **用户手工把数值键改成超范围或非数值后再打开编辑器**（如 `client.mic_seg_duration = 120`、`client.threshold = "abc"`）——界面必须能打开、其它字段仍可编辑保存，而不是启动即崩或保存被永久拦住。测试落在 Task 3（`tolerant_load_of_out_of_range_int`）与 Task 13（`int 字段接受超范围既有值`）与 Task 14（`int 控件首次渲染不改写超范围既有值`）。
3. **提示词（多行）里粘进 `"""`、裸 `\`、`#` 或制表符**——写回后 `config.toml` 必须仍可被 `toml_edit` 重新解析，且后续字段不被打乱。测试落在 Task 3（`multiline_quote_and_backslash_roundtrip`）。
4. **动态表新增的进程名含引号、点、空格或中文**（如 `my app.exe`、`a"b.exe`）——写回时必须被正确加引号成合法 TOML；否则一次保存就写出一个打不开的文件。测试落在 Task 3（`dynamic_table_weird_key_quoted`）。
5. **保存过程中进程被杀 / 断电**——`config.toml` 不得出现半截内容，`.bak` 必须可恢复。测试落在 Task 6（`tmp_left_over_does_not_corrupt_target`、`rollback_from_bak`）。

---

## 文件结构

新增目录 `edit_config_gui/`（与旧 `edit_config_gui.py` 并存直到 Task 21 删除它）。

```
edit_config_gui/
├── package.json                        # 前端依赖 + pnpm 脚本（dev/build/test/check/build:dist）
├── pnpm-lock.yaml
├── vite.config.ts                      # Vite + svelte 插件 + vitest 配置
├── svelte.config.js                    # vitePreprocess
├── tsconfig.json
├── index.html
├── README.md                           # 开发者构建说明（Task 21）
├── scripts/
│   ├── copy-dist.mjs                   # 把 src-tauri/target/release/edit_config_gui.exe 拷到仓库根
│   ├── export_hotkey_tables.py         # 从 .venv 的 keyboard 包导出两张键名表
│   ├── gen_hotkey_fixtures.py          # 生成 841 例对拍集
│   ├── gen-pinyin-map.mjs              # 构建期生成 pinyin-map.json
│   └── gen-schema-paths.mjs            # 构建期生成 schema_paths.json（供 Rust 覆盖测试）
├── src/
│   ├── main.ts
│   ├── App.svelte
│   ├── app.css
│   ├── bridge.ts                       # 唯一 invoke() 封装点
│   └── lib/
│       ├── schema/
│       │   ├── types.ts
│       │   ├── server.ts               # debug + server
│       │   ├── client.ts               # client 主表 72 键
│       │   ├── aiProviders.ts          # client.zhipuai + client.openai
│       │   ├── promptStyles.ts         # client.prompt_style 16 键
│       │   ├── additionalApps.ts       # client.additional_special_apps 动态表
│       │   ├── translate.ts            # libretranslate + deeplx
│       │   ├── modelPaths.ts           # model_paths 13 键
│       │   ├── modelArgs.ts            # funasr_args / sensevoice_args / paraformer_args
│       │   ├── index.ts                # 汇总、按页分组、扁平化 fieldId、派生只读字段
│       │   └── coverage.test.ts        # schema ↔ schema_paths.json 断言
│       ├── search.ts                   # 纯函数搜索索引与打分
│       ├── search.test.ts
│       ├── pinyin.ts
│       ├── pinyin.test.ts              # pinyin-map ↔ schema 同步断言
│       ├── pinyin-map.json             # 构建期生成
│       ├── components/
│       │   ├── Sidebar.svelte
│       │   ├── nav.test.ts             # Sidebar + navStore 测试
│       │   ├── CommandPalette.svelte
│       │   ├── palette.test.ts         # 命令面板键盘交互测试
│       │   ├── Section.svelte
│       │   ├── Field.svelte
│       │   ├── Field.test.ts           # 显隐 / 错误态 / 脏标记测试
│       │   ├── DirtyBar.svelte
│       │   ├── DiffDialog.svelte
│       │   ├── save.test.ts            # 保存状态机测试
│       │   ├── StatusBar.svelte        # 进程状态 + 重启按钮
│       │   ├── status.test.ts          # 状态栏与引导态测试
│       │   ├── Onboarding.svelte       # 未找到 config.toml 引导态
│       │   ├── pages/
│       │   │   └── PageView.svelte     # 单页容器：按 Section 顺序渲染
│       │   └── widgets/                # 13 个控件
│       │       ├── index.ts            # widget 名 → 组件的查表
│       │       ├── TextWidget.svelte
│       │       ├── IntWidget.svelte
│       │       ├── FloatWidget.svelte
│       │       ├── BoolWidget.svelte
│       │       ├── EnumWidget.svelte
│       │       ├── PathWidget.svelte
│       │       ├── HotkeyWidget.svelte
│       │       ├── StringListWidget.svelte
│       │       ├── PairListWidget.svelte
│       │       ├── LongTextWidget.svelte
│       │       ├── SecretWidget.svelte
│       │       ├── ReadonlyWidget.svelte
│       │       ├── DynamicTableWidget.svelte
│       │       └── widgets.test.ts     # 各控件行为测试
│       └── stores/
│           ├── config.ts               # runes 状态：doc / values / dirty / errors / warnings / patches / rules
│           ├── config.test.ts
│           ├── save.ts                 # 保存流程状态机：idle→previewing→confirm→committing→done/conflict
│           ├── palette.ts              # 命令面板状态：open / query / selectedIndex / recent
│           ├── toast.ts                # 右下角提示队列（保存成功/失败/冲突）
│           └── nav.ts                  # 当前页 + 高亮目标（供 ReadonlyWidget 跳转与搜索结果定位）
└── src-tauri/
    ├── .gitignore                      # /target、/gen
    ├── Cargo.toml
    ├── build.rs
    ├── tauri.conf.json
    ├── capabilities/default.json
    ├── icons/icon.ico                  # 由 assets/icon/config-icon.ico 复制
    ├── tests/
    │   ├── schema_paths.json           # 由前端脚本生成并提交（160 条 segments，不含动态表条目）
    │   ├── coverage.rs                 # schema_paths.json ↔ configs/default config.toml
    │   └── fixtures/
    │       ├── config_fixture.toml     # 40 行左右最小样本：注释/多行字符串/数组/动态表/非 ASCII 键
    │       ├── hotkey_cases.txt        # 841 行
    │       └── hotkey_expected.txt     # 841 行（ok/err）
    └── src/
        ├── main.rs                     # 仅调 lib::run()
        ├── lib.rs                      # Builder 装配 + 单元测试入口
        ├── config_doc.rs               # 文档模型：归一化/解析/输出/叶子枚举
        ├── patch.rs                    # PatchValue / apply / diff
        ├── validate.rs                 # 10 个校验器 + 全量报告
        ├── hotkey.rs                   # 快捷键解析（等价 keyboard.parse_hotkey）
        ├── hotkey_names.json           # 205 项合法键名（脚本导出，提交）
        ├── canonical_names.json        # 1171 项别名表（脚本导出，提交）
        ├── model_paths_resolve.rs      # 9 个派生只读键的解析
        ├── file_io.rs                  # 指纹 / 原子提交 / 备份 / 回滚
        ├── process.rs                  # 运行检测 + 重启
        ├── commands.rs                 # 7 个 #[tauri::command]
        └── testutil.rs                 # 仅 #[cfg(test)]：seg/load_real/tmpdir/seed/patch 等共享辅助
```

职责边界：`config_doc.rs` 只读写 TOML 不校验；`validate.rs` 只校验不碰除「存在性」外的文件；`file_io.rs` 只做字节搬运不解析 TOML；`commands.rs` 只编排水线。

---

### Task 1: 项目骨架与构建链

**Files:**
- Create: `edit_config_gui/package.json`
- Create: `edit_config_gui/vite.config.ts`
- Create: `edit_config_gui/svelte.config.js`
- Create: `edit_config_gui/tsconfig.json`
- Create: `edit_config_gui/index.html`
- Create: `edit_config_gui/src/main.ts`
- Create: `edit_config_gui/src/App.svelte`
- Create: `edit_config_gui/src/app.css`
- Create: `edit_config_gui/src-tauri/Cargo.toml`
- Create: `edit_config_gui/src-tauri/build.rs`
- Create: `edit_config_gui/src-tauri/tauri.conf.json`
- Create: `edit_config_gui/src-tauri/capabilities/default.json`
- Create: `edit_config_gui/src-tauri/icons/icon.ico`（复制自 `assets/icon/config-icon.ico`）
- Create: `edit_config_gui/src-tauri/src/main.rs`
- Create: `edit_config_gui/src-tauri/src/lib.rs`
- Create: `edit_config_gui/src-tauri/.gitignore`

**Interfaces:**
- Consumes: 无
- Produces: `edit_config_gui_lib::run()`（`lib.rs` 导出，`main.rs` 调用）；`pnpm dev` / `pnpm build` / `pnpm test` / `pnpm check` 四个脚本可用；`cargo build` 与 `cargo test` 可用。

- [ ] **Step 1: 创建 `package.json`（版本必须与 Global Constraints 完全一致）**

```json
{
  "name": "edit_config_gui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run --passWithNoTests",
    "test:watch": "vitest",
    "check": "svelte-check --tsconfig ./tsconfig.json",
    "tauri": "tauri",
    "dev:tauri": "tauri dev",
    "build:tauri": "tauri build",
    "build:dist": "tauri build && node scripts/copy-dist.mjs"
  },
  "//": "build:dist 依赖的 scripts/copy-dist.mjs 在 Task 21 创建；Task 1 阶段只用 dev/build/test/check/build:tauri",
  "dependencies": {
    "@tauri-apps/api": "2.12.4"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "7.3.1",
    "@tauri-apps/cli": "2.12.3",
    "@testing-library/svelte": "5.4.2",
    "jsdom": "30.1.3",
    "pinyin-pro": "3.29.5",
    "svelte": "5.57.2",
    "svelte-check": "4.7.7",
    "typescript": "5.9.3",
    "vite": "8.3.4",
    "vitest": "5.0.5"
  }
}
```

- [ ] **Step 2: 创建 `vite.config.ts`、`svelte.config.js`、`tsconfig.json`、`index.html`**

`vite.config.ts`：

```ts
import { defineConfig } from 'vitest/config';   // 不是 'vite'：否则 test 字段过不了类型检查
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, watch: { ignored: ['**/src-tauri/**'] } },
  build: { target: 'chrome110', emptyOutDir: true, sourcemap: false },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
});
```

`svelte.config.js`：`export default { preprocess: vitePreprocess() }`（从 `@sveltejs/vite-plugin-svelte` 导入）。
`tsconfig.json`：`target ES2022`、`module ESNext`、`moduleResolution bundler`、`strict true`、`verbatimModuleSyntax true`、`isolatedModules true`、`skipLibCheck true`、`noEmit true`、`types ["vite/client"]`，`include` 为 `["src/**/*.ts","src/**/*.svelte"]`。
`index.html`：`<div id="app">` + `<script type="module" src="/src/main.ts">`。

- [ ] **Step 3: 创建 `src/main.ts`、`src/App.svelte`（占位）、`src/app.css`（占位）**

`main.ts` 用 Svelte 5 `mount()`：

```ts
import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

export default mount(App, { target: document.getElementById('app')! });
```

`App.svelte` 暂时只渲染 `<main>配置编辑器</main>`；`app.css` 留空文件即可（Task 20 填充）。

- [ ] **Step 4: 创建 `src-tauri/Cargo.toml`（依赖版本与 feature 均已实测编译通过，`windows-sys` 的 feature 列表不得删减）**

```toml
[package]
name = "edit_config_gui"
version = "0.1.0"
description = "CapsWriter 配置编辑器"
edition = "2021"
rust-version = "1.77.2"

[lib]
name = "edit_config_gui_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-dialog = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
toml_edit = "0.22"
similar = "3"
sha2 = "0.10"
sysinfo = "0.39"

[target.'cfg(windows)'.dependencies]
windows-sys = { version = "0.59", features = [
  "Win32_Foundation",
  "Win32_Storage_FileSystem",
  "Win32_System_Threading",
  "Win32_System_ProcessStatus",
  "Win32_Security",
  "Win32_UI_WindowsAndMessaging",
  "Win32_UI_Shell",
] }
```

> `windows-sys 0.59.0` 的符号归属已逐个查证（读 registry 里的 `src/Windows/Win32/**/mod.rs`），写代码时按此导入，与直觉不同处已标注：
>
> | 符号 | 模块路径 |
> |---|---|
> | `ReplaceFileW` | `Win32::Storage::FileSystem` |
> | `OpenProcessToken` | `Win32::System::Threading`（**不在** `Win32::Security`） |
> | `DuplicateTokenEx` | `Win32::Security` |
> | `CreateProcessW` | `Win32::System::Threading` |
> | `CreateProcessWithTokenW` | `Win32::System::Threading`（**不在** `advapi32` 映射的 `Security`） |
> | `PROCESS_QUERY_LIMITED_INFORMATION` | `Win32::System::Threading` |
> | `STARTUPINFOW` / `PROCESS_INFORMATION` | `Win32::System::Threading` |
> | `CloseHandle` / `GetLastError` | `Win32::Foundation` |
> | `GetShellWindow` / `GetWindowThreadProcessId` | `Win32::UI::WindowsAndMessaging` |
> | `IsUserAnAdmin` | `Win32::UI::Shell` |
> | `TOKEN_ELEVATION` / `TokenElevation` | `Win32::Security` |
>
> 已实测 `PCWSTR = *const u16`，`ReplaceFileW` 的第六、七参数是 `*const core::ffi::c_void`，传 `std::ptr::null()` 即可。

- [ ] **Step 5: 创建 `build.rs`、`tauri.conf.json`、`capabilities/default.json`、`main.rs`、`lib.rs`（占位 `run()`）**

`build.rs`：`fn main() { tauri_build::build() }`。

`tauri.conf.json`（`bundle.active=false`：只要裸 exe，不做安装包；`beforeBuildCommand` 指向 `pnpm build`，`frontendDist` 指向 `../dist`）：

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "edit_config_gui",
  "version": "0.1.0",
  "identifier": "com.capswriter.editconfiggui",
  "build": {
    "beforeDevCommand": "pnpm dev",
    "devUrl": "http://localhost:1420",
    "beforeBuildCommand": "pnpm build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      { "title": "配置编辑器", "width": 1000, "height": 760,
        "minWidth": 760, "minHeight": 520, "resizable": true }
    ],
    "security": { "csp": null }
  },
  "bundle": { "active": false, "icon": ["icons/icon.ico"] }
}
```

`capabilities/default.json`：`identifier: "default"`、`windows: ["main"]`、`permissions: ["core:default"]`（**不要**加 `dialog:*`，对话框从 Rust 侧调用）。

`main.rs`：

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
fn main() { edit_config_gui_lib::run() }
```

`lib.rs` 占位：`pub fn run()` 装配 `tauri::Builder::default().plugin(tauri_plugin_dialog::init())` 并 `.run(tauri::generate_context!())`。

- [ ] **Step 6: 复制图标**

```powershell
New-Item -ItemType Directory edit_config_gui/src-tauri/icons -Force
Copy-Item assets/icon/config-icon.ico edit_config_gui/src-tauri/icons/icon.ico
```

（实测：该 ICO 是单条目 256×256、`bpp` 字段为 1 的合法 ICO，可直接被 `tauri-build` 用来生成 Windows 资源；缺它会直接编译失败。）

- [ ] **Step 7: 建立 `src-tauri/.gitignore` 并验证构建与测试**

`.gitignore` 内容：`/target`、`/gen`。

```powershell
cd edit_config_gui
$env:PATH = "$env:USERPROFILE\.cargo\bin;" + $env:PATH
pnpm install
pnpm build          # 期望：vite 构建产出 dist/index.html
pnpm test           # 期望：没有测试文件也退出 0（脚本已带 --passWithNoTests）
pnpm check          # 期望：svelte-check found 0 errors and 0 warnings
cd src-tauri
cargo build --release   # 期望：Finished `release`（首次约 2-3 分钟）
cargo test --release    # 期望：0 tests，退出码 0
```

- [ ] **Step 8: Commit**

```powershell
git add edit_config_gui
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(edit_config_gui): 搭建 Tauri 2 + Svelte 5 项目骨架' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 2: config_doc —— 解析、归一化、输出与叶子枚举

**Files:**
- Create: `edit_config_gui/src-tauri/src/config_doc.rs`
- Create: `edit_config_gui/src-tauri/src/testutil.rs`（仅 `#[cfg(test)]`，Step 0 先建；后续所有 Rust 测试模块都依赖它）
- Modify: `edit_config_gui/src-tauri/src/lib.rs`（加 `mod config_doc;` 与 `#[cfg(test)] pub mod testutil;`）
- Create: `edit_config_gui/src-tauri/tests/fixtures/config_fixture.toml`（从 `config.toml` 复制一份 40 行左右、含注释/多行字符串/数组/动态表/非 ASCII 键的最小样本）

**Interfaces:**
- Consumes: 无
- Produces:

```rust
pub enum TomlType { String, Integer, Float, Boolean, Array, InlineTable }

pub struct ConfigDoc { /* doc: DocumentMut, path: PathBuf, original_text: String */ }

impl ConfigDoc {
    /// 输入为磁盘原始文本（可含 CRLF）；内部做 LF 归一化。
    pub fn parse(text: &str) -> Result<Self, TdError>;
    pub fn load(path: &std::path::Path) -> Result<Self, TdError>;
    pub fn path(&self) -> &std::path::Path;
    pub fn original_text(&self) -> &str;
    pub fn get(&self, segments: &[String]) -> Option<&toml_edit::Item>;
    pub fn toml_type_at(&self, segments: &[String]) -> Option<TomlType>;
    /// 输出 CRLF 文本（内部 to_string() 后再还原）
    pub fn to_toml_string(&self) -> String;
    /// 全部叶子：(segments, 值 JSON, TomlType)。数组与内联表整体作为叶子。
    pub fn leaf_fields(&self) -> Vec<FieldEntry>;
    pub fn doc_mut(&mut self) -> &mut toml_edit::DocumentMut;
}

pub struct FieldEntry { pub segments: Vec<String>, pub value: serde_json::Value, pub toml_type: TomlType }

/// 前端 `FieldView.tomlType` 的唯一来源（camelCase：string / integer / float / boolean / array / inlineTable）
pub fn toml_type_name(t: TomlType) -> &'static str;

pub enum TdError {
    Io(String),
    Parse(String),
    NotFound(Vec<String>),
    TypeMismatch(Vec<String>),
    NewlineInSingleLine(Vec<String>),
    NotAContainer(Vec<String>),
}
```

- [ ] **Step 0: 先建共享测试辅助模块 `testutil.rs`（后续每个测试模块都用它，否则各任务里的测试代码引用不到 `seg` / `load` / `comment_line_count`）**

新增文件 `edit_config_gui/src-tauri/src/testutil.rs`，在 `lib.rs` 里写 `#[cfg(test)] pub mod testutil;`：

```rust
#![cfg(test)]
/// Vec<&str> -> Vec<String>，所有测试用它构造 segments（禁止点分字符串）
pub fn seg(parts: &[&str]) -> Vec<String> {
    parts.iter().map(|s| s.to_string()).collect()
}

/// 读仓库根的真实 config.toml（cargo test 的 cwd 是 src-tauri）
pub const REAL: &str = "../../config.toml";

/// (解析后的文档, 磁盘原始文本)。名叫 load_real 以免和 ConfigDoc::load(path) 混淆
pub fn load_real() -> (crate::config_doc::ConfigDoc, String) {
    let raw = std::fs::read_to_string(REAL).unwrap();
    let doc = crate::config_doc::ConfigDoc::parse(&raw).unwrap();
    (doc, raw)
}

/// 以 `#` 开头的整行数（含前导空白）
pub fn comment_line_count(text: &str) -> usize {
    text.lines().filter(|l| l.trim_start().starts_with('#')).count()
}

/// 注释行的排序多重集，用于断言「注释内容一字未变」
pub fn comment_multiset(text: &str) -> Vec<String> {
    let mut v: Vec<String> = text.lines()
        .filter(|l| l.trim_start().starts_with('#'))
        .map(|l| l.trim_end().to_string())
        .collect();
    v.sort();
    v
}

/// 临时目录（每个测试独立）
pub fn tmpdir() -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!(
        "dsh_ecg_{}_{}",
        std::process::id(),
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
    ));
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// 在临时目录里放一份最小 config.toml 并返回其路径
pub fn seed(dir: &std::path::Path) -> std::path::PathBuf {
    let p = dir.join("config.toml");
    std::fs::write(&p, "a = 1\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    p
}
```

```rust
// testutil.rs 里再加两个跨任务复用的构造器
/// 构造一个补丁：patch(&["a"], PatchValue::Int(9))
pub fn patch(parts: &[&str], v: crate::patch::PatchValue) -> crate::patch::Patch {
    crate::patch::Patch { segments: seg(parts), value: v }
}

/// Task 3 用：为 149 个标量键各造一个与原值不同的探针补丁
/// （跳过 8 个多行 prompt 正文 + 3 个数组 + 2 条内联表条目；162 - 8 - 3 - 2 = 149）
pub fn single_line_probe_patches(
    doc: &crate::config_doc::ConfigDoc,
) -> Vec<crate::patch::Patch> {
    use crate::config_doc::TomlType::*;
    use crate::patch::PatchValue as P;
    let mut out = Vec::new();
    for f in doc.leaf_fields() {
        // 跳过 A：8 个多行提示词正文 client.prompt_style.prompt_<style>。
        // 同段的 8 个 prompt_<style>_shortcut 是单行键，必须保留在探针里。
        let in_prompt_style = f.segments.len() == 3
            && f.segments[0] == "client"
            && f.segments[1] == "prompt_style";
        if in_prompt_style && !f.segments[2].ends_with("_shortcut") {
            continue;
        }
        // 跳过 B：动态表条目（client.additional_special_apps.<exe>.<field>）。
        // 它们由 dynamic_table_* 系列测试单独覆盖；这里跳过是为了让本测试
        // 只聚焦「单行标量键改一行」这一条不变量。
        if f.segments.len() >= 3
            && f.segments[0] == "client"
            && f.segments[1] == "additional_special_apps"
        {
            continue;
        }
        let v = match (f.toml_type, &f.value) {
            (String,  serde_json::Value::String(s)) => P::Str(format!("{s}_probe")),
            (Integer, serde_json::Value::Number(n))    => P::Int(n.as_i64().unwrap() + 1),
            (Float,   serde_json::Value::Number(n))    => P::Float(n.as_f64().unwrap() + 0.01),
            (Boolean, serde_json::Value::Bool(b))      => P::Bool(!b),
            _ => continue,   // 3 个数组跳过
        };
        out.push(crate::patch::Patch { segments: f.segments, value: v });
    }
    out
}
```

- [ ] **Step 1: 写失败测试 `config_doc.rs` 的 `#[cfg(test)] mod tests`**

```rust
use super::*;
use crate::testutil::{seg, load_real, comment_line_count, REAL};

#[test]
fn parse_real_config() {
    let (doc, _) = load_real();
    let fields = doc.leaf_fields();
    assert_eq!(fields.len(), 162, "叶子键数必须是 162");
    // 非 ASCII 键（seg 是各测试模块共用的 helper：Vec<&str> -> Vec<String>）
    assert!(fields.iter().any(|f| f.segments == seg(&["client", "多音字"])));
    // 含点的表键必须是 4 段
    assert!(fields.iter().any(|f| f.segments == seg(&["client", "additional_special_apps", "vlc.exe", "hotkey"])));
}

#[test]
fn byte_identical_roundtrip() {
    let (doc, raw) = load_real();
    assert_eq!(doc.to_toml_string(), raw);
}

#[test]
fn crlf_preserved() {
    let (doc, _) = load_real();
    let out = doc.to_toml_string();
    assert_eq!(out.matches("\r\n").count(), out.matches('\n').count(), "不得出现裸 LF");
}

#[test]
fn comment_lines_preserved() {
    let (doc, raw) = load_real();
    assert_eq!(comment_line_count(&doc.to_toml_string()), comment_line_count(&raw));
    assert_eq!(comment_line_count(&raw), 306, "基准：真实 config.toml 有 306 行整行注释");
}

#[test]
fn toml_type_reported() {
    let (doc, _) = load_real();
    let t = |s: &[&str]| doc.toml_type_at(&seg(s));
    assert_eq!(t(&["server", "speech_recognition_port"]), Some(TomlType::String));
    assert_eq!(t(&["client", "audio_name_len"]), Some(TomlType::Integer));
    assert_eq!(t(&["client", "threshold"]), Some(TomlType::Float));
    assert_eq!(t(&["client", "hold_mode"]), Some(TomlType::Boolean));
    assert_eq!(t(&["client", "enter_apps"]), Some(TomlType::Array));
    assert_eq!(t(&["client", "additional_special_apps", "vlc.exe"]), Some(TomlType::InlineTable));
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cargo test --release config_doc` — 期望 `error[E0433]: failed to resolve: use of undeclared crate or module config_doc`。

- [ ] **Step 3: 实现 `config_doc.rs`**

关键点（其余按签名补全）：

```rust
pub fn parse(text: &str) -> Result<Self, TdError> {
    let original_text = text.to_string();
    let lf = text.replace("\r\n", "\n");           // 硬性：先归一化
    let doc: DocumentMut = lf.parse().map_err(|e: toml_edit::TomlError| TdError::Parse(e.to_string()))?;
    Ok(Self { doc, original_text, .. })
}

pub fn to_toml_string(&self) -> String {
    self.doc.to_string().replace('\n', "\r\n")     // 硬性：输出前还原
}
```

`leaf_fields()` 递归遍历规则（**必须精确按此实现，否则叶子数不是 162**）：

- `Item::Table` → 递归到子项，自身**不计**为叶子。
- `Item::Value(Value::InlineTable)` → **只**把它的每个子字段各输出为一条 `FieldEntry`（segments 到子字段为止，`toml_type` 按子值类型给出），内联表自身**不单独计**为叶子。这样 `client.additional_special_apps."vlc.exe"` 贡献 2 条叶子（`…,"vlc.exe","hotkey"` 与 `…,"vlc.exe","name"`），与 162 的统计口径一致（client 95 = 直接键 72 + zhipuai 2 + openai 3 + prompt_style 16 + additional_special_apps 2）。
- `Item::ArrayOfTables` → 输出为一条 `Array` 叶子。
- `Item::Value(其他)`（String/Integer/Float/Boolean/Array/Datetime）→ 直接输出为一条叶子。
- `Item::None` → 跳过。

`value` 用 `serde_json` 表示：`Value::String(s) -> JSON String`、`Integer -> Number`、`Float -> Number`（`serde_json::Number::from_f64`，`None` 时退化为字符串）、`Boolean -> Bool`、`Array -> JSON Array`（递归）、`InlineTable -> JSON Object`。

> 数组里的 `[["happ.exe", 0.5]]` 必须原样变成 `[["happ.exe",0.5]]` 的 JSON，浮点不得丢精度。

- [ ] **Step 4: 运行测试确认通过**

Run: `cargo test --release config_doc` — 期望 4 passed。

- [ ] **Step 5: Commit**

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(config_doc): TOML 文档模型与字节级保真往返' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 3: patch —— 补丁应用、decor 保真、类型保真、动态表与数组

**Files:**
- Create: `edit_config_gui/src-tauri/src/patch.rs`
- Modify: `edit_config_gui/src-tauri/src/lib.rs`
- Create: `edit_config_gui/src-tauri/tests/fixtures/config_fixture.toml`（若 Task 2 未建）

**Interfaces:**
- Consumes: `ConfigDoc`、`TomlType`、`TdError`（Task 2）
- Produces:

```rust
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone)]
#[serde(tag = "kind", content = "value", rename_all = "camelCase")]
pub enum PatchValue {
    Str(String), Int(i64), Float(f64), Bool(bool),
    StrArray(Vec<String>),
    PairArray(Vec<(String, f64)>),
    TableRow(std::collections::BTreeMap<String, String>),
    Delete,
}

pub struct Patch { pub segments: Vec<String>, pub value: PatchValue }

/// 两趟：先非 Delete，后 Delete。
pub fn apply(doc: &mut ConfigDoc, patches: &[Patch]) -> Result<Vec<Vec<String>>, TdError>;

/// similar::TextDiff 的 unified diff，标题 "config.toml (当前)" / "config.toml (保存后)"，context 3。
pub fn unified_diff(before: &str, after: &str) -> String;

/// 单行键白名单：仅这 8 个允许含 \n。
pub const LONG_TEXT_PATHS: [&[&str]; 8];
```

- [ ] **Step 1: 写失败测试**

```rust
#[test]
fn type_fidelity_string() {
    let (mut doc, _) = load_real();
    apply(&mut doc, &[patch(&["server","speech_recognition_port"], PatchValue::Int(9999))]).unwrap();
    let out = doc.to_toml_string();
    assert!(out.contains(r#"speech_recognition_port = "9999""#), "原为字符串，写入后必须仍是字符串");
}

#[test]
fn type_fidelity_int_and_float() {
    let (mut doc, _) = load_real();
    apply(&mut doc, &[patch(&["client","audio_name_len"], PatchValue::Int(30))]).unwrap();
    apply(&mut doc, &[patch(&["client","threshold"], PatchValue::Float(0.75))]).unwrap();
    let out = doc.to_toml_string();
    assert!(out.contains("audio_name_len = 30"));
    assert!(out.contains("threshold = 0.75"));
}

#[test]
fn type_mismatch_rejected() {
    let (mut doc, _) = load_real();
    let e = apply(&mut doc, &[patch(&["client","addr"], PatchValue::PairArray(vec![("a".into(), 0.5)]))]);
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
    apply(&mut doc, &[
        patch(&["client","QQMusic_global_pause_hotkey"], PatchValue::Str("ctrl + alt + f11".into())),
        patch(&["client","threshold"], PatchValue::Float(0.9)),
        patch(&["server","model"], PatchValue::Str("Sensevoice".into())),
    ]).unwrap();
    let out = doc.to_toml_string();
    assert_eq!(comment_line_count(&out), 306);
    assert_eq!(comment_multiset(&out), comment_multiset(&raw), "注释内容也必须不变");
}

#[test]
fn inline_comment_survives_scalar_edit() {
    let (mut doc, _) = load_real();
    apply(&mut doc, &[patch(&["client","additional_special_apps","vlc.exe","hotkey"],
                            PatchValue::Str("ctrl + alt + f10".into()))]).unwrap();
    let out = doc.to_toml_string();
    assert!(out.contains("# VLC 设置全局快捷键后需要重启 VLC 才能生效"),
            "行尾注释必须随 decor 搬运保留");
}

#[test]
fn newline_rejected_in_single_line() {
    let (mut doc, _) = load_real();
    let e = apply(&mut doc, &[patch(&["server","addr"], PatchValue::Str("a\nb".into()))]);
    assert!(matches!(e, Err(TdError::NewlineInSingleLine(_))));
}

#[test]
fn multiline_prompt_allows_newline() {
    let (mut doc, _) = load_real();
    apply(&mut doc, &[patch(&["client","prompt_style","prompt_official"],
                            PatchValue::Str("第一行\n第二行".into()))]).unwrap();
    let out = doc.to_toml_string();
    ConfigDoc::parse(&out).expect("写回后必须仍可解析");
}

#[test]
fn multiline_quote_and_backslash_roundtrip() {
    let (mut doc, _) = load_real();
    let evil = "含\"\"\"三引号\\与\\反斜杠#井号\t制表";
    apply(&mut doc, &[patch(&["client","prompt_style","prompt_official"], PatchValue::Str(evil.into()))]).unwrap();
    let out = doc.to_toml_string();
    let back = ConfigDoc::parse(&out).unwrap();
    let got = back.get(&seg(&["client","prompt_style","prompt_official"])).unwrap();
    assert_eq!(got.as_str().unwrap(), evil);
}

#[test]
fn dynamic_table_add_remove() {
    let (mut doc, raw) = load_real();
    let base = raw.lines().count();
    apply(&mut doc, &[Patch { segments: seg(&["client","additional_special_apps","test.exe"]),
        value: PatchValue::TableRow([("hotkey".into(),"ctrl + alt + f11".into()),
                                     ("name".into(),"Test App".into())].into()) }]).unwrap();
    let out = doc.to_toml_string();
    assert_eq!(out.lines().count(), base + 1);
    assert_eq!(comment_line_count(&out), 306);
    assert!(out.contains("# VLC 设置全局快捷键后需要重启 VLC 才能生效"));

    let mut d2 = ConfigDoc::parse(&out).unwrap();
    apply(&mut d2, &[Patch { segments: seg(&["client","additional_special_apps","vlc.exe"]), value: PatchValue::Delete }]).unwrap();
    let out2 = d2.to_toml_string();
    assert_eq!(out2.lines().count(), base);
    assert_eq!(comment_line_count(&out2), 306, "删条目不得删注释");
}

#[test]
fn dynamic_table_weird_key_quoted() {
    let (mut doc, _) = load_real();
    for key in ["my app.exe", "a\"b.exe", "中文进程.exe", "a.b.c"] {
        let mut d = ConfigDoc::parse(&doc.original_text()).unwrap();
        apply(&mut d, &[Patch { segments: vec!["client".into(),"additional_special_apps".into(), key.into()],
            value: PatchValue::TableRow([("hotkey".into(),"".into()),("name".into(),"n".into())].into()) }]).unwrap();
        let out = d.to_toml_string();
        let back = ConfigDoc::parse(&out).expect("含特殊字符的键名必须写出合法 TOML");
        assert!(back.get(&vec!["client".into(),"additional_special_apps".into(), key.into()]).is_some());
    }
}

#[test]
fn array_prefix_normalized() {
    let (mut doc, _) = load_real();
    apply(&mut doc, &[patch(&["client","enter_apps"],
        PatchValue::PairArray(vec![("hexin.exe".into(), 0.5)]))]).unwrap();
    let out = doc.to_toml_string();
    assert!(out.contains(r#"enter_apps = [["hexin.exe", 0.5]]"#), "不得出现 [ [ 的额外空格");
}

#[test]
fn empty_string_list_placeholder_roundtrip() {
    let (mut doc, _) = load_real();
    // 前端把「只含空串」规整为空数组，保存时必须写回 [""]
    apply(&mut doc, &[patch(&["client","disable_exe_list"], PatchValue::StrArray(vec![]))]).unwrap();
    assert!(doc.to_toml_string().contains(r#"disable_exe_list = [""]"#));
}

#[test]
fn tolerant_load_of_out_of_range_int() {
    // 超范围值只影响控件提示，不得影响解析或其它字段
    let mut txt = std::fs::read_to_string(REAL).unwrap();
    txt = txt.replace("mic_seg_duration = 60", "mic_seg_duration = 120");
    let mut doc = ConfigDoc::parse(&txt).unwrap();
    apply(&mut doc, &[patch(&["client","audio_name_len"], PatchValue::Int(25))]).unwrap();
    assert!(doc.to_toml_string().contains("audio_name_len = 25"));
}

#[test]
fn diff_only_changed() {
    let raw = std::fs::read_to_string(REAL).unwrap();
    let mut doc = ConfigDoc::parse(&raw).unwrap();
    apply(&mut doc, &[
        patch(&["client","threshold"], PatchValue::Float(0.7)),
        patch(&["server","model"], PatchValue::Str("FunASR".into())),
        patch(&["debug","logger_level"], PatchValue::Str("INFO".into())),
    ]).unwrap();
    let d = unified_diff(&raw, &doc.to_toml_string());
    let added = d.lines().filter(|l| l.starts_with('+') && !l.starts_with("+++")).count();
    let removed = d.lines().filter(|l| l.starts_with('-') && !l.starts_with("---")).count();
    assert_eq!((added, removed), (3, 3));
}

#[test]
fn delete_applied_after_non_delete() {
    // 同一批里既有删除首元素又有追加，删除必须后跑，避免索引错位
    let (mut doc, _) = load_real();
    apply(&mut doc, &[
        Patch { segments: seg(&["client","enter_apps"]), value: PatchValue::Delete },
        Patch { segments: seg(&["client","disable_exe_list"]), value: PatchValue::StrArray(vec!["a.exe".into()]) },
    ]).unwrap();
    let out = doc.to_toml_string();
    assert!(!out.contains("happ.exe"));
    assert!(out.contains(r#"disable_exe_list = ["a.exe"]"#));
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cargo test --release patch` — 期望 `failed to resolve: use of undeclared crate or module patch`。

- [ ] **Step 3: 实现 decor 保真的 `set_scalar` 与三种序列写入**

这是本任务唯一需要成段给出实现的地方（规格 §7.4 结论 4/5/6 的落地）：

```rust
/// 一对一替换一个标量值，保留 prefix（缩进）与 suffix（行尾注释）。
fn set_scalar(item: &mut Item, new: Value) -> Result<(), TdError> {
    let Item::Value(old) = item else { return Err(TdError::TypeMismatch(vec![])) };
    let (p, s) = (old.decor().prefix().cloned(), old.decor().suffix().cloned());
    let mut nv = new;
    if let Some(p) = p { nv.decor_mut().set_prefix(p); }
    if let Some(s) = s { nv.decor_mut().set_suffix(s); }   // ← 行尾注释在 suffix 里
    *item = Item::Value(nv);
    Ok(())
}
```

类型判定与写入（`PatchValue` × 现有 `TomlType`）：

| 现有类型 | `PatchValue::Str` | `Int` | `Float` | `Bool` | `StrArray` | `PairArray` | `TableRow` |
|---|---|---|---|---|---|---|---|
| String | 写字符串 | `to_string()` 后写字符串 | `to_string()` 后写字符串 | 拒绝 `TypeMismatch` | 拒绝 | 拒绝 | 拒绝 |
| Integer | 解析成 i64，失败拒绝 | 写整数 | 取整写整数 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| Float | 解析成 f64，失败拒绝 | 转 f64 | 写浮点 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| Boolean | `"true"/"false"` 转布尔，否则拒绝 | 拒绝 | 拒绝 | 写布尔 | 拒绝 | 拒绝 | 拒绝 |
| Array | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 重建字符串数组 | 重建二维数组 | 拒绝 |
| InlineTable | 拒绝（除非 segments 长度为 4，见下） | — | — | — | — | — | 替换整行 |

浮点写入必须用 `toml_edit::Formatted::new(f64)`（实测 `*f = nv.as_float()` 类型不匹配）。

动态表（`segments` 形如 `["client","additional_special_apps", key]`）：
- `TableRow(map)`：定位 `Table`（`as_table_mut()`），若 `key` 已存在且是 `InlineTable` → 逐字段 `insert`（**每个字段也要 decor 搬运**，从旧 `Value::String` 取 `prefix`/`suffix`）；不存在 → `Table::insert(key, Item::Value(Value::InlineTable(新表)))`。
- `Delete`：`Table::remove(key)`。
- **禁止** `Table::clear()`；`Table::insert` 自己会加引号，实测 `"my app.exe"` 等键名能正确输出。

数组写入（`StrArray` / `PairArray`）：整段重建 `Array`，首元素 `set_prefix("")`、后续元素 `set_prefix(" ")`，然后 `set_scalar` 替换整个数组值（保留数组自己的 suffix 与行尾注释）。`StrArray(vec![])` 特例：写入 `[""]`（规格 §3.4 占位语义）。

`Delete` 用于**非**动态表时必须两趟：第一趟跳过所有 `Delete`，第二趟再执行。`apply` 返回被改动过的 segments 列表（去重、保持首次出现顺序）。

- [ ] **Step 4: 运行全部 patch 测试**

Run: `cargo test --release` — 期望 Task 2+3 全绿，特别确认 `single_line_key_touches_one_line`（149 次循环）与 `dynamic_table_weird_key_quoted` 通过。

- [ ] **Step 5: Commit**

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(patch): 保注释保类型的补丁应用与 unified diff' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 4: hotkey —— 键名表导出与等价解析器

**Files:**
- Create: `edit_config_gui/scripts/export_hotkey_tables.py`
- Create: `edit_config_gui/scripts/gen_hotkey_fixtures.py`
- Create: `edit_config_gui/src-tauri/src/hotkey_names.json`（脚本产物，提交）
- Create: `edit_config_gui/src-tauri/src/canonical_names.json`（脚本产物，提交）
- Create: `edit_config_gui/src-tauri/src/hotkey.rs`
- Create: `edit_config_gui/src-tauri/tests/fixtures/hotkey_cases.txt`、`hotkey_expected.txt`（脚本产物，提交）
- Modify: `edit_config_gui/src-tauri/src/lib.rs`

**Interfaces:**
- Consumes: 无
- Produces:

```rust
/// 等价 keyboard.parse_hotkey(...) 不抛异常
pub fn is_valid_hotkey(hk: &str) -> bool;
```

- [ ] **Step 1: 写导出脚本并运行，产出两张 JSON**

`export_hotkey_tables.py`：

```python
import json, pathlib
from keyboard import _winkeyboard as wk, _canonical_names as cn

wk._setup_name_tables()
out = pathlib.Path(__file__).resolve().parents[1] / "src-tauri" / "src"
(out / "hotkey_names.json").write_text(
    json.dumps(sorted(wk.from_name.keys()), ensure_ascii=False, indent=0), encoding="utf-8")
(out / "canonical_names.json").write_text(
    json.dumps(cn.canonical_names, ensure_ascii=False, indent=0), encoding="utf-8")
print("from_name:", len(wk.from_name), "canonical:", len(cn.canonical_names))
```

Run: `CapsWriter-Offline\.venv\Scripts\python.exe edit_config_gui\scripts\export_hotkey_tables.py`
期望输出：`from_name: 205 canonical: 1171`。

- [ ] **Step 2: 写对拍集生成脚本并运行**

`gen_hotkey_fixtures.py` 必须产出 **841 行**用例与 **841 行**期望（合法 432 / 非法 409），内容为：`config.toml` 中实际出现的全部快捷键值；8 种修饰符 × 33 个主键 × 3 种空格写法；逗号分段组合；单字符与纯数字；大小写与空白变体。每行期望是 `ok` 或 `err`。生成时用 `.venv` 的 `keyboard.parse_hotkey` 实际跑，不手写真值：

```python
def expected(hk: str) -> str:
    try:
        keyboard.parse_hotkey(hk)
        return "ok"
    except Exception:
        return "err"
```

Run: `CapsWriter-Offline\.venv\Scripts\python.exe edit_config_gui\scripts\gen_hotkey_fixtures.py`
期望：两个文件各 841 行，其中 `ok` 432 行。

- [ ] **Step 3: 写失败测试**

```rust
#[test]
fn validate_hotkey_minimal_regression() {
    for ok in ["caps lock","ctrl + alt + f5","Ctrl + Alt + F5","left shift","ctrl + alt + [",
               "f13","f24","space","enter","shift","+","_","esc","escape","ctrl+alt+f5",
               "alt+a, alt+b","volume up","left windows","alt+f4"] {
        assert!(is_valid_hotkey(ok), "应合法: {ok:?}");
    }
    for bad in ["f999","f25","","ctrl + ","mouse left","  ctrl  +  alt  +  f5  ",
                "ctrl + shift + ,","鼠标"] {
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
        if got == "ok" { ok_n += 1; }
        if got != e { diff += 1; eprintln!("diff: {c:?} expected {e} got {got}"); }
    }
    assert_eq!(cases.lines().count(), 841);
    assert_eq!(diff, 0, "与 Python keyboard 的对拍必须 0 差异");
    assert_eq!(ok_n, 432);
}
```

- [ ] **Step 4: 运行确认失败，然后实现 `hotkey.rs`**

Run: `cargo test --release hotkey` — 期望 unresolved import。

实现按规格 §8.1 的伪代码（`normalize_name` / `is_valid_key` / `split_step` / `split_plus` 已逐字给出，照抄即可），两张表用：

```rust
static ACCEPTED: OnceLock<HashSet<String>> = OnceLock::new();
static CANONICAL: OnceLock<HashMap<String, String>> = OnceLock::new();

fn accepted() -> &'static HashSet<String> {
    ACCEPTED.get_or_init(|| serde_json::from_str(include_str!("hotkey_names.json")).unwrap())
}
fn canonical() -> &'static HashMap<String, String> {
    CANONICAL.get_or_init(|| serde_json::from_str(include_str!("canonical_names.json")).unwrap())
}
```

`SIDED_MODIFIERS = ["ctrl","alt","windows","shift"]`：命中时递归尝试 `left <n>` 与 `right <n>`。
单字符与纯数字整体短路（`hk.chars().count() == 1 || hk.parse::<i64>().is_ok()`），不进 `split_plus`。
空串最先早退为非法。**不 trim**。

- [ ] **Step 5: 运行全绿**

Run: `cargo test --release hotkey` — 期望 2 passed（841 例 0 差异）。

- [ ] **Step 6: Commit**

```powershell
git add edit_config_gui/scripts edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(hotkey): 移植 keyboard.parse_hotkey 与 841 例对拍' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 5: validate —— 10 个校验器与全量报告

**Files:**
- Create: `edit_config_gui/src-tauri/src/validate.rs`
- Modify: `edit_config_gui/src-tauri/src/lib.rs`

**Interfaces:**
- Consumes: `ConfigDoc`、`TomlType`（Task 2）、`is_valid_hotkey`（Task 4）
- Produces:

```rust
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ValidatorId { Ip, LocalListenableIp, Port, FileExist, DirExist, Hotkey, Url, SingleLine, IpPort, RegexClass }

#[derive(serde::Deserialize, Debug, Clone)]
#[serde(rename_all = "camelCase")]
pub struct FieldRule {
    pub segments: Vec<String>,
    pub validators: Vec<ValidatorId>,
    pub allow_empty: bool,
    pub file_suffix: Option<String>,
    pub warn_only: bool,          // true = 只产生 warning，不阻断保存
}

pub struct ValidationError { pub segments: Vec<String>, pub validator: ValidatorId, pub message: String }
pub struct ValidationReport { pub errors: Vec<ValidationError>, pub warnings: Vec<ValidationError> }

/// 对「补丁应用之后」的文档全量校验（不是只校验脏字段）。
pub fn validate_all(doc: &ConfigDoc, rules: &[FieldRule]) -> ValidationReport;

/// 单值校验，供 preview/commit 复用与单测。
pub fn check_value(raw: &str, id: ValidatorId, suffix: Option<&str>) -> Result<(), String>;
```

- [ ] **Step 1: 写失败测试**

```rust
fn ck(v: &str, id: ValidatorId) -> Result<(), String> { check_value(v, id, None) }

#[test] fn validate_ip() {
    for ok in ["127.0.0.1","192.168.3.5","8.8.8.8","0.0.0.0","255.255.255.255"] {
        assert!(ck(ok, ValidatorId::Ip).is_ok(), "{ok}");
    }
    // "01.2.3.4" 在 Python ipaddress.IPv4Address 里是非法（前导零歧义），必须一致拒绝
    for bad in ["256.1.1.1","1.2.3","abc",""," 1.2.3.4","1.2.3.4.5","01.2.3.4","1.2.3.4 "] {
        assert_eq!(ck(bad, ValidatorId::Ip).unwrap_err(), "不是有效的IP地址", "{bad:?}");
    }
}

#[test] fn validate_local_listenable_ip() {
    for ok in ["127.0.0.1","192.168.1.1","10.0.0.5","172.16.0.1","169.254.1.1","0.0.0.0"] {
        assert!(ck(ok, ValidatorId::LocalListenableIp).is_ok(), "{ok}");
    }
    assert!(ck("8.8.8.8", ValidatorId::LocalListenableIp).is_err(), "公网 IP 不得通过");
    assert_eq!(ck("8.8.8.8", ValidatorId::LocalListenableIp).unwrap_err(), "不是有效的本地可监听IP地址");
}

#[test] fn validate_port() {
    for ok in ["1023","1024","6016","65535"] { assert!(ck(ok, ValidatorId::Port).is_ok(), "{ok}"); }
    assert_eq!(ck("80", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
    assert_eq!(ck("65536", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
    assert_eq!(ck("0", ValidatorId::Port).unwrap_err(), "端口号必须在1023到65535之间");
    assert_eq!(ck("abc", ValidatorId::Port).unwrap_err(), "不是有效的端口号");
}

#[test] fn validate_url() {
    assert!(ck("http://x", ValidatorId::Url).is_ok());
    assert!(ck("https://x/y", ValidatorId::Url).is_ok());
    assert_eq!(ck("ftp://x", ValidatorId::Url).unwrap_err(), "URL必须以http://或https://开头");
    assert_eq!(ck("", ValidatorId::Url).unwrap_err(), "URL不能为空");
}

#[test] fn validate_regex_class() {
    assert!(ck("，。,.", ValidatorId::RegexClass).is_ok());
    assert_eq!(ck("", ValidatorId::RegexClass).unwrap_err(), "该配置项不能为空");
    for bad in ["\\", "^", "[", "a[b", "a\\b", "^a"] {
        assert_eq!(ck(bad, ValidatorId::RegexClass).unwrap_err(), "该字符不能用于此处", "{bad:?}");
    }
    // 防止禁用集开得过大
    for good in ["，","。","、","；","：","？","！","…","—","～","·","「","」","『","』",
                 "（","）","【","】","《","》","〈","〉","“","”","‘","’","｡","､","｢","｣",
                 "]","(",")","*","+","?",".","-","~",",",";","!","@","$","%","&","/"] {
        assert!(ck(good, ValidatorId::RegexClass).is_ok(), "应允许: {good:?}");
    }
}

#[test] fn validate_ip_port() {
    for ok in ["192.168.3.127:10101","192.168.3.127","localhost","my-phone:5555","10.0.0.2:1024"] {
        assert!(ck(ok, ValidatorId::IpPort).is_ok(), "{ok}");
    }
    assert_eq!(ck("host:70000", ValidatorId::IpPort).unwrap_err(), "端口号必须在1023到65535之间");
    assert_eq!(ck("host:abc", ValidatorId::IpPort).unwrap_err(), "不是有效的端口号");
    assert_eq!(ck("", ValidatorId::IpPort).unwrap_err(), "不是有效的地址");
    assert_eq!(ck("a:b:c", ValidatorId::IpPort).unwrap_err(), "不是有效的地址");
}

#[test] fn validate_single_line() {
    assert!(ck("普通文本", ValidatorId::SingleLine).is_ok());
    assert_eq!(ck("a\nb", ValidatorId::SingleLine).unwrap_err(), "该配置项不能包含换行符");
    assert!(ck("a\rb", ValidatorId::SingleLine).is_err());
}

#[test] fn validate_file_and_dir() {
    let tmp = std::env::temp_dir().join("dsh_validate_probe.txt");
    std::fs::write(&tmp, b"x").unwrap();
    let p = tmp.to_string_lossy().to_string();
    assert!(check_value(&p, ValidatorId::FileExist, Some(".txt")).is_ok());
    assert_eq!(check_value(&p, ValidatorId::FileExist, Some(".onnx")).unwrap_err(),
               "文件格式不正确，预期后缀为.onnx");
    assert_eq!(check_value("C:/绝对不存在的路径/x.txt", ValidatorId::FileExist, None).unwrap_err(), "文件不存在");
    assert_eq!(check_value("C:/绝对不存在的路径", ValidatorId::DirExist, None).unwrap_err(), "目录不存在");
    let dir = std::env::temp_dir();
    assert!(check_value(&dir.to_string_lossy(), ValidatorId::DirExist, None).is_ok());
    assert_eq!(check_value(&dir.to_string_lossy(), ValidatorId::FileExist, None).unwrap_err(), "不是有效的文件");
}

#[test] fn allow_empty_skips_validation() {
    let rules = vec![FieldRule { segments: seg(&["client","QQMusic_global_pause_hotkey"]),
        validators: vec![ValidatorId::Hotkey], allow_empty: true, file_suffix: None, warn_only: false }];
    let (doc, _) = load_real();
    let report = validate_all(&doc, &rules);
    assert!(report.errors.is_empty(), "allow_empty 的空值不得报错");
}

#[test] fn warn_only_goes_to_warnings() {
    let rules = vec![FieldRule { segments: seg(&["model_paths","funasr_llm_path"]),
        validators: vec![ValidatorId::FileExist], allow_empty: false,
        file_suffix: Some(".gguf".into()), warn_only: true }];
    let (doc, _) = load_real();
    let report = validate_all(&doc, &rules);
    assert!(report.errors.is_empty());
    assert_eq!(report.warnings.len(), 1, "模型未下载只警告");
}

#[test] fn hidden_field_not_validated() {
    // adb 关闭时前端不下发 adb_addr 的规则；这里验证「不下发 = 不校验」，
    // 同时反向证明「一旦下发，坏值确实会被拦」——两半都断言，否则这条测试恒真。
    let (doc, _) = load_real();
    let adb_rule = FieldRule {
        segments: seg(&["client", "adb_addr"]),
        validators: vec![ValidatorId::IpPort],
        allow_empty: false, file_suffix: None, warn_only: false,
    };

    // ① 不下发规则 → 文档里那条（合法的）adb_addr 不产生任何 error
    let without = validate_all(&doc, &[]);
    assert!(without.errors.is_empty());

    // ② 下发规则但值是坏的 → 必须报错（证明 ① 不是因为校验器失效才为空）
    let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
    crate::patch::apply(&mut broken, &[crate::testutil::patch(
        &["client", "adb_addr"], crate::patch::PatchValue::Str("a:b:c".into()))]).unwrap();
    let with = validate_all(&broken, &[adb_rule]);
    assert_eq!(with.errors.len(), 1, "坏值必须被 IpPort 拦下");
    assert_eq!(with.errors[0].message, "不是有效的地址");
}

#[test] fn error_aggregation() {
    // 三个字段同时非法 → 一次返回三条错误，不能只报第一条就停
    let (doc, _) = load_real();
    let rules = vec![
        FieldRule { segments: seg(&["server","addr"]), validators: vec![ValidatorId::LocalListenableIp],
                    allow_empty: false, file_suffix: None, warn_only: false },
        FieldRule { segments: seg(&["server","speech_recognition_port"]), validators: vec![ValidatorId::Port],
                    allow_empty: false, file_suffix: None, warn_only: false },
        FieldRule { segments: seg(&["libretranslate","api"]), validators: vec![ValidatorId::Url],
                    allow_empty: false, file_suffix: None, warn_only: false },
    ];
    let mut broken = ConfigDoc::parse(doc.original_text()).unwrap();
    use crate::patch::PatchValue;
    crate::patch::apply(&mut broken, &[
        patch(&["server","addr"], PatchValue::Str("8.8.8.8".into())),
        patch(&["server","speech_recognition_port"], PatchValue::Str("80".into())),
        patch(&["libretranslate","api"], PatchValue::Str("ftp://x".into())),
    ]).unwrap();
    let report = validate_all(&broken, &rules);
    assert_eq!(report.errors.len(), 3, "三个非法字段必须报三条");
    assert!(report.warnings.is_empty());
    // 顺序按 rules 顺序，保证前端错误表可稳定覆盖
    assert_eq!(report.errors[0].segments, seg(&["server","addr"]));
    assert_eq!(report.errors[1].segments, seg(&["server","speech_recognition_port"]));
    assert_eq!(report.errors[2].segments, seg(&["libretranslate","api"]));
}

#[test] fn rule_for_missing_segment_is_ignored() {
    // 前端 schema 与磁盘文件不同步（例如用户手删了某键）时，规则不能 panic
    let (doc, _) = load_real();
    let rules = vec![FieldRule {
        segments: seg(&["client", "不存在的键"]),
        validators: vec![ValidatorId::Ip], allow_empty: false, file_suffix: None, warn_only: false,
    }];
    let report = validate_all(&doc, &rules);
    assert!(report.errors.is_empty(), "找不到的值跳过校验，不得 panic 也不得报错");
}
```

- [ ] **Step 2: 运行确认失败，然后实现**

语义逐条对齐旧 `util/edit_config_gui/value_check.py`（错误文案必须逐字相同，测试里已固化）。要点：

- `Ip`：整串必须正好 4 段、每段 1–3 位纯数字、无正负号、无空白，且各段 0–255 且**不得有前导零**（`"01.2.3.4"` 与尾部空格的 `"1.2.3.4 "` 都必须拒绝 —— 已用 `.venv` 的 `ipaddress.IPv4Address` 实测，这两种在 Python 里都抛 `AddressValueError`）。
- `LocalListenableIp`：先过 `Ip`，再判断 `10/8`、`172.16/12`、`192.168/16`、`127/8`、`169.254/16` 或 `0.0.0.0`。
- `RegexClass`：非空 + 不含 `\`、`^`、`[`。
- `IpPort`：按最后一个 `:` 切分（无 `:` 则整串是 host）；host 非空、不含空白与 `:`；port 部分套 `Port`。
- `FileExist` / `DirExist`：用 `std::path::Path` 的 `exists`/`is_file`/`is_dir`；后缀比较大小写不敏感。
- `validate_all`：遍历 `rules`，取文档当前值（`Item::Value` 转字符串：String 取原值、Integer/Float/Boolean 取字面量、Array 跳过校验），`allow_empty && raw.trim().is_empty()` 直接跳过；`warn_only` 的错误进 `warnings`。

- [ ] **Step 3: 运行全绿**

Run: `cargo test --release validate` — 期望全部 passed。

- [ ] **Step 4: Commit**

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(validate): 十个校验器与全量校验报告' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 6: file_io —— 指纹、原子提交、备份与回滚

**Files:**
- Create: `edit_config_gui/src-tauri/src/file_io.rs`
- Modify: `edit_config_gui/src-tauri/src/lib.rs`

**Interfaces:**
- Consumes: 无
- Produces:

```rust
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, PartialEq, Eq)]
pub struct FileFingerprint { pub mtime_ms: i64, pub size: u64, pub sha256: String }

pub enum IoError {
    Io(String),
    ReplaceFailed { code: u32, message: String },
    ReadbackParse(String),
    Conflict,
    NotFound(std::path::PathBuf),
}

pub fn fingerprint(path: &std::path::Path) -> Result<FileFingerprint, IoError>;
pub fn read_bytes(path: &std::path::Path) -> Result<Vec<u8>, IoError>;

/// 原子提交：写 .tmp → flush → sync_all → ReplaceFileW(target, tmp, bak) → 回读解析 → 返回新指纹
pub fn atomic_write(target: &std::path::Path, text: &str) -> Result<FileFingerprint, IoError>;

/// 从 .bak 回滚（同样走 ReplaceFileW，备份槽用临时名）
pub fn rollback_from_bak(target: &std::path::Path) -> Result<(), IoError>;

/// 供测试注入失败：默认 false
pub fn set_inject_readback_failure(v: bool);
```

- [ ] **Step 1: 写失败测试**

```rust
use super::*;
use crate::testutil::{tmpdir, seed};
// tmpdir() / seed() 来自 testutil.rs（Task 2 Step 0 已建），不再各模块重复定义

#[test]
fn writes_and_fingerprints() {
    let d = tmpdir(); let p = seed(&d);
    let fp1 = fingerprint(&p).unwrap();
    let fp2 = atomic_write(&p, "a = 2\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    assert_ne!(fp1.sha256, fp2.sha256);
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "a = 2\r\n# 注释\r\nb = \"x\"\r\n");
}

#[test]
fn backup_contents() {
    let d = tmpdir(); let p = seed(&d);
    atomic_write(&p, "a = 2\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    let bak = d.join("config.toml.bak");
    assert_eq!(std::fs::read_to_string(&bak).unwrap(), "a = 1\r\n# 注释\r\nb = \"x\"\r\n");
    atomic_write(&p, "a = 3\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    assert_eq!(std::fs::read_to_string(&bak).unwrap(), "a = 2\r\n# 注释\r\nb = \"x\"\r\n",
               "第二次保存时 .bak 必须是上一版");
}

#[test]
fn tmp_left_over_does_not_corrupt_target() {
    let d = tmpdir(); let p = seed(&d);
    // 模拟「写了 .tmp 但进程被杀」：.tmp 存在且内容完整，target 未变
    std::fs::write(d.join("config.toml.tmp"), "a = 999\r\n").unwrap();
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "a = 1\r\n# 注释\r\nb = \"x\"\r\n");
    // 下一次正常保存必须成功并清理 .tmp
    atomic_write(&p, "a = 4\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    assert!(!d.join("config.toml.tmp").exists());
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "a = 4\r\n# 注释\r\nb = \"x\"\r\n");
}

#[test]
fn rollback_from_bak() {
    let d = tmpdir(); let p = seed(&d);
    atomic_write(&p, "a = 2\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    atomic_write(&p, "a = 3\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    rollback_from_bak(&p).unwrap();
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "a = 2\r\n# 注释\r\nb = \"x\"\r\n",
               "回滚后应是上一版");
}

#[test]
fn readback_failure_rolls_back() {
    let d = tmpdir(); let p = seed(&d);
    atomic_write(&p, "a = 2\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    set_inject_readback_failure(true);
    let r = atomic_write(&p, "a = 3\r\n# 注释\r\nb = \"x\"\r\n");
    set_inject_readback_failure(false);
    assert!(matches!(r, Err(IoError::ReadbackParse(_))));
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "a = 2\r\n# 注释\r\nb = \"x\"\r\n",
               "回读失败必须回滚到上一版");
}

#[test]
fn fingerprint_changes_on_external_write() {
    let d = tmpdir(); let p = seed(&d);
    let fp1 = fingerprint(&p).unwrap();
    // ① 内容变化（同时 mtime 变）
    std::fs::write(&p, "a = 42\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    let fp2 = fingerprint(&p).unwrap();
    assert_ne!(fp1.sha256, fp2.sha256, "内容变了 sha256 必须变");
    // ② 只改 mtime（内容逐字节相同）—— 触摸一下文件
    std::thread::sleep(std::time::Duration::from_millis(20));
    std::fs::write(&p, "a = 42\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    let fp3 = fingerprint(&p).unwrap();
    assert_ne!(fp2.mtime_ms, fp3.mtime_ms, "mtime 变了指纹就必须变（哪怕内容一样）");
    assert_eq!(fp2.sha256, fp3.sha256);
    // ③ 同大小但内容不同 —— sha256 必须能区分（只比 size 是经典漏检）
    let a = d.join("a.toml"); let b = d.join("b.toml");
    std::fs::write(&a, "x = 1\r\n").unwrap();
    std::fs::write(&b, "x = 2\r\n").unwrap();
    assert_eq!(fingerprint(&a).unwrap().size, fingerprint(&b).unwrap().size);
    assert_ne!(fingerprint(&a).unwrap().sha256, fingerprint(&b).unwrap().sha256,
               "同大小不同内容必须靠 sha256 区分");
}

#[test]
fn commit_conflict_does_not_touch_file() {
    let d = tmpdir(); let p = seed(&d);
    let fp = fingerprint(&p).unwrap();
    // 外部改动
    std::fs::write(&p, "a = 42\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    assert_ne!(fingerprint(&p).unwrap(), fp);
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "a = 42\r\n# 注释\r\nb = \"x\"\r\n",
               "冲突检测只是比较，不得写文件");
}

#[test]
fn replace_null_backup_ok() {
    // 传 NULL 必须成功且不产生备份；传空串必须失败且原文件不变
    let d = tmpdir(); let p = seed(&d);
    let tmp = d.join("config.toml.tmp");
    std::fs::write(&tmp, "z = 9\r\n").unwrap();
    assert!(replace_file_w(&p, &tmp, None).is_ok(), "NULL 备份必须成功");
    assert!(!d.join("config.toml.bak").exists());
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "z = 9\r\n");

    let d2 = tmpdir().join("second"); std::fs::create_dir_all(&d2).unwrap();
    let p2 = seed(&d2);
    let tmp2 = d2.join("config.toml.tmp");
    std::fs::write(&tmp2, "z = 9\r\n").unwrap();
    assert!(replace_file_w(&p2, &tmp2, Some("")).is_err(), "空串备份必须失败");
    assert_eq!(std::fs::read_to_string(&p2).unwrap(), "a = 1\r\n# 注释\r\nb = \"x\"\r\n");
}

#[cfg(windows)]
#[test]
fn replace_keeps_acl() {
    use std::process::Command;
    let d = tmpdir(); let p = seed(&d);
    let sddl = |path: &std::path::Path| -> String {
        let out = Command::new("powershell").args(["-NoProfile","-Command",
            &format!("(Get-Acl '{}').Sddl", path.to_string_lossy())]).output().unwrap();
        String::from_utf8_lossy(&out.stdout).trim().to_string()
    };
    // 加一条自定义 ACE
    Command::new("icacls").args([p.to_string_lossy().as_ref(), "/grant", "Everyone:(R)"]).output().unwrap();
    let before = sddl(&p);
    atomic_write(&p, "a = 2\r\n# 注释\r\nb = \"x\"\r\n").unwrap();
    assert_eq!(sddl(&p), before, "ReplaceFileW 必须保留目标 ACL");
}
```

（`replace_file_w(path, tmp, backup: Option<&str>)` 作为 `pub(crate)` 辅助函数供测试直接调用；`None` → `std::ptr::null()`，`Some("")` → 空串路径。）

- [ ] **Step 2: 运行确认失败，然后实现**

`atomic_write` 的固定链（顺序不可调换）：

```rust
let tmp = target.with_extension("toml.tmp");   // 同目录，保证同卷
std::fs::write(&tmp, text)?;
let f = std::fs::OpenOptions::new().write(true).open(&tmp)?;
f.sync_all()?;                                  // 落盘再替换
let bak = target.with_extension("toml.bak");
replace_file_w(target, &tmp, Some(bak 的路径))?; // 一步完成替换 + 备份
// 回读校验
let readback = std::fs::read_to_string(target)?;
if set_inject_readback_failure_flag() || ConfigDoc::parse(&readback).is_err() {
    rollback_from_bak(target)?;                 // 用 .bak 作 replacement
    return Err(IoError::ReadbackParse(...));
}
fingerprint(target)
```

`replace_file_w` 用 `windows_sys::Win32::Storage::FileSystem::ReplaceFileW`，前三个参数都转成 `Vec<u16>` 加 NUL 的 `PCWSTR`（`*const u16`）；`backup` 为 `None` 时传 `std::ptr::null()`，第六、七参数（`*const c_void`）也传 `std::ptr::null()`。失败时 `windows_sys::Win32::Foundation::GetLastError()` 取 `WIN32_ERROR`（`u32`），返回 `IoError::ReplaceFailed`。**返回值是 `BOOL`（`i32`），非 0 才是成功**。

**失败收尾**：`ReplaceFileW` 失败后删除 `.tmp`（`let _ = std::fs::remove_file(&tmp);`），原文件与 `.bak` 都保持原样。

`rollback_from_bak`：`ReplaceFileW(target, bak, Some(废弃槽))`，废弃槽用 `config.toml.rollback`，成功后删掉废弃槽。

- [ ] **Step 3: 运行全绿（含 ACL 用例）**

Run: `cargo test --release file_io` — 期望全部 passed。若 ACL 用例因 `icacls` 权限失败，用 `Everyone:(R)` 失败时改为对当前用户 `"$env:USERNAME:(R)"`；仍失败则记录并保留用例（`#[ignore]` 需在计划里注明，不得删除）。

- [ ] **Step 4: Commit**

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(file_io): 指纹、ReplaceFileW 原子提交与回滚' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 7: model_paths_resolve —— 9 个派生只读键

**Files:**
- Create: `edit_config_gui/src-tauri/src/model_paths_resolve.rs`
- Modify: `edit_config_gui/src-tauri/src/lib.rs`

**Interfaces:**
- Consumes: `ConfigDoc`（Task 2）
- Produces:

```rust
/// (派生键 segments, 真实来源键 segments)
pub const DERIVED: [(&[&str], &[&str]); 9];

/// 派生键当前「应当」显示的值；来源键缺失时返回 None。
pub fn resolve(doc: &ConfigDoc, derived: &[String]) -> Option<String>;
```

**没有写入函数**：规格 §6.5 明确「这 9 个键在 TOML 中仍然存在，保存时**不删除、不改写**」。它们只用于在 UI 上显示「实际生效：…」并提供一个跳到 `model_paths` 的链接，因此本任务只有只读解析，不提供任何 sync / 回写占位符的入口——一旦有了写入入口，就会出现「占位符被替换成真实路径」的 config.toml 分叉，那正是本次重构要消灭的旧问题。

映射（规格 §6.5，逐条照抄）：

| 派生键 | 来源键 |
|---|---|
| `funasr_args.encoder_onnx_path` | `model_paths.funasr_encoder_adaptor_path` |
| `funasr_args.ctc_onnx_path` | `model_paths.funasr_ctc_path` |
| `funasr_args.decoder_gguf_path` | `model_paths.funasr_llm_path` |
| `funasr_args.tokens_path` | `model_paths.funasr_tokens_path` |
| `funasr_args.hotwords_path` | `model_paths.funasr_hotwords_path` |
| `sensevoice_args.model` | `model_paths.sensevoice_path` |
| `sensevoice_args.tokens` | `model_paths.sensevoice_tokens_path` |
| `paraformer_args.paraformer` | `model_paths.paraformer_path` |
| `paraformer_args.tokens` | `model_paths.paraformer_tokens_path` |

- [ ] **Step 1: 写失败测试**

```rust
#[test]
fn resolve_all_nine() {
    let (doc, _) = load_real();
    for (derived, source) in DERIVED {
        let d: Vec<String> = derived.iter().map(|s| s.to_string()).collect();
        let s: Vec<String> = source.iter().map(|s| s.to_string()).collect();
        let expect = doc.get(&s).and_then(|i| i.as_str()).unwrap().to_string();
        assert_eq!(resolve(&doc, &d).unwrap(), expect, "{derived:?}");
    }
}

#[test]
fn read_only_resolve_does_not_touch_text() {
    // 解析派生键是纯读操作：不得改写 Item、不得影响 emit 出来的文本
    let (doc, raw) = load_real();
    let before = doc.to_toml_string();
    for (derived, _) in DERIVED {
        let d: Vec<String> = derived.iter().map(|s| s.to_string()).collect();
        let _ = resolve(&doc, &d);          // 只是看一眼
    }
    assert_eq!(doc.to_toml_string(), before, "resolve 不得改动文档");
    assert_eq!(comment_line_count(&raw), 306);
}

#[test]
fn all_nine_are_placeholders_in_toml() {
    // 9 个派生键在 TOML 里必须仍是 ${...} 占位符；若哪天被同步成真实路径，
    // 说明有人加了写入入口 —— 那是配置文件分叉，必须在这里红掉
    let (doc, _) = load_real();
    for (derived, _) in DERIVED {
        let d: Vec<String> = derived.iter().map(|s| s.to_string()).collect();
        let got = doc.get(&d).and_then(|i| i.as_str()).unwrap();
        assert!(got.starts_with("${model_paths."), "{derived:?} = {got}");
    }
}
```

- [ ] **Step 2: 运行确认失败，然后实现**

`resolve` 只读来源键：按 `DERIVED` 找到来源 segments → `doc.get(&source)` → `as_str()` → 返回 `Some(String)`；任一环节缺失就返回 `None`（不许 `unwrap`，配置可能被用户手工删掉键）。

- [ ] **Step 3: 跑绿并提交**

Run: `cargo test --release model_paths_resolve` → 3 passed（`resolve_all_nine`、`read_only_resolve_does_not_touch_text`、`all_nine_are_placeholders_in_toml`）。

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(model_paths): 九个派生只读键的只读解析' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 8: process —— 运行检测与受限重启

**Files:**
- Create: `edit_config_gui/src-tauri/src/process.rs`
- Modify: `edit_config_gui/src-tauri/src/lib.rs`

**Interfaces:**
- Consumes: 无
- Produces:

```rust
#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ServiceTarget { Server, Client }

pub struct RunningInfo { pub server: bool, pub client: bool, pub client_variant: Option<String>, pub is_admin: bool }

pub fn detect() -> RunningInfo;

/// 进程名匹配：双向去 `.exe` + 小写比较
pub fn name_matches(exe_name: &str, target: &str) -> bool;

/// 结束 → 以 base_dir 为 cwd 重新拉起。base_dir 必须由调用方传 config.toml 父目录。
pub fn restart(target: ServiceTarget, base_dir: &std::path::Path, variant: Option<&str>) -> Result<RestartOutcome, ProcError>;

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RestartOutcome { pub degraded: bool }

/// 纯判定，不启动任何进程：名称必须与白名单中的某个字面量完全相等
pub fn is_whitelisted(name: &str) -> bool;

/// 只允许白名单里的字面量；路径、`..`、绝对路径一律 Err。内部先过 `is_whitelisted`。
pub fn restart_launcher(name: &str, base_dir: &std::path::Path) -> Result<RestartOutcome, ProcError>;

pub enum ProcError { NotWhitelisted(String), Spawn(String), Kill(String), Downgrade(String) }
```

白名单（规格 §9.4，逐个照抄）：

```rust
/// 「在跑就显示」的检测名单，含非启动器进程
const SERVER_PROCS: [&str; 3] = ["start_server_gui.exe", "python_capswriter_server.exe", "deeplx_windows_amd64.exe"];
const CLIENT_PROCS: [&str; 4] = ["start_client_gui_admin.exe", "start_client_gui.exe", "python_capswriter_client.exe", "hint_while_recording.exe"];

/// 「允许被拉起」的启动器，比上面窄：`is_whitelisted` 只认这三个字面量
const LAUNCHERS: [&str; 3] = ["start_server_gui.exe", "start_client_gui.exe", "start_client_gui_admin.exe"];
```

> 两个清单**职责不同**，不能合并：`SERVER_PROCS`/`CLIENT_PROCS` 只用于 `detect()` 判断「在不在跑」（大小写不敏感、`.exe` 可省）；`LAUNCHERS` 只用于 `restart_launcher()` 决定「能不能被拉起」（精确字面量相等）。`python_CapsWriter_Server.exe`、`hint_while_recording.exe`、`deeplx_windows_amd64.exe` 只进前者，永不进后者——否则前端一旦被注入，就能借这个命令启动任意白名单外的可执行文件。

- [ ] **Step 1: 写失败测试**

```rust
#[test]
fn whitelist_has_no_core_scripts() {
    // core_server.py / core_client.py 不是启动器，不得作为匹配目标
    for n in SERVER_PROCS.iter().chain(CLIENT_PROCS.iter()) {
        assert!(!n.contains("core_"), "{n}");
    }
}

#[test]
fn name_match_rules() {
    assert!(name_matches("start_server_gui.exe", "start_server_gui"));
    assert!(name_matches("Start_Server_GUI.EXE", "start_server_gui.exe"));
    assert!(!name_matches("start_server_gui_admin.exe", "start_server_gui"));
    assert!(!name_matches("python.exe", "start_server_gui"));
}

#[test]
fn detect_does_not_panic() {
    let info = detect();
    let _ = (info.server, info.client, info.client_variant, info.is_admin);
}

#[test]
fn whitelist_rejects_path_like_names() {
    // 这条测试只调用纯判定函数，不会启动任何进程
    for bad in [
        r"C:\Windows\System32\cmd.exe",
        r"..\..\evil.exe",
        r".\start_server_gui.exe",
        r"start_server_gui.exe ",        // 尾随空格
        r"START_SERVER_GUI.EXE",         // 大小写与字面量不同，必须被拒（前端只能传枚举）
        r"start_server_gui_admin.exe",   // 客户端变体，不在服务端启动器白名单
        "",
    ] {
        assert!(!is_whitelisted(bad), "{bad:?} 不应通过白名单");
    }
}

#[test]
fn whitelist_accepts_exact_literal_names() {
    assert!(is_whitelisted("start_server_gui.exe"));
    assert!(is_whitelisted("start_client_gui.exe"));
    assert!(is_whitelisted("start_client_gui_admin.exe"));
    // 被「检测」的进程不等于「启动器」：python_CapsWriter_Server.exe 只能被 kill，不能作为启动目标
    assert!(!is_whitelisted("python_CapsWriter_Server.exe"));
    assert!(!is_whitelisted("hint_while_recording.exe"));
    assert!(!is_whitelisted("deeplx_windows_amd64.exe"));
}
```

- [ ] **Step 2: 实现**

`name_matches(exe_name, target)`：双向去 `.exe` + `to_lowercase()` 比较。

`detect()`：`sysinfo::System::new()` + `refresh_processes(sysinfo::ProcessesToUpdate::All, true)` 遍历 `p.name()`（0.39 返回 `&OsStr`，用 `.to_string_lossy()`），与白名单比对。`client_variant` 记录命中的是 `start_client_gui_admin.exe` 还是 `start_client_gui.exe`。`is_admin`：`windows_sys::Win32::UI::Shell::IsUserAnAdmin()`（已实测返回 `i32`，非 0 为管理员；`Win32_UI_Shell` feature 已在 Cargo.toml 里给出）。

`restart()`：先 `taskkill /IM <exe> /F` 逐个杀掉命中的进程（`std::process::Command`，参数分离，不经 shell），再 `CreateProcessW` 拉起启动器，`lpCurrentDirectory` 显式设为 `base_dir`。
服务端启动器固定 `start_server_gui.exe`；客户端按 `variant` 选 `start_client_gui_admin.exe` 或 `start_client_gui.exe`（都没跑则用后者）。
`restart_launcher(name, base_dir)`：先 `if !is_whitelisted(name) { return Err(ProcError::NotWhitelisted(name.into())) }`，否则 `CreateProcessW`。
**降权**：当前进程是管理员时，服务端启动必须走 `ShellExecuteExW` + `runas` 是不可接受的（会再弹 UAC）；本计划采用与 `util/explorer_token_downgrade.py` 等价的实现：`GetShellWindow` → `GetWindowThreadProcessId` → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` → `OpenProcessToken(TOKEN_DUPLICATE|TOKEN_QUERY)` → `DuplicateTokenEx` → `CreateProcessWithTokenW`。若该链路任一步失败，**降级为直接 `CreateProcessW` 并在返回值里带上 `degraded: true` 让 UI 提示**，不允许静默假装成功。

> `windows-sys` 的符号归属按 Global Constraints 里的实测结论导入：`OpenProcessToken` 在 `Win32::System::Threading`。

- [ ] **Step 3: 跑绿并提交**

Run: `cargo test --release process` → 5 passed（`whitelist_has_no_core_scripts`、`name_match_rules`、`detect_does_not_panic`、`whitelist_rejects_path_like_names`、`whitelist_accepts_exact_literal_names`）。

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(process): 服务进程检测与受限重启' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 9: commands —— 七个 IPC 命令与状态装配

**Files:**
- Create: `edit_config_gui/src-tauri/src/commands.rs`
- Modify: `edit_config_gui/src-tauri/src/lib.rs`（`manage` 状态 + `invoke_handler` 注册 7 个命令）

**Interfaces:**
- Consumes: `config_doc` / `patch` / `validate` / `file_io` / `process` / `model_paths_resolve`
- Produces（前端 `bridge.ts` 一对一依赖这些名字与字段）：

```rust
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocState {
    pub path: String,
    pub fingerprint: file_io::FileFingerprint,
    pub fields: Vec<FieldView>,      // segments / value(JSON) / tomlType
    pub base_dir: String,
}
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FieldView { pub segments: Vec<String>, pub value: serde_json::Value, pub toml_type: String }
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewResult { pub diff: String, pub errors: Vec<Problem>, pub warnings: Vec<Problem>, pub changed: Vec<Vec<String>> }
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Problem { pub segments: Vec<String>, pub message: String }
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommitResult { pub fingerprint: file_io::FileFingerprint, pub backup_path: String }

/// config.toml 定位：命令行参数 > exe 同目录 > cwd；全失败返回 IoError::NotFound 且不创建文件
pub(crate) fn locate(cli: Option<&std::path::Path>, exe_dir: &std::path::Path, cwd: &std::path::Path) -> Result<std::path::PathBuf, file_io::IoError>;

#[tauri::command] async fn open_config(state: State<'_, AppState>, path: Option<String>) -> Result<DocState, String>;
#[tauri::command] async fn pick_path(app: tauri::AppHandle, state: State<'_, AppState>, mode: String, title: String) -> Result<Option<String>, String>;
#[tauri::command] async fn preview_save(state: State<'_, AppState>, patches: Vec<patch::Patch>, rules: Vec<validate::FieldRule>) -> Result<PreviewResult, String>;
#[tauri::command] async fn commit_save(state: State<'_, AppState>, patches: Vec<patch::Patch>, rules: Vec<validate::FieldRule>, fingerprint: file_io::FileFingerprint, force: bool) -> Result<CommitResult, String>;
#[tauri::command] async fn reload_config(state: State<'_, AppState>) -> Result<DocState, String>;
#[tauri::command] async fn running_processes() -> Result<process::RunningInfo, String>;
#[tauri::command] async fn restart_service(state: State<'_', AppState>, target: process::ServiceTarget) -> Result<process::RestartOutcome, String>;
```

- [ ] **Step 1: 写失败测试**

```rust
use super::*;
use crate::testutil::{seg, tmpdir, seed, patch};
use crate::patch::PatchValue;

#[test]
fn config_location_precedence() {
    let d = tmpdir();
    let exe_dir = d.join("bin"); std::fs::create_dir_all(&exe_dir).unwrap();
    let cwd = d.join("cwd"); std::fs::create_dir_all(&cwd).unwrap();
    let cli = d.join("cli.toml"); std::fs::write(&cli, "a = 1\r\n").unwrap();
    let in_exe = exe_dir.join("config.toml"); std::fs::write(&in_exe, "a = 2\r\n").unwrap();

    // ① 命令行参数优先
    assert_eq!(locate(Some(&cli), &exe_dir, &cwd).unwrap(), cli);
    // ② exe 同目录
    assert_eq!(locate(None, &exe_dir, &cwd).unwrap(), in_exe);
    // ③ cwd 兜底
    let in_cwd = cwd.join("config.toml"); std::fs::write(&in_cwd, "a = 3\r\n").unwrap();
    assert_eq!(locate(None, &d.join("empty"), &cwd).unwrap(), in_cwd);
    // ④ 都没有 → NotFound，且不得创建文件
    let empty2 = d.join("empty2");
    let nf = locate(None, &empty2, &d.join("empty3"));
    assert!(matches!(nf, Err(crate::file_io::IoError::NotFound(_))));
    assert!(!empty2.exists() && !empty2.join("config.toml").exists(), "定位失败不得创建文件");
}

#[test]
fn toml_type_is_camel_string() {
    use crate::config_doc::{toml_type_name, TomlType};
    assert_eq!(toml_type_name(TomlType::String), "string");
    assert_eq!(toml_type_name(TomlType::Integer), "integer");
    assert_eq!(toml_type_name(TomlType::Float), "float");
    assert_eq!(toml_type_name(TomlType::Boolean), "boolean");
    assert_eq!(toml_type_name(TomlType::Array), "array");
    assert_eq!(toml_type_name(TomlType::InlineTable), "inlineTable");
}

#[test]
fn preview_does_not_write() {
    let d = tmpdir();
    let p = seed(&d);
    let before = std::fs::read_to_string(&p).unwrap();
    let doc = crate::config_doc::ConfigDoc::load(&p).unwrap();
    let mut copy = crate::config_doc::ConfigDoc::parse(doc.original_text()).unwrap();
    crate::patch::apply(&mut copy, &[crate::testutil::patch(&["a"], PatchValue::Int(9))]).unwrap();
    let diff = crate::patch::unified_diff(doc.original_text(), &copy.to_toml_string());
    assert!(!diff.is_empty());
    assert_eq!(std::fs::read_to_string(&p).unwrap(), before, "preview 不得写盘");
    assert!(!d.join("config.toml.bak").exists());
}
```

- [ ] **Step 2: 实现**

`locate(cli: Option<&Path>, exe_dir: &Path, cwd: &Path)` 严格按 ①②③，全失败返回 `NotFound` 且**绝不创建文件**。

`open_config`：`locate` 后用当前 `%CD%` 或 `std::env::current_exe()?.parent()` 得 `exe_dir`，`std::env::current_dir()` 得 `cwd`；把 `ConfigDoc`、`base_dir = path.parent()`、`fingerprint` 存进 `AppState`（`Mutex<Option<Session>>`）。

`preview_save`：从 `AppState` 的 `original_text` **重新 parse 一份副本**（不碰已存文档），`apply` 补丁，`validate_all` 得 errors/warnings，`unified_diff(original_text, after)`。**全程不写盘。** 注意：9 个派生只读键永远不在 `patches` 里（前端不产生它们的补丁），这里也**不做**任何占位符回写。

`commit_save`：①`force == false` 时重新 `fingerprint(path)` 与传入的比，不等则 `Err("CONFLICT")`；②重新 parse + apply + validate_all，有 errors 直接拒绝（不写盘）；③`atomic_write`；④更新 `AppState` 的文档与指纹，返回新指纹与 `.bak` 路径。

`restart_service`：先 `running_processes()` 判断当前跑的是哪个客户端变体（`start_client_gui_admin.exe` 还是 `start_client_gui.exe`），再 `process::restart(target, base_dir, variant)`；`base_dir` 只能来自 `AppState`（不接受前端传路径）。把 `RestartOutcome { degraded }` 原样返回给前端，`degraded == true` 时状态栏必须显示降权失败提示，**不得**把它吞成成功。

`pick_path`：`app.dialog().file().set_title(title).blocking_pick_file()/blocking_pick_folder()`（`mode == "dir"` 用后者），`.into_path()` 转 `PathBuf` 再 `to_string_lossy()`。因为用了 `blocking_*`，命令必须是 `async` 且由 Tauri 在非主线程执行。

- [ ] **Step 3: 跑绿**

Run: `cargo test --release` → 全部通过（含前面所有任务）。

- [ ] **Step 4: Commit**

```powershell
git add edit_config_gui/src-tauri
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(commands): 七个 IPC 命令与文档状态装配' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 10: 前端 schema 基础 —— 类型、debug 与 server

**Files:**
- Create: `edit_config_gui/src/lib/schema/types.ts`
- Create: `edit_config_gui/src/lib/schema/server.ts`
- Create: `edit_config_gui/src/lib/schema/index.ts`（先只汇总 server，后续任务追加）

**Interfaces:**
- Consumes: 无
- Produces:

```ts
export type JsonValue = string | number | boolean | JsonValue[] | { [k: string]: JsonValue };

/** 对应规格 §5.1 的 ValueType */
export type ValueType = 'string' | 'integer' | 'float' | 'boolean' | 'stringArray' | 'pairArray' | 'inlineTable';
export type ValidatorId = 'ip' | 'localListenableIp' | 'port' | 'fileExist' | 'dirExist'
  | 'hotkey' | 'url' | 'singleLine' | 'ipPort' | 'regexClass';
export type WidgetKind = 'text' | 'int' | 'float' | 'bool' | 'enum' | 'path'
  | 'hotkey' | 'stringList' | 'pairList' | 'longText'
  | 'secret' | 'readonly' | 'dynamicTable';

export interface FieldMeta {
  /** 点分路径，仅用于展示与搜索；定位一律用 segments */
  path: string;
  segments: string[];
  title: string;
  note?: string;                 // 来自 config.toml 的注释原文
  type: ValueType;
  widget: WidgetKind;
  default?: JsonValue;
  options?: { value: string; label: string }[];
  min?: number; max?: number; step?: number;
  validators?: ValidatorId[];
  allowEmpty?: boolean;
  pathMode?: 'file' | 'directory';
  fileSuffix?: string;
  visibleWhen?: { segments: string[]; equals?: JsonValue; in?: JsonValue[] };
  /** 只读派生：真实生效位置（segments） */
  derivedFrom?: string[];
  aliases?: string[];            // 搜索同义词（规格 §9.7.2）
  /** 规格 §5.1 未列出、本计划新增：该字段的校验失败只警告不阻断（用于 model_paths.*，见规格 §9.3） */
  warnOnly?: boolean;
}
export interface SectionMeta { id: string; title: string; note?: string; fields: FieldMeta[] }
export interface PageMeta { id: string; title: string; icon: string; sections: SectionMeta[] }
```

> 与规格 §5.1 的差异只有两处，均为实现必需：①两处都用 `segments: string[]` 定位（规格 §5.2 已要求 FieldMeta 同时携带 segments，此处把 `path` 降为展示字段）；②新增 `warnOnly?: boolean`，让「`model_paths.*` 校验失败只警告」能声明式表达（规格 §9.3/§6.4 的要求），不必在 Rust 里硬编码路径前缀。

- [ ] **Step 1: 写 `types.ts` 与 `server.ts`（`debug` 1 键 + `server` 15 键）**

`server.ts` 导出 `const serverPages: PageMeta[]`。`debug` 段 1 个键：
`debug.logger_level` → `enum`，选项 `TRACE 5 / DEBUG 10 / INFO 20 / SUCCESS 25 / WARNING 30 / ERROR 40 / CRITICAL 50`（label 写「级别名称 (数字)」），`default: 'ERROR'`。

`server` 段的 **15 个键**（已用 `tomllib` 从 `config.toml` 实测，逐个照抄，不得增删）：

| 键 | widget | type | 额外 |
|---|---|---|---|
| `model` | `enum` | string | 选项 `FunASR`/`Sensevoice`/`Paraformer`，`default:'FunASR'` |
| `expand_funasr_hotwords` | `bool` | boolean | `visibleWhen: { segments:['server','model'], equals:'FunASR' }` |
| `addr` | `text` | string | `validators:['localListenableIp']`，`default:'0.0.0.0'` |
| `speech_recognition_port` | `text` | string | `validators:['port']`，`default:'6016'`（**写回字符串**） |
| `check_port_usage_before_start` | `bool` | boolean | `default:false` |
| `start_online_translate_server` | `bool` | boolean | `default:true` |
| `start_offline_translate_server` | `bool` | boolean | `default:true` |
| `offline_translate_port` | `text` | string | `validators:['port']`，`default:'6017'`，`visibleWhen: start_offline_translate_server === true` |
| `format_num` | `bool` | boolean | `default:true` |
| `format_punc` | `bool` | boolean | `default:true`，`visibleWhen: { segments:['server','model'], equals:'Paraformer' }` |
| `format_spell` | `bool` | boolean | `default:true` |
| `shrink_automatically_to_tray` | `bool` | boolean | `default:true` |
| `only_run_once` | `bool` | boolean | `default:true` |
| `in_the_meantime_start_the_client` | `bool` | boolean | `default:true` |
| `in_the_meantime_start_the_client_and_run_as_admin` | `bool` | boolean | `default:true`，`visibleWhen: in_the_meantime_start_the_client === true` |

`server.model` 的三分支显隐**已实测确认**（`util/edit_config_gui/server_config_page.py:448-457` `model_changed`）：`Paraformer` → `format_punc` 显示 / `expand_funasr_hotwords` 隐藏；`Sensevoice` → 两个都隐藏；其余（`FunASR`）→ `format_punc` 隐藏 / `expand_funasr_hotwords` 显示。因此两条 `visibleWhen` 都是单一 `equals`，**不需要 `in` 数组**：`format_punc` 用 `{ segments:['server','model'], equals:'Paraformer' }`，`expand_funasr_hotwords` 用 `{ segments:['server','model'], equals:'FunASR' }`。`types.ts` 的 `visibleWhen` 仍保留 `in?: JsonValue[]` 供后续页面使用，但服务端页不依赖它。

- [ ] **Step 2: 写 `index.ts` 骨架**

```ts
import type { PageMeta } from './types';
export * from './types';
export const pages: PageMeta[] = [];
export function allFields() { return pages.flatMap(p => p.sections.flatMap(s => s.fields)); }
export function fieldById(id: string) { return allFields().find(f => f.segments.join('\u0000') === id); }
export const fieldId = (segments: string[]) => segments.join('\u0000');
```

- [ ] **Step 3: 跑 `pnpm check` 确认类型通过并提交**

Run: `cd edit_config_gui; pnpm check` — 期望 `0 errors 0 warnings`。此时还没有测试文件，`pnpm test` 会因 `--passWithNoTests` 而退出 0，属正常。

```powershell
cd edit_config_gui && pnpm check
git add edit_config_gui/src/lib/schema
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(schema): 字段元数据类型与 server/debug 页' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```
---

### Task 11: 前端 schema —— client 主表 72 键

**Files:**
- Create: `edit_config_gui/src/lib/schema/client.ts`
- Modify: `edit_config_gui/src/lib/schema/index.ts`

**Interfaces:**
- Consumes: `types.ts`（Task 10）
- Produces: `export const clientSections: SectionMeta[]`，含 6 个分组（规格 §6.1 的「客户端」页）：通用 / 语音识别 / 简繁转换 / 离线翻译 / 在线翻译 / 文件转录。

- [ ] **Step 1: 写 `client.ts`**

按旧 GUI 分组名（`通用 / 语音识别 / 简繁转换 / 离线翻译 / 在线翻译 / 文件转录`，出处 `util/edit_config_gui/client_config_page.py` 的 `SiTitledWidgetGroup` 标题）组织 72 个键。必须按规格 §6.3 显式指定控件的键：

| 键 | widget | 额外 |
|---|---|---|
| `addr` | `text` | `validators:[{id:'ip'}]`（**注意：不是 localListenableIp**，见规格 §1.4） |
| `speech_recognition_port` / `offline_translate_port` / `offline_translate_port_gemma2b` | `text` | `type:'string'` + `port` |
| `threshold` | `float` | `min:0.1 max:2.0 step:0.1`，单位秒 |
| `audio_name_len` | `int` | 10–200 |
| `mic_seg_duration` | `int` | 10–60 |
| `mic_seg_overlap` | `int` | 0–10 |
| `file_seg_duration` | `int` | 10–60 |
| `file_seg_overlap` | `int` | 1–60 |
| `start_music_volume` / `stop_music_volume` | `int` | 0–100，`type:'string'`（写回字符串） |
| `start_music_path` / `stop_music_path` | `path` | `fileExist`，`warnOnly:true` |
| `check_microphone_usage_by` | `enum` | 注册表 / 按键 |
| `online_translate_target_languages` | `enum` | JA/EN/RU/FR/KO |
| `online_translate_target_languages_libretranslate` | `enum` | zh/en/ru/fr/ko |
| `ai_provider` | `enum` | openai/zhipuai（决定 AI 页显示哪一组，用 `visibleWhen`） |
| `prompt_style_selection` | `enum` | 8 个风格，默认 `english` |
| `convert_to_traditional_chinese_main` | `enum` | 简 / 繁（值为 `简`/`繁`） |
| `opencc_converter` | `text` | 默认 `s2t` |
| `trash_punc` | `text` | `validators:[{id:'regexClass'}]` |
| `adb_addr` | `text` | `validators:[{id:'ipPort'}]` + `visibleWhen: {segments:['client','enable_adb_control'], equals:true}` |
| `disable_exe_list` / `disable_exe_list_on_focus` | `stringList` | 空串占位数组 |
| `enter_apps` | `pairList` | |
| `QQMusic_global_pause_hotkey` 等 4 个 | `hotkey` | `allowEmpty:true` |
| `多音字` / `声调` | `bool` | 键名含非 ASCII，必须原样写入 `segments` |

条件显隐必须用 `visibleWhen` 声明（不得写 `if` 分支）。**以下是逐条实测出来的 11 组依赖**（出处 `util/edit_config_gui/client_config_page.py:1815-1897` 的 9 个 `*_changed` 处理器），逐组写进对应字段：

| 开关字段（触发） | 受影响字段（`visibleWhen` 引用开关 = true 时显示） |
|---|---|
| `play_start_music` | `start_music_path`、`start_music_volume` |
| `play_stop_music` | `stop_music_path`、`stop_music_volume` |
| `pause_other_audio` | `QQMusic_global_pause_hotkey`、`CloudMusic_global_pause_hotkey`、`PotPlayer_global_pause_hotkey`、`foobar2000_global_pause_hotkey` |
| `hint_while_recording_at_cursor_position` | `check_microphone_usage_by` |
| `save_markdown` | `save_non_kwd_markdown` |
| `paste` | `restore_clipboard_after_paste` |
| `hold_mode` | `suppress` |
| `save_audio` | `audio_name_len`、`reduce_audio_files` |
| `use_offline_translate_function` | `offline_translate_port`、`offline_translate_shortcut` |
| `use_online_translate_function` | `online_translate_shortcut`、`online_translate_target_languages`、`online_translate_target_languages_libretranslate` |
| `enable_adb_control` | `adb_addr` |

`convert_to_traditional_chinese_main` 是**值联动**而非显隐（旧 GUI `:1855-1859` 只是把按钮文字在「繁/简」间切换），在本计划里它就是一个 `enum`，不需要 `visibleWhen`。
`enable_ai_optimize_language_expression` 的旧处理器 `:1899-1903` 两个分支都是 `...`（空实现），**不产生任何显隐**，AI 服务商页与提示风格页始终可见；是否按它隐藏整页属于新增行为，规格 §6.1 未要求，故不做。
以上字段全部在 `client` 段内引用，**没有跨段依赖**；服务端页的跨段引用（`visibleWhen` 读 `server.*`）只出现在服务端页自己的 15 个键里。

- [ ] **Step 2: 修改 `index.ts` 把 client 页并入 `pages`**

`index.ts` 里 `pages` 数组按规格 §6.1 的 13 页顺序排列，此时只到第 2 页：

```ts
export const pages: PageMeta[] = [serverPage, clientPage];
```

`clientPage` 的 `sections` 顺序必须是：通用 → 语音识别 → 简繁转换 → 离线翻译 → 在线翻译 → 文件转录 → AI 优化语言表达（沿用旧 GUI 的分区名，规格 §6.1）。同一 `section` 内的 `fields` 顺序按 `config.toml` 里出现顺序排列——这样即使将来用户重新保存，diff 的阅读顺序也和 TOML 一致。

- [ ] **Step 3: `pnpm check` 并提交**

Run: `cd edit_config_gui; pnpm check` — 期望 `0 errors 0 warnings`（`client.ts` 里的 72 个 `FieldMeta` 全部与 `types.ts` 对齐，尤其是 `type` 与 `widget` 的组合不漏字段）。

```powershell
git add edit_config_gui/src/lib/schema
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(schema): 客户端 72 键元数据与声明式显隐' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 12: 前端 schema 完成 —— 其余 8 页 + 覆盖断言

**Files:**
- Create: `edit_config_gui/src/lib/schema/aiProviders.ts`（5 键）
- Create: `edit_config_gui/src/lib/schema/promptStyles.ts`（16 键）
- Create: `edit_config_gui/src/lib/schema/additionalApps.ts`（动态表）
- Create: `edit_config_gui/src/lib/schema/translate.ts`（libretranslate 1 + deeplx 3）
- Create: `edit_config_gui/src/lib/schema/modelPaths.ts`（13 键）
- Create: `edit_config_gui/src/lib/schema/modelArgs.ts`（funasr 15 + sensevoice 12 + paraformer 7）
- Create: `edit_config_gui/scripts/gen-schema-paths.mjs`
- Create: `edit_config_gui/src/lib/schema/coverage.test.ts`
- Create: `edit_config_gui/src-tauri/tests/schema_paths.json`（脚本产物，提交）
- Create: `edit_config_gui/src-tauri/tests/coverage.rs`
- Modify: `edit_config_gui/src/lib/schema/index.ts`

**Interfaces:**
- Consumes: 全部 `types.ts`
- Produces: `pages` 完整 13 页；`export function derivedFields(): { segments: string[]; from: string[] }[]`（9 条）。

- [ ] **Step 1: 写 6 个 schema 文件**

`aiProviders.ts`（5 键）：`client.zhipuai.api_key`（`secret`）、`zhipuai.model`（`text`）、`client.openai.api_key`（`secret`）、`openai.base_url`（`text` + `url`）、`openai.model`（`text`）。
`promptStyles.ts`（16 键）：8 个 `prompt_*` 用 `longText`（`allowEmpty:true`，**不加 `singleLine`**），8 个 `prompt_*_shortcut` 用 `hotkey`（`allowEmpty:true`），按风格两两成对分 Section。
`additionalApps.ts`：`widget:'dynamicTable'`，`type:'inlineTable'`，`segments:['client','additional_special_apps']`（这是唯一的动态表，它的条目不进固定 schema，因此覆盖断言要把它排除）。
`translate.ts`（4 键，键名逐字照抄 config.toml:677/688/691/694）：`libretranslate.api`（`text` + `url`）；`deeplx.api`（`text` + `url`）、`deeplx.online_translate_port`（`text` + `port`，`type:'string'`）、`deeplx.exe_path`（`path` + `fileExist`，`fileSuffix:'.exe'`）。
`modelPaths.ts`（13 键，后缀逐字照抄规格 §6.4 的表）：4 个目录 model_dir/funasr_dir/punc_model_dir/opus_mt_dir（`pathMode:'directory'` + `dirExist`，`warnOnly:true`）+ 9 个文件，fileSuffix 依次为 `.onnx`/`.onnx`/`.gguf`/`.txt`/`.txt`/`.onnx`/`.txt`/`.onnx`/`.txt`（对应 funasr_encoder_adaptor_path / funasr_ctc_path / funasr_llm_path / funasr_tokens_path / funasr_hotwords_path / sensevoice_path / sensevoice_tokens_path / paraformer_path / paraformer_tokens_path），全部 `warnOnly:true`。
`modelArgs.ts`：funasr 15 键里的 5 个派生键用 `readonly`（`derivedFrom` 由 `derivedFields()` 提供）；`n_predict` 1–2048、`n_threads` 0–32、`similar_threshold` 0.3–1.0 step 0.1、`max_hotwords` 1–100；sensevoice/paraformer 的 `num_threads` 1–32、`feature_dim` 1–1024、`sample_rate` enum 16000/44100/48000（`type:'integer'`）、`provider` enum cpu/cuda/coreml、`language` enum auto/zh/en/ja/ko/yue。

第 13 页「关于」不进 `pages[].sections[].fields`（它没有可编辑字段，`fields: []`），由 `aboutPage` 单独定义并追加到 `pages` 末尾：`id:'about'`、`title:'关于'`、`sections: []`。页面内容由 Task 16 的 `PageView` 对 `page.id === 'about'` 特判渲染（程序版本、`config.toml` 绝对路径、项目地址、旧 GUI 迁移说明），不占用任何 `FieldMeta`。
**因此 `pages` 的 13 页顺序是**：`server` / `client` / `aiProviders` / `promptStyles` / `additionalApps` / `libretranslate` / `deeplx` / `modelPaths` / `funasr` / `sensevoice` / `paraformer` / `debug` / `about`。其中 `server` 与 `debug` 两页都来自 `server.ts` 的 `serverPages`（Task 10），其余见上文各文件。

**页 id 与标题的权威表**（`navStore.focus()` 的反查、`Sidebar` 的测试、`PageView` 的 about 特判都依赖这张表，不得改名）：

| # | `PageMeta.id` | `title` | 来源文件 | 键数 |
|---|---|---|---|---|
| 1 | `server` | 服务端 | `server.ts` | 15 |
| 2 | `client` | 客户端 | `client.ts` | 72 |
| 3 | `aiProviders` | AI 服务商 | `aiProviders.ts` | 5 |
| 4 | `promptStyles` | 提示风格 | `promptStyles.ts` | 16 |
| 5 | `additionalApps` | 附加特殊应用 | `additionalApps.ts` | 动态 |
| 6 | `libretranslate` | LibreTranslate | `translate.ts` | 1 |
| 7 | `deeplx` | DeepLX | `translate.ts` | 3 |
| 8 | `modelPaths` | 模型路径 | `modelPaths.ts` | 13 |
| 9 | `funasr` | FunASR 参数 | `modelArgs.ts` | 15 |
| 10 | `sensevoice` | SenseVoice 参数 | `modelArgs.ts` | 12 |
| 11 | `paraformer` | Paraformer 参数 | `modelArgs.ts` | 7 |
| 12 | `debug` | 调试 | `server.ts` | 1 |
| 13 | `about` | 关于 | `index.ts`（内联 `aboutPage`） | 0（静态） |

Step 3 的 `coverage.test.ts` 里有一条硬断言把这张表钉死（页数 13、id 顺序逐项相等、id 全局唯一、每个页都有 title/icon），见下文。

- [ ] **Step 2: 写 `gen-schema-paths.mjs` 并生成 `schema_paths.json`**

```js
import { writeFileSync } from 'node:fs';
import { pages, derivedFields } from '../src/lib/schema/index.ts';

// 三段互斥的拆分，合计必须等于固定叶子数 160：
//   ① 普通可编辑字段  ② 9 个派生只读字段（在 pages 里也要出现，才能渲染成只读控件）
//   ③ 动态表（不为每个条目建索引项，整体排除）
// 注意：derivedFields() 与 pages 里的 readonly 字段**是同一批 9 个键**，
// 所以必须把 readonly 从 pages 侧剔掉再并进来，否则 160 会算成 169。
const fixed = pages
  .flatMap(p => p.sections.flatMap(s => s.fields))
  .filter(f => f.widget !== 'dynamicTable' && f.widget !== 'readonly');
const readonly = pages
  .flatMap(p => p.sections.flatMap(s => s.fields))
  .filter(f => f.widget === 'readonly');
const derived = derivedFields();

// 双向校验：pages 里的 readonly 集合与 derivedFields() 必须逐项相等
const key = (s) => JSON.stringify(s);
const a = readonly.map(f => key(f.segments)).sort();
const b = derived.map(d => key(d.segments)).sort();
if (JSON.stringify(a) !== JSON.stringify(b)) {
  console.error('readonly 字段与 derivedFields() 不一致：', { readonly: a, derived: b });
  process.exit(1);
}

const out = [...fixed, ...derived]
  .map(d => key(d.segments ?? d))
  .sort();
writeFileSync(new URL('../../src-tauri/tests/schema_paths.json', import.meta.url),
  '[\n  ' + out.join(',\n  ') + '\n]\n');
console.log('fixed:', fixed.length, 'derived:', derived.length, 'paths:', out.length);
```

Run: `node scripts/gen-schema-paths.mjs` — 期望 `fixed: 151 derived: 9 paths: 160`。
（151 + 9 = 160 = `leaf_fields()` 的 162 减去动态表的 2 条。已用 `tomllib` 实测：`configs/default config.toml` 共 162 叶子，其中 `client.additional_special_apps.vlc.exe.hotkey` 与 `.name` 是仅有的 2 条动态条目；剩下 160 里恰有 9 个是派生占位键。）
（Node 24 可直接 import `.ts`；`package.json` 已有 `"type": "module"`，不会报警告。若遇到 `ERR_UNKNOWN_FILE_EXTENSION`，改用 `pnpm build` 后的 `dist` 产物不现实，此时把 `index.ts` 的纯数据部分拆成 `data.json` 导出——**优先**确认 node 版本 ≥ 22.6 的 strip-types 生效。）

- [ ] **Step 3: 写前端覆盖测试**

```ts
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { pages, derivedFields, fieldId } from './index';

describe('schema 覆盖率', () => {
  // 可编辑字段 + 派生只读字段 + 动态表 三段互斥，合计必须是 162 个叶子键的等价值：
  // 151（可编辑，不含 9 个派生、不含 1 个动态表入口）+ 9（派生只读）+ 2（动态表 vlc.exe 的 hotkey/name）
  it('与构建期生成的 schema_paths.json 完全一致', () => {
    const raw = readFileSync(new URL('../../../src-tauri/tests/schema_paths.json', import.meta.url), 'utf8');
    const file: string[] = JSON.parse(raw);
    const allFields = pages.flatMap(p => p.sections.flatMap(s => s.fields));
    // readonly 字段就是 derivedFields() 那 9 个，不能重复计入（否则 160 会变成 169）
    const editable = allFields.filter(f => f.widget !== 'dynamicTable' && f.widget !== 'readonly');
    const mine = [
      ...editable.map(f => f.segments),
      ...derivedFields().map(d => d.segments),
    ].map(s => JSON.stringify(s)).sort();
    expect(mine).toEqual(file);
    expect(editable.length).toBe(151);
    expect(derivedFields().length).toBe(9);
    expect(file.length).toBe(160);
  });

  it('segments 全局唯一', () => {
    const all = pages.flatMap(p => p.sections.flatMap(s => s.fields)).map(f => fieldId(f.segments));
    expect(new Set(all).size).toBe(all.length);
  });

  it('派生字段的 from 指向真实字段', () => {
    const ids = new Set(pages.flatMap(p => p.sections.flatMap(s => s.fields)).map(f => fieldId(f.segments)));
    for (const d of derivedFields()) expect(ids.has(fieldId(d.from))).toBe(true);
  });

  it('同段内 title 不重复，且每个字段都有 title', () => {
    for (const page of pages) {
      for (const section of page.sections) {
        const titles = section.fields.map(f => f.title);
        expect(titles.every(t => t.length > 0), `${page.id}/${section.id} 有空标题`).toBe(true);
        expect(new Set(titles).size, `${page.id}/${section.id} 标题重复`).toBe(titles.length);
      }
    }
  });

  it('选项型控件的每个 default 都在 options 里', () => {
    for (const f of pages.flatMap(p => p.sections.flatMap(s => s.fields))) {
      if (f.widget !== 'enum' || f.default === undefined) continue;
      const values = (f.options ?? []).map(o => o.value);
      expect(values, `${f.title} 的默认值 ${String(f.default)} 不在选项中`).toContain(String(f.default));
    }
  });

  // 页 id / 顺序是 navStore.focus() 反查、Sidebar 顺序、PageView 的 about 特判的共同依据，钉死防漂移
  it('13 页的 id 与顺序固定', () => {
    expect(pages.map(p => p.id)).toEqual([
      'server', 'client', 'aiProviders', 'promptStyles', 'additionalApps',
      'libretranslate', 'deeplx', 'modelPaths', 'funasr', 'sensevoice',
      'paraformer', 'debug', 'about',
    ]);
    expect(new Set(pages.map(p => p.id)).size).toBe(13);
    expect(pages.every(p => p.title.length > 0 && p.icon.length > 0)).toBe(true);
  });
});
```

- [ ] **Step 4: 写 Rust 侧覆盖测试并跑通两端**

`tests/coverage.rs`：从 `"../../configs/default config.toml"` 读文本 → `ConfigDoc::parse` → `leaf_fields()` 的 segments（**排除 `client.additional_special_apps` 下的动态条目**：其段长 ≥ 3 且第 2 段是 `additional_special_apps`，实测恰好 2 条：`["client","additional_special_apps","vlc.exe","hotkey"]` 与同前缀的 `name`）→ 与 `schema_paths.json` 比对（都排序后 `JSON.stringify` 风格的字符串数组比较）。断言 `schema_paths.json` 长度 **160**（162 叶子 − 2 动态条目），并单独断言 `leaf_fields().len() == 162`。

Run:
```powershell
cd edit_config_gui; node scripts/gen-schema-paths.mjs; pnpm test
cd src-tauri; cargo test --release coverage
```
期望：两端都通过，且 `paths: 160`、`file.length == 160`、`leaf_fields().len() == 162`。

- [ ] **Step 5: Commit**

```powershell
git add edit_config_gui
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(schema): 补齐全部配置键并建立双向覆盖断言' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 13: bridge 与配置状态层

**Files:**
- Create: `edit_config_gui/src/bridge.ts`
- Create: `edit_config_gui/src/lib/stores/config.ts`
- Create: `edit_config_gui/src/lib/stores/config.test.ts`
- Create: `edit_config_gui/src/lib/stores/toast.ts`（右下角提示队列）
- Create: `edit_config_gui/src/lib/stores/nav.ts`（当前页 + 高亮目标；Task 14 的 ReadonlyWidget 与 Task 15 的 Field 都要用它做跳转，故在此先建）

**Interfaces:**
- Consumes: schema（Task 10–12）
- Produces:

```ts
// bridge.ts —— 唯一 invoke 出口，函数名与 Rust 命令一一对应
export interface FileFingerprint { mtimeMs: number; size: number; sha256: string }
export interface FieldView { segments: string[]; value: JsonValue; tomlType: string }
export interface DocState { path: string; fingerprint: FileFingerprint; fields: FieldView[]; baseDir: string }

// 与 Rust 的 PatchValue（serde tag="kind" rename_all="camelCase"）逐字对应
export type PatchValue =
  | { kind: 'str'; value: string }
  | { kind: 'int'; value: number }
  | { kind: 'float'; value: number }
  | { kind: 'bool'; value: boolean }
  | { kind: 'strArray'; value: string[] }
  | { kind: 'pairArray'; value: [string, number][] }
  | { kind: 'tableRow'; value: Record<string, string> }
  | { kind: 'delete' };
export interface Patch { segments: string[]; value: PatchValue }

// 与 Rust 的 FieldRule（serde rename_all="camelCase"）逐字对应
export interface FieldRule {
  segments: string[];
  validators: ValidatorId[];
  allowEmpty: boolean;
  fileSuffix: string | null;
  warnOnly: boolean;
}
export interface Problem { segments: string[]; message: string }
export interface PreviewResult { diff: string; errors: Problem[]; warnings: Problem[]; changed: string[][] }
export interface CommitResult { fingerprint: FileFingerprint; backupPath: string }
export interface RunningInfo { server: boolean; client: boolean; clientVariant: string | null; isAdmin: boolean }
export const bridge: {
  openConfig(path?: string): Promise<DocState>;
  pickPath(mode: 'file' | 'dir', title: string): Promise<string | null>;
  previewSave(patches: Patch[], rules: FieldRule[]): Promise<PreviewResult>;
  commitSave(patches: Patch[], rules: FieldRule[], fingerprint: FileFingerprint, force: boolean): Promise<CommitResult>;
  reloadConfig(): Promise<DocState>;
  runningProcesses(): Promise<RunningInfo>;
  /** 对应 Rust 的 RestartOutcome（serde camelCase）：degraded=true 表示降权失败，必须提示用户 */
  restartService(target: 'server' | 'client'): Promise<{ degraded: boolean }>;
};

// stores/nav.ts —— 当前页与高亮目标（ReadonlyWidget / Field / CommandPalette / Sidebar 共用）
export const navStore: {
  current: () => string;                 // 当前页 id，初值 pages[0].id
  go(id: string): void;                  // 切页并清空 highlight
  /** 切页 + 把某字段滚动到视野内并高亮 1.5 秒（搜索结果与「跳转到来源」共用） */
  focus(segments: string[]): void;
  highlight: () => string | null;        // 当前高亮的 fieldId（fieldId(segments)），1.5 秒后自动清为 null
};

// stores/config.ts —— runes 状态
export const configStore: {
  state: () => 'loading' | 'ready' | 'onboarding' | 'error';
  doc: () => DocState | null;
  values: () => Record<string, JsonValue>;        // 以 fieldId 为键
  dirtyIds: () => Set<string>;
  /** 当前字段的错误文案（来自最近一次 preview_save 的 errors）；无错时返回 undefined */
  errors: () => Record<string, string>;
  errorOf(id: string): string | undefined;
  setValue(id: string, v: JsonValue): void;
  resetValue(id: string): void;
  resetAll(): void;                               // 「全部还原」用
  patches: () => Patch[];
  rules: () => FieldRule[];                       // 只含当前可见字段的规则
  load(path?: string): Promise<void>;
  reload(): Promise<void>;
  applyDoc(d: DocState): void;
  /** 把 preview_save 返回的 errors/warnings 落到 errors 表；warnOnly 的进 warnings 不进 errors */
  applyProblems(problems: { errors: Problem[]; warnings: Problem[] }): void;
  // —— 以下两个只给测试用，产品代码不得调用 ——
  /** 清空 values/dirty/errors 并加载一份内存基线（不触 IPC） */
  __resetForTest(): void;
  /** 直接注入一个字段错误，供 Field.svelte 的渲染测试使用 */
  setError(id: string, message: string): void;
};
```

> `warnings` 单独存一份（`warnings: () => Problem[]`），由 `DiffDialog` 读取；`applyProblems` 负责按 `FieldRule.warnOnly` 分流——`warnOnly` 的字段问题**只能**进 `warnings`，绝不能进 `errors`，否则「模型文件缺失只警告不阻断」会退化成阻断保存。

- [ ] **Step 1: 写失败测试（纯逻辑，不触 IPC）**

```ts
import { beforeEach, describe, expect, it } from 'vitest';
import { buildPatches, buildRules, configStore, initialValues } from './config';
import { fieldId } from '../schema';

describe('patch 生成', () => {
  it('只产出脏字段', () => {
    const base = { [fieldId(['server','addr'])]: '0.0.0.0', [fieldId(['server','model'])]: 'FunASR' };
    const cur  = { [fieldId(['server','addr'])]: '127.0.0.1', [fieldId(['server','model'])]: 'FunASR' };
    const p = buildPatches(base, cur);
    expect(p).toHaveLength(1);
    expect(p[0].segments).toEqual(['server','addr']);
    expect(p[0].value).toEqual({ kind: 'str', value: '127.0.0.1' });
  });

  it('字符串型整数键仍发 str', () => {
    const id = fieldId(['client','start_music_volume']);
    const p = buildPatches({ [id]: '100' }, { [id]: '80' });
    expect(p[0].value).toEqual({ kind: 'str', value: '80' });
  });

  it('真假布尔发 bool', () => {
    const id = fieldId(['client','hold_mode']);
    const p = buildPatches({ [id]: false }, { [id]: true });
    expect(p[0].value).toEqual({ kind: 'bool', value: true });
  });

  it('不可见字段不下发规则', () => {
    // values 以 fieldId 为键；adb 关闭 → adb_addr 的 visibleWhen 不满足 → 不下发规则
    const values = { [fieldId(['client', 'enable_adb_control'])]: false };
    const rules = buildRules(values);
    expect(rules.some(r => r.segments.join('.') === 'client.adb_addr')).toBe(false);
  });

  it('可见字段会下发规则', () => {
    const values = { [fieldId(['client', 'enable_adb_control'])]: true };
    const rules = buildRules(values);
    expect(rules.some(r => r.segments.join('.') === 'client.adb_addr')).toBe(true);
  });

  it('int 字段接受超范围既有值', () => {
    const v = initialValues([{ segments:['client','mic_seg_duration'], value: 120, tomlType:'integer' }]);
    expect(v[fieldId(['client','mic_seg_duration'])]).toBe(120);  // 不夹取
  });
});

describe('脏态跟踪', () => {
  beforeEach(() => configStore.__resetForTest());

  it('dirty_tracking：改字段后进脏集合，改回原值后自动移出', () => {
    const id = fieldId(['server','addr']);
    expect(configStore.dirtyIds().has(id)).toBe(false);
    configStore.setValue(id, '127.0.0.1');
    expect(configStore.dirtyIds().has(id)).toBe(true);
    // 改回原值 —— 脏集合必须自己收缩，不能靠用户点「放弃」
    configStore.setValue(id, '0.0.0.0');
    expect(configStore.dirtyIds().has(id)).toBe(false);
    expect(configStore.patches()).toEqual([]);
  });

  it('revert_all：放弃后 current 回到 original，脏集合与错误表都清空', () => {
    const id = fieldId(['server','addr']);
    configStore.setValue(id, '1.2.3.4');
    configStore.setError(id, '不是有效的IP地址');
    configStore.resetAll();
    expect(configStore.dirtyIds().size).toBe(0);
    expect(configStore.values()[id]).toBe('0.0.0.0');
    expect(configStore.errorOf(id)).toBeUndefined();
  });

  it('revert_field：单字段恢复默认只动该字段，其它脏字段保持脏', () => {
    const a = fieldId(['server','addr']);
    const m = fieldId(['server','model']);
    configStore.setValue(a, '1.2.3.4');
    configStore.setValue(m, 'Sensevoice');
    configStore.resetValue(a);
    expect(configStore.values()[a]).toBe('0.0.0.0');   // 回到 schema default
    expect(configStore.dirtyIds().has(a)).toBe(false);
    expect(configStore.dirtyIds().has(m)).toBe(true);  // 另一个仍脏
  });
});
```

- [ ] **Step 2: 实现 `bridge.ts`（薄封装）+ `config.ts`**

关键实现约束：
- `buildPatches` 的类型选择**只看 `FieldMeta.type`，不看值本身**：`string` → `{kind:'str'}`（即便值是 `"80"` 这种数字串）、`integer` → `{kind:'int'}`、`float` → `{kind:'float'}`、`boolean` → `{kind:'bool'}`、`stringArray` → `{kind:'strArray'}`、`pairArray` → `{kind:'pairArray'}`、`inlineTable` → `{kind:'tableRow'}`。补丁的 `segments` 来自 `FieldMeta.segments`，**不得**从 `path` 字符串 split 得到。
- `initialValues` **不做范围夹取**，原样保留文档值（Review Focus 第 2 条）。
- `buildRules` 跳过 `visibleWhen` 不满足的字段；`warnOnly` 原样透传到 `FieldRule.warn_only`。
- `resetValue` 用 `FieldMeta.default`（Task 10–12 在各 `schema/*.ts` 里已按 `configs/default config.toml` 填好，字段名就叫 `default`，**不叫 `defaultValue`**）。
- `navStore`（`stores/nav.ts`）本任务只建骨架：`current` / `highlight` 两个 `$state`，`go(id)` 切页并把 `highlight` 置 `null`，`focus(segments)` 先反查页 id 再切页并设 `highlight = fieldId(segments)`，用 `setTimeout(1500)` 清空。**两个必须遵守的点**：① 重复调用 `focus()` 要先 `clearTimeout`，否则上一次的定时器会把新的高亮提前清掉；② 找页 id 必须遍历 `pages[].sections[].fields[].segments` 反查，**不得**用 `segments[0]` 猜——`server`/`client` 恰好与页 id 同名，但 `client.zhipuai` 的页 id 是 `aiProviders`、`client.prompt_style` 是 `promptStyles`，靠段名猜会跳错页。`focus()` 里的 `scrollIntoView` 在 jsdom 下不存在，调用处要写成 `el?.scrollIntoView?.({ block: 'center' })`。

- [ ] **Step 3: 跑绿并提交**

Run: `pnpm test` → 期望全绿。

```powershell
git add edit_config_gui/src
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(stores): IPC 桥接与配置状态层' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 14: 控件库（13 个 widget）

**Files:**
- Create: `edit_config_gui/src/lib/components/widgets/TextWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/SecretWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/LongTextWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/BoolWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/EnumWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/IntWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/FloatWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/HotkeyWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/PathWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/StringListWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/PairListWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/DynamicTableWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/ReadonlyWidget.svelte`
- Create: `edit_config_gui/src/lib/components/widgets/index.ts`
- Create: `edit_config_gui/src/lib/components/widgets/widgets.test.ts`

**Interfaces:**
- Consumes: `FieldMeta`、`configStore`、`bridge`
- Produces: 每个控件统一 props：`{ field: FieldMeta; value: JsonValue; error?: string; onChange(v: JsonValue): void }`，并在 `index.ts` 导出 `widgetFor(kind: WidgetKind)` 映射。

- [ ] **Step 1: 写失败测试（用 `@testing-library/svelte`）**

```ts
import { describe, expect, it } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TextWidget from './TextWidget.svelte';
import IntWidget from './IntWidget.svelte';
import HotkeyWidget from './HotkeyWidget.svelte';
import type { FieldMeta } from '../../schema/types';

/** 测试用字段工厂：只覆盖需要的字段，其余给安全默认值 */
function f(p: Partial<FieldMeta> & { widget: FieldMeta['widget'] }): FieldMeta {
  return {
    path: (p.segments ?? ['client', 'x']).join('.'),
    segments: ['client', 'x'],
    title: '测试字段',
    type: 'string',
    validators: [],
    ...p,
  } as FieldMeta;
}

it('text 控件透传输入', async () => {
  const got: unknown[] = [];
  const { getByRole } = render(TextWidget, { field: f({ widget:'text' }), value: 'a', onChange: v => got.push(v) });
  await fireEvent.input(getByRole('textbox'), { target: { value: 'abc' } });
  expect(got.at(-1)).toBe('abc');
});

it('int 控件编辑时夹取到 min/max', async () => {
  const got: number[] = [];
  const { getByRole } = render(IntWidget, { field: f({ widget:'int', min:10, max:60 }), value: 20, onChange: v => got.push(v as number) });
  const el = getByRole('spinbutton');
  await fireEvent.change(el, { target: { value: '999' } });
  expect(got.at(-1)).toBe(60);
});

it('int 控件首次渲染不改写超范围既有值', () => {
  const { getByRole } = render(IntWidget, { field: f({ widget:'int', min:10, max:60 }), value: 120, onChange: () => {} });
  expect((getByRole('spinbutton') as HTMLInputElement).value).toBe('120');
});

it('hotkey 控件录制后回填', async () => {
  const got: string[] = [];
  const { getByRole } = render(HotkeyWidget, { field: f({ widget:'hotkey' }), value: '', onChange: v => got.push(v as string) });
  const btn = getByRole('button', { name: /录制/ });
  await fireEvent.click(btn);
  await fireEvent.keyDown(window, { key: 'F5', ctrlKey: true, altKey: true });
  expect(got.at(-1)).toBe('ctrl + alt + f5');
});
```

- [ ] **Step 2: 实现各控件**

要点（全部可验证，不含猜测）：
- `IntWidget` / `FloatWidget`：`oninput` 只更新本地显示，**`onchange`（失焦/回车）时才夹取并上报**。首次渲染**不**夹取既有值（Review Focus 第 2 条）。`type` 为 `string` 的整数字段（如 `start_music_volume`）由 `IntWidget` 用 `String(v)` 上报。
- `HotkeyWidget`：一个「录制」按钮 + 一个输入框（可手打）。录制期监听 `keydown`（`{ capture: true }`），把 `event.ctrlKey/altKey/shiftKey/metaKey` 拼成 `ctrl + alt + shift + <key>`，`event.key === 'Meta'` 映射 `windows`，`' '` 映射 `space`，`Escape` 停止录制但不写入。录制结果立即交给 `onChange`，合法性由 Rust 侧 `validate` 兜底并回显。
- `PathWidget`：一个只读输入框 + 「浏览…」按钮，点击调 `bridge.pickPath('file'|'dir', field.title)`。`mode` 由 `field.validators` 是否含 `dirExist` 决定。
- `SecretWidget`：`type="password"` + 眼睛按钮切换；**不得**把明文写进 `title` 或 `aria-label`。
- `DynamicTableWidget`（`additional_special_apps`）：三列表格（进程名 / 全局快捷键 / 显示名称）+ 删除按钮 + 「添加一行」。空状态文案「暂未添加」。新增/删除/改值都通过 `onChange` 上报**整表当前值**，由 `buildPatches` 与基线做差得出 `tableRow` / `delete` 补丁（不得下发「整表替换」）。
- `StringListWidget`：每行一个文本框 + 删除；值 `[""]` 视为空列表显示「暂未添加」，为空时上报 `[]`（Task 3 的 `StrArray(vec![])` → 写回 `[""]`）。
- `ReadonlyWidget`：显示 `resolve` 值 + 灰度样式 + 提示「此项由模型路径页的 X 决定，修改后立即生效；本文件中的值为占位符，不参与读取」。附「跳转到来源」按钮（切页 + 高亮）。
- 全部控件用 `<input>` 的原生 `aria-invalid` 标记错误态；错误文案由 `Field.svelte` 渲染，控件只负责边框。

- [ ] **Step 3: 跑绿并提交**

Run: `pnpm test` → 期望 widgets 测试通过。

```powershell
git add edit_config_gui/src/lib/components/widgets
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(widgets): 十三个配置控件' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 15: Field 与 Section 渲染层

**Files:**
- Create: `edit_config_gui/src/lib/components/Field.svelte`
- Create: `edit_config_gui/src/lib/components/Section.svelte`
- Create: `edit_config_gui/src/lib/components/Field.test.ts`

**Interfaces:**
- Consumes: `FieldMeta`、`widgetFor()`、`configStore`
- Produces: `Section` props `{ section: SectionMeta }`；`Field` props `{ field: FieldMeta }`。两者都从 `configStore` 直接读写。

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import Field from './Field.svelte';
import { configStore } from '../stores/config';
import { fieldId } from '../schema';
import type { FieldMeta } from '../schema/types';

const meta = (p: Partial<FieldMeta> & { widget: FieldMeta['widget'] }): FieldMeta => ({
  path: p.segments!.join('.'),
  segments: ['client', 'x'],
  title: '测试字段',
  type: 'string',
  ...p,
} as unknown as FieldMeta);

const adbField = meta({
  segments: ['client', 'adb_addr'],
  title: 'ADB 设备地址',
  validators: ['ipPort'],
  visibleWhen: { segments: ['client', 'enable_adb_control'], equals: true },
});
const addrField = meta({
  segments: ['server', 'addr'],
  title: '服务端监听地址',
  validators: ['localListenableIp'],
});

beforeEach(() => configStore.__resetForTest());

it('visibleWhen 不满足时整行不渲染', () => {
  configStore.setValue(fieldId(['client', 'enable_adb_control']), false);
  const { queryByText } = render(Field, { field: adbField });
  expect(queryByText('ADB 设备地址')).toBeNull();
});

it('visibleWhen 满足时整行渲染', () => {
  configStore.setValue(fieldId(['client', 'enable_adb_control']), true);
  const { getByText } = render(Field, { field: adbField });
  expect(getByText('ADB 设备地址')).toBeTruthy();
});

it('有错误时渲染文案并标记 aria-invalid', () => {
  configStore.setError(fieldId(['server', 'addr']), '不是有效的IP地址');
  const { getByText, getByRole } = render(Field, { field: addrField });
  expect(getByText('不是有效的IP地址')).toBeTruthy();
  expect(getByRole('textbox').getAttribute('aria-invalid')).toBe('true');
});

it('脏字段显示「已修改」标记', () => {
  configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
  const { getByText } = render(Field, { field: addrField });
  expect(getByText('已修改')).toBeTruthy();
});

it('note 与 title 同时可见', () => {
  const withNote = meta({
    segments: ['server', 'addr'],
    title: '服务端监听地址',
    note: '服务端启动时绑定的网卡地址，0.0.0.0 表示全部网卡',
  });
  const { getByText } = render(Field, { field: withNote });
  expect(getByText('服务端监听地址')).toBeTruthy();          // title
  expect(getByText('服务端启动时绑定的网卡地址，0.0.0.0 表示全部网卡')).toBeTruthy();  // note
});
```

> 上面用到的两个测试态方法（`__resetForTest()`、`setError(id, msg)`）必须在 Task 13 的 `configStore` 里一并实现：`__resetForTest` 把 values/dirty/errors 清空并加载一份内存基线；`setError` 写入 `errors: Record<fieldId, string>`，供 `Field.svelte` 读取。这两个不是给产品代码用的，但**必须存在**，否则本任务的测试跑不起来。

- [ ] **Step 2: 实现**

`Field.svelte` 结构：左列 `title` + `note`（小字灰色，来自 `config.toml` 注释），右列控件，下方错误行。用 Svelte 5 runes（`$props()`、`$derived`），不要用 `export let`。

具体四件事：
1. `$derived` 计算 `visible`：`field.visibleWhen` 为 `undefined` 时恒 `true`；否则读 `configStore.values()[fieldId(field.visibleWhen.segments)]`，有 `equals` 则严格相等，有 `in` 则包含。`visible === false` 时整个 `<div class="field">` 不渲染（用 `{#if}`，不要用 CSS `display:none`，否则 Tab 键仍能聚焦到隐藏控件）。
2. 脏标记：`configStore.dirtyIds().has(fieldId(field.segments))` 为真时在 title 右侧渲染 `<span class="dirty">已修改</span>`。
3. 错误行：`error = configStore.errorOf(fieldId(field.segments))`；有则渲染 `<p class="error">{error}</p>` 并给控件传 `error`，控件据此设 `aria-invalid="true"`。
4. 只读派生字段（`field.widget === 'readonly'`）额外渲染「来源：<链式面包屑>」与「跳转到来源」按钮，点击调 `navStore.go` 并设置 `highlight`。

`Section.svelte` 只是 `<h2>{section.title}</h2>` + 可选 `<p class="note">{section.note}</p>` + `{#each section.fields as field}<Field {field} />{/each}`，不需要额外逻辑。

- [ ] **Step 3: 跑绿并提交**

Run: `cd edit_config_gui; pnpm test` — 期望 `Field.test.ts` 的 5 个用例全绿（其中 2 个依赖 Task 13 的 `__resetForTest` 与 `setError`）。

```powershell
git add edit_config_gui/src/lib/components
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(components): Field 与 Section 渲染层' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 16: 侧边导航、页面容器与 App 装配

**Files:**
- Modify: `edit_config_gui/src/lib/stores/nav.ts`（Task 13 已建骨架，此处补 `focus()` 的反查页逻辑与 1.5 秒高亮定时器）
- Create: `edit_config_gui/src/lib/components/Sidebar.svelte`
- Create: `edit_config_gui/src/lib/components/pages/PageView.svelte`
- Modify: `edit_config_gui/src/App.svelte`
- Create: `edit_config_gui/src/lib/components/nav.test.ts`

**Interfaces:**
- Consumes: `pages`（13 页）、`configStore`、`navStore`（Task 13）、`Field`/`Section`（Task 15）
- Produces:

```ts
// navStore 在 Task 13 已随 configStore 一起建好（stores/nav.ts），此处只消费
```

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import Sidebar from './Sidebar.svelte';
import { navStore } from '../stores/nav';
import { configStore } from '../stores/config';
import { pages, fieldId } from '../schema';

beforeEach(() => { navStore.go(pages[0].id); configStore.__resetForTest(); });

it('13 个导航项按 pages 顺序渲染', () => {
  const { getAllByRole } = render(Sidebar);
  const items = getAllByRole('tab').map(el => el.textContent?.trim());
  expect(items).toHaveLength(13);
  expect(items[0]).toContain(pages[0].title);
});

it('点击切换 current', async () => {
  const { getByText } = render(Sidebar);
  await fireEvent.click(getByText(pages[1].title));
  expect(navStore.current()).toBe(pages[1].id);
});

it('该页有脏字段时导航项出现脏计数', () => {
  configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
  const { getByRole } = render(Sidebar);
  const serverTab = getByRole('tab', { name: new RegExp(pages[0].title) });
  expect(serverTab.textContent).toMatch(/1/);
});

it('go() 会清空 highlight', () => {
  navStore.focus(['server', 'addr']);
  expect(navStore.highlight()).not.toBeNull();
  navStore.go(pages[1].id);
  expect(navStore.highlight()).toBeNull();
});
```

- [ ] **Step 2: 实现**

`stores/nav.ts`：`current` / `highlight` 两个 `$state`，`go()` 清空 highlight，`focus(segments)` 设 `current = 所在页 id` 与 `highlight = fieldId(segments)`，并用 `setTimeout(1500)` 清空（重复调用要先 `clearTimeout`，否则上次的定时器会把新的高亮提前清掉）；高亮目标所在页从 `pages` 反查（遍历 `pages[].sections[].fields[].segments` 找匹配者），**不得**用 `segments[0]` 猜页 id——`server`/`client` 段的页 id 恰好同名，但 `client.zhipuai` 的页 id 是 `aiProviders`、`client.prompt_style` 是 `promptStyles`，靠段名猜会跳错页。

`Sidebar.svelte`：左侧 200px 固定宽度 + 右侧滚动区。窗口 ≥ 1000px 时侧栏常驻。导航项显示 `page.title` 与脏计数徽标（该页所有字段的脏数之和，为 0 时不渲染徽标）。用 `role="tab"` / `aria-selected`，整列 `<nav role="tablist">`。

- [ ] **Step 3: `pnpm dev` 目视检查 + `pnpm check` 并提交**

Run: `cd edit_config_gui; pnpm test; pnpm check` — 期望导航的 4 个测试全绿、`svelte-check` 0 error。再 `pnpm dev` 打开窗口，确认左侧 13 项按 `pages` 顺序、点任一页右侧内容跟着换、改一个字段后对应导航项出现脏计数。

```powershell
git add edit_config_gui/src
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(ui): 侧边导航与页面容器' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 17: 搜索与命令面板

**Files:**
- Create: `edit_config_gui/scripts/gen-pinyin-map.mjs`
- Create: `edit_config_gui/src/lib/pinyin-map.json`（产物，提交）
- Create: `edit_config_gui/src/lib/search.ts`
- Create: `edit_config_gui/src/lib/search.test.ts`
- Create: `edit_config_gui/src/lib/pinyin.ts`
- Create: `edit_config_gui/src/lib/pinyin.test.ts`（拼音表与 schema 的同步断言，验收标准第 21 条）
- Create: `edit_config_gui/src/lib/stores/palette.ts`（`open` / `query` / `selectedIndex` / `recent` 四个 `$state`）
- Create: `edit_config_gui/src/lib/components/CommandPalette.svelte`
- Create: `edit_config_gui/src/lib/components/palette.test.ts`

**Interfaces:**
- Consumes: `allFields()`、`fieldId`
- Produces:

```ts
export interface SearchHit {
  fieldId: string;
  segments: string[];
  title: string;
  page: string;
  score: number;
  matchedBy: 'title' | 'segment' | 'pinyin' | 'initial' | 'note';
  /** 徽标：visibleWhen 不满足 → 'hidden'；派生只读键 → 'readonly'；普通字段无此字段 */
  badge?: 'hidden' | 'readonly';
  /** 仅 badge==='hidden'：需要先开启哪个控制字段（那一项的 segments），供「去开启该开关」用 */
  dependOn?: string[];
  /** 仅 badge==='readonly'：真正能改的那个字段的 segments，供「第二跳」用 */
  derivedFrom?: string[];
  /** 动态表条目的运行时命中（如用户输入了 vlc.exe），指向表格中该行的键名 */
  dynamicKey?: string;
}
/** 全量命中数（不截断）+ 是否触及上限；searchFields 是它的便捷包装 */
export const SEARCH_LIMIT = 50;
export function searchAll(q: string): { hits: SearchHit[]; truncated: boolean };
export function searchFields(q: string): SearchHit[];   // 空查询返回 []
```

**索引必须包含隐藏字段**：`searchFields` 遍历的是 `allFields()`（全部 162 项），而不是「当前可见」的字段。`visibleWhen` 不满足只影响徽标与跳转后的落地形态，不影响是否进结果——用户搜出来就是要改它，直接不显示会让人以为编辑器有 bug。

- [ ] **Step 1: 生成拼音表**

`gen-pinyin-map.mjs`：从 `config.toml` 与 `src/lib/schema/*.ts` 的中文文案里收集去重汉字（实测 820 + 21 = 841 字），对每个字用 `pinyinPro.pinyin(ch, { type:'array', multiple:true, toneType:'none' })` 取多音，输出 `{ "端": ["duan"], "重": ["zhong","chong"], "率": ["lü","lv","lu","shuai"], ... }`（`ü` 额外展开 `v` 与 `u` 变体）。文件约 12.7 KB。

Run: `node scripts/gen-pinyin-map.mjs` → 期望打印 `chars: 841`（`config.toml` 实测 820 个不重复汉字 + UI 文案补充的 21 个；实测计划里出现的汉字并集为 1017，故脚本的字表来源必须严格限定为「`config.toml` + `src/lib/schema/*.ts` 的 title/note」，不要扫全仓）。**字数本身不是验收口，真正的门是 Step 1.6 的同步断言**：`pinyin_map_covers_all_titles` 必须通过——新增字段后忘了重跑脚本会立刻红。

- [ ] **Step 2: 写 `pinyin.ts`（查表，不做转换）**

```ts
import map from './pinyin-map.json';

const TABLE = map as Record<string, string[]>;

/** 单字的全部读音（含 ü 的 v/u 变体）；表里没有的字返回空数组 */
export function readingsOf(ch: string): string[] {
  return TABLE[ch] ?? [];
}

/** 一个词的全拼候选串（逐字取音后笛卡尔积；超出 64 条时截断，防多音字爆炸） */
export function fullPinyinCandidates(word: string): string[] {
  let out = [''];
  for (const ch of word) {
    const rs = readingsOf(ch);
    if (rs.length === 0) return [];       // 含表外字（拉丁字母、标点）→ 不做拼音匹配
    const next: string[] = [];
    for (const prefix of out) for (const r of rs) next.push(prefix + r);
    out = next.slice(0, 64);
  }
  return out;
}

/** 首字母串（每个字取任意读音的首字母，去重后排序；同样截断到 64） */
export function initialCandidates(word: string): string[] {
  let out = [''];
  for (const ch of word) {
    const rs = readingsOf(ch);
    if (rs.length === 0) return [];
    const heads = [...new Set(rs.map(r => r[0]))];
    const next: string[] = [];
    for (const prefix of out) for (const h of heads) next.push(prefix + h);
    out = next.slice(0, 64);
  }
  return out;
}
```

- [ ] **Step 3: 写 `pinyin-map` 与 schema 的同步测试（验收标准第 21 条点名要求）**

```ts
import map from './pinyin-map.json';
import { allFields } from './schema';

const TABLE = map as Record<string, string[]>;
const HAN = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]/;

it('pinyin_map_covers_all_titles', () => {
  // 所有会参与搜索的中文文案（title + note + segments 里的中文段）的每个汉字都必须在表里，
  // 否则用户搜那个字会静默搜不到 —— 这是最容易在新增字段后回归的地方
  const missing = new Set<string>();
  for (const f of allFields()) {
    for (const text of [f.title, f.note ?? '', ...f.segments]) {
      for (const ch of text) {
        if (HAN.test(ch) && !(ch in TABLE)) missing.add(ch);
      }
    }
  }
  expect([...missing].sort(), `pinyin-map.json 缺字，请重跑 node scripts/gen-pinyin-map.mjs`).toEqual([]);
});

it('多音字保留全部读音', () => {
  expect(TABLE['重']).toEqual(expect.arrayContaining(['zhong', 'chong']));
  expect(TABLE['率']).toEqual(expect.arrayContaining(['shuai']));
  // ü 必须同时有 lü / lv / lu 三种写法，否则用户按汉语拼音习惯输入会搜不到
  expect(TABLE['率']).toEqual(expect.arrayContaining(['lü', 'lv', 'lu']));
});
```

- [ ] **Step 4: 写失败测试**

```ts
it('中文子串命中', () => {
  expect(searchFields('端口').length).toBeGreaterThan(0);
});
it('拼音全拼命中', () => {
  expect(searchFields('duankou').some(h => h.matchedBy === 'pinyin')).toBe(true);
});
it('首字母命中', () => {
  expect(searchFields('dk').some(h => h.matchedBy === 'initial')).toBe(true);
});
it('段路径命中也算', () => {
  expect(searchFields('speech_recognition_port').length).toBeGreaterThanOrEqual(2);   // server 与 client 两段都有此键
});
it('空查询返回空数组', () => {
  expect(searchFields('   ')).toEqual([]);
});
it('结果按分数降序且 title 精确命中排最前', () => {
  const r = searchFields('addr');
  expect(r[0].score).toBeGreaterThanOrEqual(r[r.length - 1].score);
});
it('同一查询两次结果顺序一致', () => {
  expect(searchFields('端口').map(h => h.fieldId))
    .toEqual(searchFields('端口').map(h => h.fieldId));
});
it('secret 的值不参与匹配', () => {
  // api_key 属于 secret，其值不建索引；搜一个像 key 前缀的串必须 0 条
  expect(searchFields('sk-abcdef')).toEqual([]);
});
it('隐藏字段仍进结果并带 hidden 徽标与 dependOn', () => {
  // 默认 enable_adb_control = false，adb_addr 是隐藏的
  const hit = searchFields('adb_addr').find(h => h.segments.join('.') === 'client.adb_addr');
  expect(hit).toBeTruthy();
  expect(hit!.badge).toBe('hidden');
  expect(hit!.dependOn).toEqual(['client', 'enable_adb_control']);
});
it('派生只读键带 readonly 徽标与 derivedFrom', () => {
  const hit = searchFields('encoder_onnx_path').find(h => h.segments.join('.') === 'funasr_args.encoder_onnx_path');
  expect(hit).toBeTruthy();
  expect(hit!.badge).toBe('readonly');
  expect(hit!.derivedFrom).toEqual(['model_paths', 'funasr_encoder_adaptor_path']);
});
it('动态表条目按进程名补一条 dynamicKey 命中', () => {
  configStore.setValue(fieldId(['client', 'additional_special_apps', 'vlc.exe', 'name']), 'VLC Media Player');
  const hits = searchFields('vlc');
  const dyn = hits.find(h => h.dynamicKey === 'vlc.exe');
  expect(dyn).toBeTruthy();
  expect(dyn!.segments.slice(0, 2)).toEqual(['client', 'additional_special_apps']);
});
it('只读派生字段也在结果里', () => {
  const r = searchFields('encoder_onnx_path');
  expect(r.some(h => h.segments.join('.') === 'funasr_args.encoder_onnx_path')).toBe(true);
});
it('结果截断到 50 条并暴露 truncated 标记', () => {
  // 单字「a」几乎命中所有键名，必然超过上限
  const all = searchAll('a');          // searchAll 返回 { hits, truncated }，不截断前先数总数
  expect(all.truncated).toBe(true);
  expect(all.hits.length).toBe(50);
  // `searchFields` 是 searchAll 的便捷包装，同样封顶 50
  expect(searchFields('a').length).toBeLessThanOrEqual(50);
  // 命中数不到上限时不得误标截断
  expect(searchAll('adb_addr').truncated).toBe(false);
});
it('多音字：重 的两种读法都能命中', () => {
  // 「重命名」类标题在客户端页（录音相关），zhong 与 chong 都必须能搜到同一条
  const byChong = searchFields('chongmingming').map(h => h.fieldId);
  const byZhong = searchFields('zhongmingming').map(h => h.fieldId);
  expect(byChong.length).toBeGreaterThan(0);
  expect(byChong).toEqual(byZhong);
});
```

- [ ] **Step 5: 实现 `search.ts`**

打分：`title` 完全相等 1000 / 前缀 800 / 包含 600；`segments` 任一段包含 500；拼音全拼前缀 400 / 包含 300；首字母前缀 200；`note` 包含 100。相等时按 `pages` 顺序稳定排序。查询先 `toLowerCase()`，`trim()` 后为空立即返回 `[]`。
**徽标与跳转的填充规则**（规格 §9.7.3，三处都要落地，漏任何一处验收第 21 条就不过）：

| 情形 | 判定 | `badge` | 附带字段 | 跳转后的落地形态 |
|---|---|---|---|---|
| 普通字段 | 其余全部 | 无 | 无 | 直接滚动 + 高亮控件 |
| `visibleWhen` 不满足 | 读 `values[fieldId(field.visibleWhen.segments)]`，按 `equals`/`in` 判定为假 | `'hidden'` | `dependOn = field.visibleWhen.segments` | 占位卡片「该配置项当前被隐藏，因为 `client.enable_adb_control` = `false`」+「去开启该开关」按钮 → `navStore.focus(dependOn)` |
| 派生只读键 | `field.derivedFrom` 存在（9 项） | `'readonly'` | `derivedFrom = field.derivedFrom` | 定位到只读控件（它显示「实际生效：<解析值>」）+ 徽标旁「去 `model_paths.funasr_encoder_adaptor_path`」第二跳 |

**动态表**：不为现有条目单独建索引项（条目随用户增删，索引会过期），只建一条指向整个表格的项（title `附加特殊应用`）；但搜索时若查询串命中某个**当前存在条目的进程名**（大小写不敏感），额外补一条 `dynamicKey` 命中，跳转到表格中该行并高亮。条目名从 `configStore.values()` 里那一项读，不在索引里缓存。

**`hidden` 的判定必须用 `visibleWhen` 求值**，不要用「页面当前有没有渲染这个控件」——搜索结果是在页面切换前算出来的，那时候目标页可能根本没挂载。

**`secret` 字段（`client.openai.api_key`、`client.zhipuai.api_key`）不得参与任何匹配**：它们能出现在结果里（便于跳转），但 `title`/`note`/`segment`/拼音都不允许对它们的**值**做匹配——搜索输入 `sk-` 之类前缀必须返回 0 条。实现上只要不给 secret 字段建值索引即可，值本来也不进索引；测试要明确断言这一点（规格 §13-21）。

**稳定排序**：`pages` 顺序 → `sections` 顺序 → `fields` 顺序。分数相同的项必须保持这个顺序，否则验收第 20 条的「同一查询连跑两次顺序一致」在真实使用中会因 `Array.prototype.sort` 的稳定性依赖而看似随机（V8 现在稳定，但要显式写出 tie-breaker，不依赖引擎实现）。

- [ ] **Step 6: 实现 `CommandPalette.svelte`**

`Ctrl+K` 打开（监听 `keydown`，`event.preventDefault()`），`Esc` 关闭，`↑/↓` 移动，`Enter` 跳转并高亮 1.5 秒。输入框 `autofocus`，最多显示 50 条。

面板的可变状态（`open` / `query` / `selectedIndex` / `recent`）全部放 `stores/palette.ts`，`CommandPalette.svelte` 只读它、不自己持有 —— 这样 `App.svelte` 的全局 `keydown`、`DiffDialog` 打开时的屏蔽、以及测试都能直接操作同一份状态，不必挂载组件。`recent` 最多存 8 条 `fieldId`，仅在内存里（不落盘、不读 localStorage）。

- [ ] **Step 7: 跑绿并提交**

Run: `pnpm test` — 期望 Task 13–17 的测试全绿，且 `pinyin_map_covers_all_titles` 通过（新增字段没重跑生成脚本会在这里红）。

```powershell
git add edit_config_gui
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(search): 命令面板与拼音搜索' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 18: DirtyBar、DiffDialog 与保存流程

**Files:**
- Create: `edit_config_gui/src/lib/stores/save.ts`（保存流程的状态机，纯逻辑，可单独测）
- Create: `edit_config_gui/src/lib/components/DirtyBar.svelte`
- Create: `edit_config_gui/src/lib/components/DiffDialog.svelte`
- Create: `edit_config_gui/src/lib/components/save.test.ts`
- Modify: `edit_config_gui/src/App.svelte`

**Interfaces:**
- Consumes: `configStore`、`bridge`
- Produces:

```ts
// stores/save.ts —— 保存流程状态机
export type SavePhase =
  | { kind: 'idle' }
  | { kind: 'previewing' }
  | { kind: 'confirm'; result: PreviewResult }
  | { kind: 'committing' }
  | { kind: 'conflict'; error: string }
  | { kind: 'done'; backupPath: string }
  | { kind: 'failed'; error: string };

export const saveStore: {
  phase: () => SavePhase;
  preview(): Promise<void>;          // 调 bridge.previewSave；errors 非空 → phase 仍是 idle 且把错误写进 configStore
  confirm(force: boolean): Promise<void>;
  cancel(): void;
  reloadAndReset(): Promise<void>;   // 冲突时点「重新加载」
};
```

- [ ] **Step 1: 写失败测试（mock bridge）**

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { saveStore } from '../stores/save';
import { configStore } from '../stores/config';
import { fieldId } from '../schema';
import * as bridgeMod from '../../bridge';   // 测试文件在 src/lib/components/ 下，bridge.ts 在 src/ 下

// bridge 用 vi.mock 整体替换，测试里只关心调用次数与返回值
vi.mock('../../bridge', () => ({
  bridge: {
    previewSave: vi.fn(), commitSave: vi.fn(), reloadConfig: vi.fn(),
    openConfig: vi.fn(), pickPath: vi.fn(), runningProcesses: vi.fn(), restartService: vi.fn(),
  },
}));
const bridge = vi.mocked(bridgeMod.bridge);
const emptyPreview = { diff: '', errors: [], warnings: [], changed: [] };

beforeEach(() => {
  vi.clearAllMocks();
  configStore.__resetForTest();
  saveStore.cancel();
});

it('无脏字段时保存按钮禁用', () => {
  expect(configStore.patches()).toEqual([]);
  // DirtyBar 用 patches().length > 0 决定 disabled；这里断言底层条件本身
});

it('preview 返回错误时不进入 confirm 态，并把错误写进 configStore', async () => {
  configStore.setValue(fieldId(['server', 'addr']), '999.1.1.1');
  bridge.previewSave.mockResolvedValue({
    ...emptyPreview,
    errors: [{ segments: ['server', 'addr'], message: '不是有效的IP地址' }],
  });
  await saveStore.preview();
  expect(saveStore.phase().kind).toBe('idle');
  expect(configStore.errorOf(fieldId(['server', 'addr']))).toBe('不是有效的IP地址');
  expect(bridge.commitSave).not.toHaveBeenCalled();
});

it('只有 warnings 时仍可确认保存', async () => {
  configStore.setValue(fieldId(['model_paths', 'funasr_llm_path']), 'models/x.gguf');
  bridge.previewSave.mockResolvedValue({
    ...emptyPreview,
    warnings: [{ segments: ['model_paths', 'funasr_llm_path'], message: '文件不存在' }],
  });
  await saveStore.preview();
  expect(saveStore.phase().kind).toBe('confirm');
  const p = saveStore.phase();
  expect(p.kind === 'confirm' && p.result.warnings.length).toBe(1);
});

it('冲突时进入 conflict 态，且不重试写盘', async () => {
  configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
  bridge.previewSave.mockResolvedValue(emptyPreview);
  bridge.commitSave.mockRejectedValue('CONFLICT');   // Tauri 的 Err 是字符串本身
  await saveStore.preview();
  await saveStore.confirm(false);
  expect(saveStore.phase().kind).toBe('conflict');
  expect(bridge.commitSave).toHaveBeenCalledTimes(1);     // 失败后不得自动重试
  expect(bridge.reloadConfig).not.toHaveBeenCalled();     // 也不得自动重载
});

it('强制覆盖时带 force=true 重发', async () => {
  configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
  bridge.previewSave.mockResolvedValue(emptyPreview);
  bridge.commitSave
    .mockRejectedValueOnce('CONFLICT')
    .mockResolvedValueOnce({ fingerprint: { mtimeMs: 1, size: 2, sha256: 'x' }, backupPath: 'config.toml.bak' });
  await saveStore.preview();
  await saveStore.confirm(false);
  await saveStore.confirm(true);
  expect(bridge.commitSave).toHaveBeenLastCalledWith(
    expect.any(Array), expect.any(Array), expect.anything(), true,
  );
  expect(saveStore.phase().kind).toBe('done');
});

it('保存成功后清空脏状态并带出备份路径', async () => {
  configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
  bridge.previewSave.mockResolvedValue(emptyPreview);
  bridge.commitSave.mockResolvedValue({ fingerprint: { mtimeMs: 1, size: 2, sha256: 'x' }, backupPath: 'config.toml.bak' });
  await saveStore.preview();
  await saveStore.confirm(false);
  expect(configStore.patches()).toEqual([]);              // 脏状态已清空
  const p = saveStore.phase();
  expect(p.kind === 'done' && p.backupPath).toBe('config.toml.bak');
});

it('冲突后点重新加载会丢弃本地改动', async () => {
  configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
  bridge.reloadConfig.mockResolvedValue({
    path: 'config.toml', fingerprint: { mtimeMs: 1, size: 2, sha256: 'x' },
    fields: [{ segments: ['server', 'addr'], value: '0.0.0.0', tomlType: 'string' }],
    baseDir: '.',
  });
  await saveStore.reloadAndReset();
  expect(configStore.patches()).toEqual([]);
  expect(saveStore.phase().kind).toBe('idle');
});
```

- [ ] **Step 2: 实现**

- `DirtyBar`：固定底部，显示「N 项已修改」+「全部还原」+「保存」；保存中显示 spinner 并禁用。
- `DiffDialog`：`<pre>` 渲染 unified diff，`+` 行绿色、`-` 行红色；顶部显示改动计数；`warnings` 用黄色块列出；底部「取消」/「保存」。**不使用长按**（用户已定，规格 §9.2）。
- 冲突分支：`commit_save` 抛 `CONFLICT` → 对话框切换为冲突态，说明「文件已被外部修改（可能是 config_selector 或其它编辑器）」，两个按钮分别调 `reload()` 与 `commitSave(..., force=true)`。
- 保存成功后的 `phase = done` 里必须带出 `backupPath`，状态栏提示「已备份到 `<backupPath>`」，并提示「需重启服务端/客户端以生效」，给出重启按钮（Task 19 实现按钮）。

**错误识别（关键，写错会导致冲突检测形同虚设）**：Tauri 2 的命令返回 `Result<T, String>` 时，`invoke` 被 reject 的**就是那个字符串本身**，不是 `Error` 对象。所以判断冲突必须写 `String(e) === 'CONFLICT'`；写成 `(e as Error).message === 'CONFLICT'` 会恒为 `undefined`，冲突将永远识别不到，用户点保存就会得到一句莫名其妙的中文失败提示。Rust 侧对冲突固定返回字面量 `"CONFLICT"`，其他错误返回可读中文；这个约定同时写在 Task 9 的 `commit_save` 里。

- [ ] **Step 3: 跑绿并提交**

Run: `cd edit_config_gui; pnpm test` — 期望保存流程测试全绿（含冲突分支：`commitSave` 抛 `CONFLICT` 后出现「重新加载」与「强制覆盖」两个按钮）。

```powershell
git add edit_config_gui/src
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(save): 脏状态栏、diff 预览与冲突处理' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 19: 进程状态栏、重启与引导态

**Files:**
- Create: `edit_config_gui/src/lib/components/StatusBar.svelte`
- Create: `edit_config_gui/src/lib/components/Onboarding.svelte`
- Create: `edit_config_gui/src/lib/components/status.test.ts`
- Modify: `edit_config_gui/src/App.svelte`

**Interfaces:**
- Consumes: `bridge.runningProcesses()` / `bridge.restartService()` / `bridge.openConfig()` / `bridge.pickPath()`
- Produces: 状态栏 5 秒轮询（页面隐藏时暂停）。

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/svelte';
import StatusBar from './StatusBar.svelte';
import Onboarding from './Onboarding.svelte';
import App from '../../App.svelte';
import * as bridgeMod from '../../bridge';

vi.mock('../../bridge', () => ({
  bridge: {
    runningProcesses: vi.fn(), restartService: vi.fn(), openConfig: vi.fn(),
    pickPath: vi.fn(), previewSave: vi.fn(), commitSave: vi.fn(), reloadConfig: vi.fn(),
  },
}));
const bridge = vi.mocked(bridgeMod.bridge);

beforeEach(() => vi.clearAllMocks());

it('服务端在跑时显示运行指示', async () => {
  bridge.runningProcesses.mockResolvedValue({ server: true, client: false, clientVariant: null, isAdmin: false });
  render(StatusBar);
  expect(await screen.findByText(/服务端/)).toBeTruthy();
  expect(screen.getByLabelText('服务端运行中')).toBeTruthy();
});

it('点重启并确认后调用 restartService', async () => {
  bridge.runningProcesses.mockResolvedValue({ server: true, client: false, clientVariant: null, isAdmin: false });
  bridge.restartService.mockResolvedValue({ degraded: false });
  render(StatusBar);
  await fireEvent.click(await screen.findByRole('button', { name: /重启服务端/ }));
  // 确认弹窗必须出现，文案要说明会中断语音输入
  expect(screen.getByText(/重启会中断正在进行的语音输入/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));
  expect(bridge.restartService).toHaveBeenCalledWith('server');
});

it('取消确认时不调用 restartService', async () => {
  bridge.runningProcesses.mockResolvedValue({ server: true, client: false, clientVariant: null, isAdmin: false });
  render(StatusBar);
  await fireEvent.click(await screen.findByRole('button', { name: /重启服务端/ }));
  await fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(bridge.restartService).not.toHaveBeenCalled();
});

it('degraded=true 时提示降权失败', async () => {
  bridge.runningProcesses.mockResolvedValue({ server: true, client: false, clientVariant: null, isAdmin: true });
  bridge.restartService.mockResolvedValue({ degraded: true });
  render(StatusBar);
  await fireEvent.click(await screen.findByRole('button', { name: /重启服务端/ }));
  await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));
  expect(await screen.findByText(/未能以普通权限启动/)).toBeTruthy();
});

it('onboarding 态只渲染 Onboarding，不渲染页面', () => {
  render(App, { props: { __forceState: 'onboarding' } });   // App 接受一个仅测试用的 state 覆盖 prop
  expect(screen.getByText(/未找到 config.toml/)).toBeTruthy();
  expect(screen.queryByRole('tablist')).toBeNull();
});

it('引导态选择文件后调用 openConfig', async () => {
  bridge.pickPath.mockResolvedValue('D:\\x\\config.toml');
  bridge.openConfig.mockResolvedValue({
    path: 'D:\\x\\config.toml', fingerprint: { mtimeMs: 1, size: 2, sha256: 'x' },
    fields: [], baseDir: 'D:\\x',
  });
  render(Onboarding);
  await fireEvent.click(screen.getByRole('button', { name: /选择 config.toml/ }));
  expect(bridge.pickPath).toHaveBeenCalledWith('file', expect.any(String));
  expect(bridge.openConfig).toHaveBeenCalledWith('D:\\x\\config.toml');
});
```

- [ ] **Step 2: 实现**

- `StatusBar.svelte`：`onMount` 起 5 秒 `setInterval` 调 `bridge.runningProcesses()`，`visibilitychange` 到 `hidden` 时清掉、回到 `visible` 时立刻拉一次再重建。显示「服务端 ● / 客户端 ●」（在跑为绿点、未跑为灰点，给 `aria-label` 写「服务端运行中」/「服务端未运行」）+ 重启按钮 + 「已备份到 `<path>`」提示位。
- 重启按钮文案按目标区分：「重启服务端」/「重启客户端」，点击先弹确认层（在当前窗口内渲染，**不要**用 `window.confirm`，因为 Tauri 的 WebView 里原生对话框可能被禁用且无法测试），确认文案固定含「重启会中断正在进行的语音输入」。
- `degraded === true` 时提示「未能以普通权限启动服务端，可能无法被客户端连接；请用非管理员方式启动服务端」。
- `Onboarding.svelte`：标题「未找到 config.toml」+ 三条说明（① 把 `config.toml` 放在本程序同目录；② 或用命令行参数指定路径；③ 或点击下方按钮手动选择）+「选择 config.toml…」按钮，选完直接 `bridge.openConfig(path)`。
- `App.svelte` 增加一个 `__forceState` props（仅测试用，默认 `undefined`），用于在 jsdom 里直接渲染 onboarding 态而无需真的触发 IPC 失败。

- [ ] **Step 3: 跑绿并提交**

Run: `cd edit_config_gui; pnpm test` — 期望状态栏与引导态测试全绿。

```powershell
git add edit_config_gui/src
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(status): 进程状态、重启与未找到配置的引导' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 20: 主题与外观

**Files:**
- Modify: `edit_config_gui/src/app.css`
- Modify: `edit_config_gui/src/App.svelte`（根节点加 `data-theme`）

**Interfaces:**
- Consumes: 无
- Produces: CSS 变量 `--bg`、`--panel`、`--text`、`--muted`、`--border`、`--accent`、`--danger`、`--warn`、`--ok`，在 `:root`（浅色）与 `@media (prefers-color-scheme: dark)`（深色）各定义一份。

- [ ] **Step 1: 实现**

- 字号基准 14px，行高 1.5；控件统一高度 30px、圆角 4px。
- 侧栏底色 `--panel`，选中项左侧 2px `--accent` 条。
- diff 配色：`+` 用 `--ok` 底 12% 透明，`-` 用 `--danger` 底 12% 透明。
- 禁用 `user-select` 只作用于导航与标签，输入框与 diff 允许选择复制。
- 不引入任何 CSS 框架与图标字体；图标用内联 SVG（13 个导航图标 + 4 个操作图标）。

- [ ] **Step 2: `pnpm dev` 目视检查浅色/深色两套并提交**

Run: `cd edit_config_gui; pnpm dev` — 打开窗口后逐项确认：改一个字段 → 脏标记与保存按钮在深色下仍可辨；打开 diff 预览 → `+`/`-` 两种底色对比度足够；切到系统深色（设置 → 个性化 → 颜色 → 深色）后重新看一遍。再 `pnpm check` 确认 0 error。

```powershell
git add edit_config_gui/src
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'feat(theme): 浅色深色主题与统一外观' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 21: 替换产物、清理旧实现与文档

**Files:**
- Delete: `edit_config_gui.py`
- Delete: `util/edit_config_gui/`（整目录，14 个 `.py` + `__pycache__`）
- Delete: `edit_config_gui.exe`（构建后由新产物替换）
- Create: `edit_config_gui/scripts/copy-dist.mjs`
- Create: `edit_config_gui/README.md`
- Modify: `readme.md`（4 处）
- Modify: `pyproject.toml`（删掉 `[dependency-groups] editconfiggui`）
- Modify: `.gitignore`（加 `edit_config_gui/node_modules`、`edit_config_gui/dist`、`edit_config_gui/src-tauri/target`）
- Modify: `dev/archive_list.txt`（若含旧路径则同步）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 仓库根出现新的 `edit_config_gui.exe`。

- [ ] **Step 1: 写 `copy-dist.mjs`**

```js
import { copyFileSync, existsSync } from 'node:fs';
const src = new URL('../src-tauri/target/release/edit_config_gui.exe', import.meta.url);
if (!existsSync(src)) { console.error('未找到构建产物:', src.pathname); process.exit(1); }
copyFileSync(src, new URL('../../edit_config_gui.exe', import.meta.url));
console.log('已复制到仓库根: edit_config_gui.exe');
```

- [ ] **Step 2: 构建并验证 exe**

```powershell
cd edit_config_gui
$env:PATH = "$env:USERPROFILE\.cargo\bin;" + $env:PATH
pnpm build:dist
Get-Item ..\edit_config_gui.exe | Select-Object Length,LastWriteTime
```
期望：产物存在（预计 6–12 MB），双击能打开窗口。

- [ ] **Step 3: 删除旧实现（先排查引用再删）**

先跑这三条排查命令，确认不会删出孤儿引用：

```powershell
# 注意：测试目录叫 tests/ 不是 test/；且 repo 里有 .venv/ 与 site-packages/，
# 直接写 glob 会扫出上千条噪声，必须先用 Get-ChildItem 排除。
# 1) 谁还引用旧的配置编辑器入口或包
Get-ChildItem -Recurse -Filter *.py -File |
  Where-Object { $_.FullName -notmatch '\\\.venv\\|\\site-packages\\' } |
  Select-String -Pattern 'edit_config_gui' -List |
  ForEach-Object { $_.Path.Replace((Get-Location).Path + '\','') }
# 2) 谁还 import siui / keyboard
Get-ChildItem -Recurse -Filter *.py -File |
  Where-Object { $_.FullName -notmatch '\\\.venv\\|\\site-packages\\' } |
  Select-String -Pattern 'import siui|from siui|sibase|import keyboard' -List |
  ForEach-Object { "$($_.Path.Replace((Get-Location).Path + '\','')) :$($_.LineNumber) : $($_.Line.Trim())" }
# 3) 打包清单里是否列了旧路径
Select-String -Path dev/archive_list.txt -Pattern 'edit_config_gui'
```

实测预期（已在当前 HEAD `2ad1ca6` 上跑过，结果写死在这里以免执行者误判）：
- ① `edit_config_gui` 的 Python 命中只有 9 个文件：`edit_config_gui.py` 自身 + `util/edit_config_gui/` 下的 8 个 page 文件（client / deeplx / funasr_args / libretranslate / model_paths / paraformer_args / sensevoice_args / server）。`config_selector.py` **不**引用它（只 import PySide6，实测 L9-11 无 siui/sibase）。`dev/check_site_packages_update.py` **零命中**（它只跑 `uv pip list --outdated`）。
- ② `siui` 命中：`edit_config_gui.py:8` + `util/edit_config_gui/` 下 **11** 个文件（about_page / client_config_page / deeplx_config_page / funasr_args_config_page / libretranslate_config_page / model_paths_config_page / paraformer_args_config_page / select_path / sensevoice_args_config_page / server_config_page / set_default_button），**全部随旧包删除**；删除后 `siui` 在仓库业务代码里零命中（`site-packages/siui/` 是手工放进仓库的第三方包，见 §11.1，本次不动它）。
- ③ `keyboard` 命中 6 处：`util/client/` 下 4 个（`check_microphone_usage.py:6`、`pause_other_audio.py:4`、`shortcut_handler.py:8`、`type_result.py:5`，**全部保留**，见 `pyproject.toml:41` 的 client 组）+ `tests/adb_control.py:46`、`tests/hint_while_recording_at_cursor_position_test.py:3`（**保留**，是测试脚本）+ `util/edit_config_gui/value_check.py:4`（随旧包删除）。
- ④ `dev/archive_list.txt`：第 13 行 `edit_config_gui.py` 删掉，第 12 行 `edit_config_gui.exe` 保留（新产物同名，仍要归档）。
- ⑤ 别漏了 `readme.md` 的 6 处（不是 4 处）：L8、L18、L190、L406、L445、L476。Step 4 只逐字给出 L8 / L190 / L406 / L442-446 四处的改法，**L18 与 L476 只需确认措辞仍然成立**（两处都已写的是 `edit_config_gui.exe`，新实现同名，无需改动）；若发现 L18 的「安全地修改」与新交互不符可微调，但不是必改项。

确认无误后删除：

```powershell
git rm -r util/edit_config_gui
git rm edit_config_gui.py
```

- [ ] **Step 4: 改文档**

- `readme.md` L8：`可方便修改大部分配置，更多自定义配置仍需手动修改 config.toml 文件` → `可修改全部配置项（含提示词、API Key、ADB、快捷键等）`。
- `readme.md` L190 附近（暂停快捷键说明）：句末补「；留空表示不暂停」。
- `readme.md` L406 附近：**整行删除**「调试配置编辑器 GUI （edit_config_gui.py） 另需手动下载 siui 放在 .venv/Lib/site-packages」——新实现是单文件 exe，不再需要 Python 与 siui。
- `readme.md` L442–446 的代码块 `uv run edit_config_gui.py` → 「双击 `edit_config_gui.exe`」+ 一行构建说明「源码构建见 `edit_config_gui/README.md`」。
- `pyproject.toml`：**只删** `[dependency-groups]` 里的 `editconfiggui = [...]` 段（pyproject.toml:58-62，2 项有效内容 + 2 行 siui 注释）。**不要**动 `client` 组里的 `keyboard>=0.13.5`（pyproject.toml:41）—— 已实测它被 4 个客户端模块使用：`util/client/check_microphone_usage.py:6`、`util/client/pause_other_audio.py:4`、`util/client/shortcut_handler.py:8`、`util/client/type_result.py:5`。**也不要**动 `tomlkit>=0.15.1`（pyproject.toml:14）—— 它被 `util/config.py:7`、`util/client/hot_update.py:17`、`util/client/shortcut_handler.py:12`、`start_client_gui.py:50` 使用，只有 `util/edit_config_gui/write_toml.py:1` 那处会随旧包一起删除。
- 新建 `edit_config_gui/README.md`：前置工具链（Rust ≥ 1.77.2 + MSVC Build Tools、Node ≥ 20.19、pnpm ≥ 9）、`pnpm install` / `pnpm dev` / `pnpm test` / `pnpm check` / `pnpm build:dist`、产物位置与复制步骤、常见错误（`icons/icon.ico not found`、`link.exe not found`、`cargo: command not found`、`WebView2 Runtime 缺失`）。


- [ ] **Step 5: 跑最终验证**

```powershell
cd edit_config_gui; pnpm test; pnpm check
cd src-tauri; cargo test --release
```
期望：前端与 Rust 测试全绿、`svelte-check` 0 error。

- [ ] **Step 6: Commit**

```powershell
git add -A
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'refactor(edit_config_gui): 用 Tauri 2 产物替换 PySide6 实现并清理旧代码' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```

---

### Task 22: 端到端手工验收

**Files:** 无新增（发现问题回到对应任务修复）

**Interfaces:** 无新增接口。本任务只读取前面 21 个任务的产物并做端到端验证；唯一写入的是 `edit_config_gui/README.md` 的「验收记录」小节。

- [ ] **Step 1: 按规格 §13 的 22 条逐项验证**

规格里的 22 条是最终验收口径，逐条对应如下（括号里是规格条目号）。至少必须实测：

1. 双击仓库根 `edit_config_gui.exe` 打开，13 页全部可切换，无空白页；逐页数一遍控件数，确认 162 键都在（9 个派生键为只读 + 可跳转）（§13-1、§13-13）。
2. 从**另一个工作目录**（如 `C:\Windows\Temp`）启动 exe，确认能读到仓库根 `config.toml`（走 exe 同目录解析）；再把 `config.toml` 临时改名，确认进入引导态且**没有**新建空文件（§13-14）。
3. 改 1 个单行字段后保存 → diff 预览只显示 1 处 → 确认 → `git diff config.toml` 只有 1 行变化；再核 `(Get-Content config.toml -Raw) -match "`n"` 为 false（纯 CRLF）、注释行数仍是 306（§13-2）。
4. 改 3 个字段（分别落在 string / int / bool 上）后保存 → 重新打开核对类型未变：`python -c "import tomllib;d=tomllib.load(open('config.toml','rb'));..."` 检查 `server.speech_recognition_port` 仍是 str、`client.audio_name_len` 仍是 int、`client.hold_mode` 仍是 bool（§13-3）。
5. 保存后核验 `config.toml.bak` 内容为上一版，且 `config.toml` 的 ACL 未变（`(Get-Acl config.toml).Sddl` 前后一致）（§13-4）。
6. 打开编辑器后，用另一个窗口手工改 `config.toml` 一个字节，再点保存 → 出现冲突提示 → 点「重新加载」→ 界面反映外部改动且未覆盖（§13-5）。
7. 4 个暂停快捷键清空后保存 → 重新打开仍为空，不报错（§13-6）。
8. `client.addr` 填公网 IP（如 `8.8.8.8`）→ 可通过；填 `abc` → 被拦下且**输入框内容不被覆写**（§13-7）。
9. `trash_punc` 输入 `[`、`\`、`^`、空串 → 4 种都被拦下并显示「该字符不能用于此处」/「该配置项不能为空」；模板值 `，。,.` 保存后不变，且 `util/client/strip_punc.py` 的正则行为与改动前逐字一致（§13-18）。
10. `disable_exe_list` / `disable_exe_list_on_focus` 显示「暂未添加」；不动它们直接保存 → 回读仍是 `[""]`（§13-15）。
11. 附加特殊应用新增一行 `My App.exe` → 保存后 TOML 合法，大小写保住，`vlc.exe` 行的行尾注释仍在；再删除该行 → 文件恢复原行数（§13-16）。
12. 提示词里粘贴含 `"""`、`\`、`#`、制表符的文本 → 保存后重新打开内容一致，文件仍可解析（§13-2 的延伸）。
13. `client.mic_seg_duration` 手工改成 `120` 后打开编辑器 → 界面显示 120 且标黄提示，其它字段仍可保存；把它改成 30 再保存 → 写回 30（§13-2 的延伸）。
14. 命令面板 `Ctrl+K` 搜「端口」「duankou」「dk」「server.addr」都能命中；`↑↓` 选择、`Enter` 跳转并聚焦、`Esc` 关闭还原焦点；同一查询连跑两次顺序一致；搜 `已隐藏`/`只读` 徽标、secret 值搜不到（§13-20、§13-21）。
15. `client.enable_adb_control=false` 时 `adb_addr` 隐藏；置 true 后填 `192.168.3.127:10101` 可通过保存（§13-19）。
16. 服务端/客户端在跑时状态栏显示正确（真实进程名 `python_CapsWriter_Server.exe` 等，大小写不敏感、`.exe` 可省）（§13-8）。
17. **管理员会话**下启动服务端后点「重启服务端」→ 服务端以 Medium 完整性级别重启（`whoami /groups` 或 Process Explorer 核验），客户端能连上；再确认进程 cwd 是仓库根（服务端能加载到 `models/` 下的模型）（§13-9、§13-17）。
18. 仓库内已无 PySide6 版配置编辑器代码：`git ls-files | Select-String 'edit_config_gui'` 只剩新目录；`readme.md` 4 处已改且 siui 那行已删（§13-10、§13-11）。
19. `cd edit_config_gui; pnpm test; pnpm check` 与 `cd src-tauri; cargo test --release` 全绿（§13-12）。
20. `pnpm build:dist` 后仓库根 `edit_config_gui.exe` 可双击运行（§13-13）。
21. `edit_config_gui/package.json` 的 `dependencies` 里不含 `pinyin-pro`，`src/lib/pinyin-map.json` 已提交，`pinyin_map_covers_all_titles` 测试通过（§13-22）。

- [ ] **Step 2: 记录验收结果到 `edit_config_gui/README.md` 的「验收记录」小节**

（含实测日期、Windows 版本、管理员路径是否验证成功。）

- [ ] **Step 3: Commit**

```powershell
git add edit_config_gui/README.md
Set-Content -Path $env:TEMP\ecg-commit.txt -Value 'docs(edit_config_gui): 补充端到端验收记录' -Encoding UTF8
git commit -F $env:TEMP\ecg-commit.txt
```
