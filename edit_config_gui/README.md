# edit_config_gui

CapsWriter-Offline 的图形化配置编辑器。Tauri 2 + Svelte 5，前端资源内嵌，产物是仓库根的**单文件** `edit_config_gui.exe`。

它取代了原来的 PySide6 + siui 实现。旧实现只覆盖 121/162 个键、写文件时直接截断覆盖，而且校验失败会**把用户输入覆写**成默认值——这三件事是这个重写的主要动机。

## 它做什么

- 覆盖 `config.toml` 的全部 **162 个叶子键**：151 个可编辑 + 9 个由 `model_paths` 派生的只读占位键（可一键跳转到真正生效的那一行）+ 2 个动态表条目。
- 保存前**预览 unified diff**，确认后才写盘；写入用 `ReplaceFileW` 原子替换，原文件备份为 `config.toml.bak`。
- 注释、键序、行尾注释、CRLF、值类型（字符串型的端口、浮点、布尔）全部保持原样——`toml_edit` 在保留装饰的前提下改值，不重新序列化整份文件。
- 打开后如果文件被外部改过，保存时会报冲突，给「重新加载」与「强制覆盖」两个选择，不会静默覆盖。
- 客户端/服务端进程是否在跑会显示在底部状态栏，可直接重启（管理员会话下会尝试降权启动）。若检测到服务端或客户端**以管理员权限运行**，对应的圆点会从绿色变**紫色**（`src/app.css` 的 `--ecg-elevated`，浅色 `#7b3fa0` / 深色 `#d0a8f5`；`aria-label` 为「服务端以管理员权限运行」/「客户端以管理员权限运行」）；此时若管理器自身不是管理员，重启会先在确认框里提示，点「以管理员权限重启」才会弹 UAC 走提权助手。
- 默认窗口 **1122×760**（最小 760×520，可自由缩放）；缩放比例不记忆，每次打开都是 100%。

## 前置工具链

| 工具 | 版本 | 说明 |
|---|---|---|
| Rust | ≥ 1.95 | `rustup` 安装；需要 MSVC Build Tools（`link.exe`）。`rust-version` 由 `sysinfo 0.39` 决定 |
| Node.js | ≥ 20.19 | 构建期脚本用 `node --experimental-strip-types` 直接跑 `.ts` |
| pnpm | ≥ 9 | |
| WebView2 Runtime | 任意近期版本 | Win11 自带；Win10 若缺失需装 Evergreen Runtime |

Rust 若没在 `PATH` 里：

```powershell
$env:PATH = "$env:USERPROFILE\.cargo\bin;" + $env:PATH
```

## 常用命令

```powershell
cd edit_config_gui
pnpm install

pnpm dev          # 只起 Vite，浏览器里看 UI（IPC 会提示「不在 Tauri 窗口中运行」）
pnpm dev:tauri    # 起完整窗口，可读写配置

pnpm test         # 前端 187 个用例 / 13 个文件（schema 12 · 拼音 8 · 搜索 15 · 主题 14 · 缩放 13 · 翻页键 14 · stores 27 · 字段行 13 · 控件 22 · 保存 9 · 导航 15 · 面板 7 · 状态 18）
pnpm check        # svelte-check，必须 0 error 0 warning
pnpm gen:schema-paths   # 改了 schema 后重新生成 Rust 侧的键清单

pnpm build:dist   # 构建 release 并把 exe 复制到仓库根
```

Rust 侧：

```powershell
cd edit_config_gui/src-tauri
cargo test --release   # lib 119 + tests/coverage.rs 2
```

## 产物位置

`pnpm build:dist` 之后：

- `edit_config_gui/src-tauri/target/release/edit_config_gui.exe`（构建产物）
- `edit_config_gui.exe`（仓库根，由 `scripts/copy-dist.mjs` 复制）

前端资源由 Tauri 内嵌进 exe，不需要旁边放 `dist/`。

## 外观：MD3 + 跟随 Windows 主题

界面用 [m3-svelte](https://kendell.dev/m3-svelte/)（Material Design 3 组件库）实现，并且**自动跟随 Windows 的深浅色与主题色**，没有自己的开关。

- 深浅色与主题色都来自注册表，由 Rust 的 `system_theme.rs` 读出来交给前端：
  `HKCU\...\Themes\Personalize\AppsUseLightTheme` 定深浅，
  `HKCU\...\DWM\ColorizationColor` 与 `HKCU\Control Panel\Colors\Hilight` 给主题色候选
  （Windows 在「自动从壁纸取色」时 `ColorizationColor` 可能是近黑色，所以这里给的是**有序候选**，
  由 `lib/theme.ts` 挑第一个 HCT 彩度 ≥ 12 的；都不合格才退回 `#0078d4`）。
- 前端 `lib/stores/theme.svelte.ts` 每 3 秒轮询一次（窗口隐藏时跳过），
  把 HCT 种子色展开成 MD3 的动态色板，注入 `<style id="ecg-m3-tokens">`。
  深浅两套都在同一条 `light-dark()` 里，切哪套只取决于 `color-scheme`——所以
  **不要在任何 CSS 里写 `@media (prefers-color-scheme: dark)`**，WebView2 的媒体查询来源
  不保证等于 Windows 的「应用模式」设置，两套判据并存只会互相打架。
- 组件只认语义令牌 `--ecg-*`（`app.css` 把 `--m3c-*` 翻译过来）：`--ecg-panel`、`--ecg-danger`、
  `--ecg-add-bg`……组件里不写任何 hex。状态色（绿=在跑、紫=管理员、黄=警告、红=错误）**故意不跟着
  主题色走**，否则种子色是绿色时警告也变绿，指示意义就没了。
- `m3-svelte` 的 `Button`/`TextField`/`Select` 用草案 CSS 函数 `@apply --m3-*` 与
  `--m3-density()`，需要 `vite-plugin-functions-mixins` 在构建期展开；该函数包内没有默认实现，
  由 `app.css` 里的 `@function --m3-density` 补上（`--ecg-density` 可整体缩放密度）。
- 枚举下拉的候选列表（`::picker(select)`）**必须由 `app.css` 里不带任何前缀的规则**接管：
  只有在 picker 自己身上声明 `appearance: base-select`，浏览器才会把列表当成页面内盒子画，
  否则走平台原生菜单——在 WebView2 里那个菜单固定浅色，主题管不到。而 `m3-svelte` 里那条
  `::picker(select)` 会被 Svelte 加上作用域类（`.svelte-xxxx::picker(select)`），Chromium 只认
  挂在 `<select>` 上的 picker 伪元素，于是那条规则等于失效（这就是「下拉列表始终浅色」的成因）。
  同理，picker 内部只能写普通 `option` 选择器——`::picker(select) option` 这种「伪元素后跟选择器」
  会被 lightningcss 判为语法错误，构建直接失败。列表用 `right: anchor(right)` 右对齐到选择框，
  比选择框宽时朝左展开，不会顶出窗口被裁掉。
- 样式表用相对路径导入：`import '../node_modules/m3-svelte/package/etc/styles.css'`。
  走包名 `m3-svelte/etc/styles.css` 会被 Vite 8 拒绝（该子路径只声明在 exports 的 `style` 条件下），
  而给 `resolve.conditions` 加 `style` 又会把 Svelte 的**服务端**渲染树拉进浏览器产物。

## 缩放与键盘

| 快捷键 | 作用 |
|---|---|
| `Ctrl` + `=` / `Ctrl` + `+` | 放大一档 |
| `Ctrl` + `-` | 缩小一档 |
| `Ctrl` + 滚轮 | 放大 / 缩小（一次手势只算一档） |
| `Ctrl` + `0` | 回到 100%（顶栏的「还原」按钮同理） |
| `Ctrl` + `F` | 搜索配置项（早期版本是 `Ctrl+K`） |
| `Ctrl` + `S` | 预览保存：先看 diff，确认后才写盘 |
| `PageUp` / `PageDown` | 翻一屏（90% 视口，留一条重叠带） |
| `↑` / `↓` | 滚动 80px |
| `Esc` | 关闭搜索面板 / 保存预览对话框 |

几条实现上的取舍：

- **缩放**档位 50%–200%，只在本次会话有效（不写盘，也不进 `config.toml`）。走 Rust 的 `set_zoom`
  （webview 缩放），不用 CSS `zoom`——后者不参与媒体查询与 `vw`/`vh` 计算，断点行为会和浏览器不一致。
  不是 100% 时，顶栏「搜索配置」左侧出现 `110% 还原`，点一下回 100% 后按钮自己消失；
  用快捷键或滚轮缩回 100% 也会消失，因为按钮看的是状态而不是某一次点击。
- **翻页键**在焦点位于 `input`/`textarea`/`select`/可编辑区里时**不接管**，命令面板或保存预览
  对话框开着时也不接管——那些地方的方向键归控件自己。判定逻辑在 `lib/scrollKeys.ts`，是纯函数。

## 跳转定位与高亮

从搜索结果（`Ctrl+F`）跳转，或点只读派生键的「跳转到『…』」，都会切到目标键所在的页，**并把那一行滚到视口中部**，同时让该行闪一次。

- 跳转只经过 `stores/nav.svelte.ts` 的 `focus(segments)`：它负责切页、记下要高亮的 `fieldId`，并在 1.5 秒后自己清掉。页 id 靠 `pageOfSegments()` 反查而不是拿 `segments[0]` 猜——`client.zhipuai` 属于「AI 服务商」页、`client.prompt_style` 属于「提示风格」页，按段名猜会跳错页。
- 真正滚动的是 `Field.svelte` 里的 `$effect`：它读 `navStore.pulse()`（每次 `focus()` 自增的计数器）而不是只读 `highlight`，否则连着跳同一项时 `highlight` 的值没变，`$effect` 不重跑，滚动会停在上一轮。滚动用 `block: 'center'`，系统开了「减少动画」时用 `behavior: 'auto'`。
- 闪烁是**声明式**的 `class:flash`，由 `highlight === id && pulse > 0` 推导，动画 1.4 秒播一次。**不能**用 `classList.add('flash')`：这一行的 `class` 属性里有 `class:wide` / `class:bool` 动态指令，Svelte 会在后续更新时整串重写 class 属性，手加的类当场被抹掉（症状是「怎么都不闪」）。同理，`@keyframes` 只改背景与描边、不做位移，免得把正在读的行推走。

## 改 schema 的注意事项

字段元数据在 `src/lib/schema/*.ts`，是**唯一**的界面来源：控件、校验器、显隐条件、搜索关键词都由它驱动。

改完必须同步三处，否则测试会红：

1. `pnpm gen:schema-paths` —— 生成 `src-tauri/tests/schema_paths.json`；
2. `node scripts/gen-pinyin-map.mjs` —— 新增标题里的汉字要进拼音表，否则 `Ctrl+F` 搜不到；
3. `pnpm test` —— `coverage.test.ts`（前端）与 `tests/coverage.rs`（Rust）会双向核对「模板里的键」与「schema 里的键」是否一致。

`pinyin-pro` 只在生成脚本里用，运行期不加载。

## 常见错误

| 现象 | 原因与处理 |
|---|---|
| `icons/icon.ico not found; required for generating a Windows Resource file` | `src-tauri/icons/icon.ico` 缺失。`tauri-build` 生成 Windows 资源文件必须要它 |
| `link.exe not found` | 缺 MSVC Build Tools，装 Visual Studio Build Tools 的「C++ 生成工具」 |
| `cargo: command not found` | `%USERPROFILE%\.cargo\bin` 不在 `PATH` |
| 窗口白屏 / `WebView2` 相关错误 | 缺 WebView2 Runtime |
| 保存报 `CONFLICT` | 文件在打开后被外部改过（config_selector、其它编辑器、上一次会话）。选「重新加载」看新内容，或「强制覆盖」 |
| 保存报 `拒绝访问。 (os error 5)` | `config.toml` 只读或被占用；关掉占用它的编辑器再试 |
| 状态栏提示「未能以普通权限启动服务端」 | 管理器以管理员身份运行，降权启动失败。服务端会以高权限启动，客户端可能连不上；用非管理员方式启动服务端 |
| 左下服务端/客户端指示为**紫色** | 对应的服务端/客户端以管理员权限运行（`aria-label` 分别为「服务端以管理员权限运行」/「客户端以管理员权限运行」）。这是正常状态，不是错误；重启它需要提权（绿=普通权限运行中，灰=未运行） |
| 重启服务端后指示由紫转绿 | 服务端以管理员权限运行时，非管理员管理器重启它同样先提示提权。提权助手对服务端按 `DowngradeWhenAdmin` 策略拉起，所以重启后它会**回到普通权限**（指示转绿）；客户端按 `InheritToken` 保持提权形态（仍紫色） |
| 重启客户端报「结束进程失败：拒绝访问（需管理员权限）」 | 客户端以管理员权限运行，而管理器自身不是管理员，`taskkill` 被系统拒绝。在确认框里点「以管理员权限重启」并在 UAC 弹窗选「是」；选「否」会得到「已取消管理员授权（UAC），未做任何改动」，此时磁盘与进程零改动 |
| `pnpm build:dist` 末尾报 `EBUSY: resource busy or locked, copyfile ... edit_config_gui.exe` | 管理器正开着，仓库根的 exe 被占用（Rust 编译其实已经成功）。先关掉 `edit_config_gui.exe`，再单独跑 `node scripts/copy-dist.mjs` |

## 为什么不用 `std::fs::rename` 做原子替换

实测：`Move-Item -Force` 与 `std::fs::rename` 都会**丢掉目标文件的自定义 ACL**（例如别人给 `config.toml` 加的 `Everyone:(R)`），而 `ReplaceFileW` 保留。用 `ReplaceFileW` 的第三个参数传备份路径，备份与替换是一步完成的，不会出现「备份好了但替换失败」的中间态。

## 目录

```
edit_config_gui/
├─ src/                  # Svelte 前端
│  ├─ lib/schema/        # 字段元数据（162 键的唯一来源）+ 覆盖断言
│  ├─ lib/components/    # 字段行、控件、导航、对话框
│  ├─ lib/stores/        # 配置状态、保存状态机、导航、命令面板、主题、缩放
│  ├─ lib/theme.ts       # 种子色 → MD3 色板（纯函数，可测试）
│  ├─ lib/scrollKeys.ts  # 翻页/方向键该不该接管（纯函数，可测试）
│  └─ bridge.ts          # 唯一 import invoke 的地方
├─ src-tauri/src/        # Rust
│  ├─ config_doc.rs      # 解析 / CRLF 归一化 / 叶子枚举
│  ├─ patch.rs           # 补丁应用（decor 搬运、动态表、diff）
│  ├─ validate.rs        # 10 个校验器
│  ├─ file_io.rs         # 指纹 / ReplaceFileW / 回滚
│  ├─ hotkey.rs          # 与 Python keyboard 逐字等价的解析器
│  ├─ process.rs         # 进程检测、服务端/客户端令牌完整性、受限重启（含 taskkill 输出解码）
│  ├─ elevate.rs         # 提权助手：runas 拉起自身、结果文件回传（一次性、无窗口）
│  ├─ system_theme.rs    # 从注册表读 Windows 深浅色与主题色候选
│  └─ commands.rs        # 11 个 IPC 命令
└─ scripts/              # 构建期脚本（键清单、拼音表、复制产物）
```
