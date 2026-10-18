# SDD 进度台账 —— edit_config_gui（Tauri 2 + Svelte 5）

计划：`docs/superpowers/plans/2026-10-18-edit-config-gui-tauri.md`
规格：`docs/superpowers/specs/2026-10-18-edit-config-gui-tauri-design.md`
分支：`CapsTranser`

## 任务状态

| Task | 内容 | 状态 | 提交 |
|---|---|---|---|
| 1 | 项目骨架与构建链 | 完成 | `e31409d` |
| 2 | config_doc（解析/归一化/输出/叶子枚举） | 完成 | `c06cdf5` |
| — | vitest 配置与 MSRV 修正 | 完成 | `f9e4461` |
| 3 | patch（decor/类型保真、动态表、diff） | 完成 | `4a2298e` |
| 4 | hotkey（键名表导出与等价解析器） | 完成 | `8717ec3` |
| 4b | hotkey 对拍集补全 | 完成 | `b6cfd1c` |
| 5 | validate（10 个校验器） | 完成 | `3919c29` |
| 6 | file_io（指纹/ReplaceFileW 原子提交/回滚） | 完成 | `1e313cb` |
| 7 | model_paths_resolve（9 个派生只读键） | 完成 | `1933696` |
| — | patch 排版守护用例补强 | 完成 | `fcec6aa`、`60ac778` |
| 8 | process（运行检测与受限重启） | 完成 | `5500325` |
| 10 | 前端 schema 基础（类型/schema/debug+server） | 完成 | `4302da2` |
| 11 | 前端 schema —— client 主表 72 键 | 完成 | `1b2b32b` |
| 12 | 前端 schema 完成 —— 其余 8 页 + 覆盖闭环 | 完成 | `d8529a0` |
| 9 | commands（7 个 IPC 命令与状态装配） | 完成 | `bb71207` |
| 9b | 指纹结构补 camelCase（保存链路阻断缺陷） | 完成 | `5da8acd` |
| 13 | bridge 与配置状态层 | 完成 | `6be48ea` |
| 14 | 控件库（13 个 widget） | 完成 | `a0a7ddd` |
| 15 | Field 与 Section 渲染层 | 待办 | — |
| 16 | 侧边导航、页面容器与 App 装配 | 待办 | — |
| 17 | 搜索与命令面板 | 待办 | — |
| 18 | DirtyBar、DiffDialog 与保存流程 | 完成 | `47badfb` |
| 19 | 进程状态栏、重启与引导态 | 完成 | `ec0d25e` |
| 20 | 主题与外观（设计令牌 + 深色 + 内联图标） | 完成 | `49f2650` |
| 21 | 替换产物、清理旧实现与文档 | 完成 | 见下一提交 |
| 22 | 端到端手工验收 | 待办 | — |

## 已确立的关键约束（实现时不可违反）

- **162 个叶子键全覆盖**：151 可编辑固定键 + 9 派生只读 + 2 动态表条目。
  `pnpm gen:schema-paths` 生成 `src-tauri/tests/schema_paths.json`；
  `coverage.test.ts`（前端 12 例）与 `tests/coverage.rs`（Rust 2 例）双向锁死。
- **注释/键序/CRLF/值类型全保留**：`config_doc` 统一把 CRLF 归一成 LF 再交给
  `toml_edit`，输出时还原；标量与内联表成员的 decor（prefix/suffix）必须搬运。
- **原子写入用 `ReplaceFileW`**，不用 `std::fs::rename`（实测 rename 会丢自定义
  ACL）。失败从 `.bak` 回滚。
- **9 个 `${model_paths.…}` 占位符键是死键**：`util/config.py:241-278` 直接读
  `model_paths` 段，不解析占位符。UI 里只读展示，绝不写回。
- **动态表 `client.additional_special_apps` 必须逐项 insert/remove**，不能整表
  重建（会丢行尾注释）；进程名大小写敏感、不可归一化。
- 单行键禁用换行；只有 8 个提示词正文（`longText`）允许换行。

## 与计划的偏差（均为实现必需，已落地）

- `stores/config.ts` → `stores/config.svelte.ts`（同理 `nav`、`toast`）：runes 只在
  `.svelte.ts` 里被编译器处理，放 `.ts` 里 `$state` 会原样进产物、组件拿不到响应式。
- 控件额外拆出 `widgets/props.ts` 统一 `WidgetProps`，避免 13 份重复的 props 声明。
- `EnumWidget` 的 `options` 只接受 `{value,label}[]`（`types.ts` 就是这么定义的），
  不再兼容裸字符串；日志级别等 label≠value 的场景本来就需要对象。

## 踩过的坑（写代码前先看一眼）

- `.svelte.ts` 里读 `$state` 变量会被编译器改写成 `$.get(doc)`。若写成
  `doc()` 去调自己的访问器，就变成 `$.get(doc)()`，运行时报
  `get(...) is not a function`，且栈指向调用处而非定义处。模块内部一律直接读变量。
- 6 个控件的初值在 `$state(...)` 里直接读了 `value`，触发
  `state_referenced_locally` 警告；改成从闭包取初值。
- 测试里 `getByRole('spinbutton')` 要求 `input[type=number]`；`IntWidget` 的
  `onchange` 必须读 `el.value` 而不是本地 state，否则 `fireEvent.change` 只改 DOM
  不触发 `input`，夹取拿到的还是旧值。

## 已知不可测点

- `file_io::atomic_write` 里的 `sync_all()`：只在断电/掉盘语义上有区别，单进程
  测试无法证伪。去掉后全套测试仍绿，故保留该行并在此登记。

## 前端实现的补充约束（Task 14–17 期间确立）

- 组件值不能用 `$derived` 存再 `<Widget />`：Svelte 5 不会把它当组件渲染，控件容器会
  空白。用 `{@const Widget = widgetFor(field.widget)}`。
- store 是模块级 `$state`：测试里改完必须 `await tick()`（从 `svelte` 导入）再看 DOM。
- `pageOfSegments()` 是**前缀**匹配：动态表的行是 4 段，表本身只登记 2 段。
- 拼音表是构建期产物（`scripts/gen-pinyin-map.mjs` → `src/lib/pinyin-map.json`，827 字）；
  新增字段必须重跑，`pinyin_map_covers_all_titles` 会拦。
- 首字母搜索允许「包含」而不只是前缀（中文标题多为长定语，用户常敲后半截如 `dk`）。
## Task 22 端到端验收（真机实测）

在仓库根直接跑 `edit_config_gui.exe`（10,334,720 字节）逐项验收，以下均为实测通过：

1. 启动即定位到仓库根的 `config.toml`，13 页导航齐全；深色主题下正文与输入框对比度足够。
2. `Ctrl+K` 命令面板：输入「日志」命中 2 条（`funasr_args.verbose`、`debug.logger_level`），
   ↑↓ + Enter 直接切到「调试」页。
3. 改值后字段旁出现「已修改」、左侧对应页出现计数徽标、底部出现「1 项未保存」+
   「全部还原」/「保存…」。
4. `Ctrl+S` 弹出的确认框渲染 unified diff：`+++`/`---` 与 `@@` 不着色，`-`/`+` 分别红/绿，
   **行尾 `# 调试日志级别` 在原值行与新值行两侧都保留**。
5. 写入后回读校验通过并报出备份路径；磁盘实测 `git diff` 仅 1 行、852 行全 CRLF、
   306 行注释不变、无 BOM、`.bak` 里是旧内容。
6. 外部改盘（`git checkout -- config.toml`）后再保存 → 命中指纹冲突，弹「配置文件已被
   外部修改」；点「重新加载」丢弃改动并从盘上重读（值回到 DEBUG、徽标清空）。
7. 「全部还原」把脏值恢复成打开时的基线。

未能自动化的一项：状态栏的「重启服务端 / 重启客户端」按钮只在对应进程运行时才出现，
本次没有启动真实服务，故该路径仅由 `status.test.ts` 的 8 例覆盖（含确认弹窗与降权提示），
**未做真机重启**。

### 验收中修掉的三个问题

- **设计变量缺失**：控件里用了 `var(--ecg-input-bg, #fff)` 等 4 个 `app.css` 从未定义的
  变量，深色下退化成白底 + 浅灰字，输入内容几乎看不见。补齐 `--ecg-input-bg`、
  `--ecg-readonly-bg`、`--ecg-muted-strong`、`--ecg-mono`、`--ecg-warn-*`、`--ecg-tag-*`
  两套主题值，并把 DiffDialog / StatusBar 里硬编码的警告色与标签色改成走变量。
- **只读派生键出现两个跳转按钮**：`Field.svelte` 的「来源：… + 跳转到来源」与
  `ReadonlyWidget` 的「跳转到「X」」语义重复。来源说明与跳转统一由 `ReadonlyWidget` 负责。
- **枚举框键盘改值不立即置脏**：Chromium 对闭合的 `<select>` 要等提交或失焦才派发
  `change`，用户在那之前看不到任何反馈。`EnumWidget` 同时挂 `oninput` 与 `onchange`。

## 验收后的界面调整（提交 72f0fbd）

用户在真机验收后提了五条，均已完成：

1. **主内容自动拉伸**：`PageView.svelte` 去掉 `max-width: 820px`，改 `width: 100%`。
   原宽度让模型路径这类 80+ 字符的值读不全，右侧还空一大片。
2. **侧边栏可折叠**：新增 `src/lib/stores/ui.svelte.ts`（折叠状态存 localStorage，
   键 `ecg.sidebar.collapsed`）。折叠后 56px 图标列、`.title` 隐藏、徽标缩成右上角
   小圆点，`aria-label` / `title` 保留完整页面名。
3. **右上角全局搜索按钮**：新增 `TopBar.svelte`，折叠按钮 + 页面标题 + 搜索按钮
   （带 `Ctrl K` 提示），点按即 `paletteStore.show()`。
4. **关于页**：新增 `src/lib/components/pages/AboutPage.svelte` —— 简介、四项能力、
   三个 GitHub 链接（项目主页 / 提交问题 / 下载发布版）、当前配置文件路径与生效
   方式、快捷键表。链接走新增的 Rust 命令 `open_url`。
5. **「关于」置底**：`Sidebar.svelte` 拆成 `.list`（12 个配置页）+ `.foot`（关于，
   上方一条分隔线）。

### 新增的安全边界

`commands.rs::open_url` 只放行 `https://`（`check_url`）：该命令把字符串交给系统
协议处理器，`file://` 能打开本地文件、`ms-settings:` 之类自定义协议能拉起别的
程序，而它的入参最终来自渲染进程。`shell_open` 用 `ShellExecuteW`（项目已依赖
windows-sys，不引新 crate），返回 `<= 32` 视为失败并把错误码回传。

### 本轮踩到的坑

`AboutPage` 的链接卡片一开始只排得下两列、第三张掉到第二行：`.link-url` 的
`white-space: nowrap` 让卡片的最小内容宽度等于整条 URL（`min-width: 0` 缺失时
`text-overflow` 也没机会生效）。另外 `auto-fit` 的 `minmax` 从 240px 降到 220px，
因为主区可用宽度只有 ~730px，3×240 + 2 个 gap = 736 差一点排不下。

## 重启管理员客户端：乱码修复 + 金黄指示 + 提权助手（2026-10-19）

> 后续变更（同日）：指示颜色由金黄改为**紫色**，提权检测扩展到**服务端**；见本文末「提权指示改为紫色 + 检测扩展到服务端」。本节记录的是当时的实现与证据。

用户报：客户端以管理员权限运行时，非管理员的 `edit_config_gui` 点「重启客户端」得到
`重启失败：结束进程失败：taskkill start_client_gui_admin.exe 失败（退出码 1）：…拒绝访问`，
而且整串是乱码。三项改动（Rust 与前端并行实现；独立验证见
`verification/2026-10-19-elevation-restart.md`）：

1. **乱码根因与修法**：`taskkill` 的中文文案是 **cp936** 字节，旧代码
   `String::from_utf8_lossy(stdout)+from_utf8_lossy(stderr)` 解出来全是替换字符。新增
   `process::decode_console_output`：按 `GetACP()` 用 `MultiByteToWideChar`（先严格
   `MB_ERR_INVALID_CHARS`、失败再放宽）→ `String::from_utf16`，都失败才回落
   `from_utf8_lossy`。非零退出分类抽成纯函数 `classify_taskkill`：退出码 128 或
   「没有找到/找不到/not found」→ `NotFound`（继续）、「拒绝访问 / access is denied」→
   `ProcError::AccessDenied`、其余 → 可读的 `Kill`。`AccessDenied` 在命令层还会被映射成
   `needsElevation=true`（预检为假但 kill 时才被拒的安全网）。
2. **管理员客户端检测**：`process::process_is_elevated(pid)` =
   `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` → `OpenProcessToken(TOKEN_QUERY)` →
   `GetTokenInformation(TokenElevation)`，任何一步失败返回 `None`、绝不 panic（受保护进程
   打不开是正常的）。`RunningInfo` 新增 `client_admin`；状态栏客户端圆点新增 `.dot.admin`
   （金黄 `var(--ecg-warn, #b8860b)`，声明在 `.dot.on` 之后 → 同特异性覆盖绿），`aria-label`
   三态（管理员/运行中/未运行）。所有 token 查询都失败时回退「检测到的变体是 admin 启动器」。
   **实测证据**：本非管理员 Medium 会话能查询**同用户提权**进程（PowerToys.exe、
   SystemInformer.exe、sing-box.exe 等实测 `TokenIsElevated=1`），只有 SYSTEM / 受保护进程
   返回 `None`（`OpenProcess` 错误 5）——真实场景下金黄判定可靠，变体回退只是兜底。
3. **重启前提权（两阶段确认 + 一次性助手）**：`process::needs_elevation(target)` 在任何 kill
   **之前**预检，为真就直接返回 `needs_elevation=true`、**一个进程都不结束**（非管理员 kill
   提权进程只会拿到「拒绝访问」，还会先把同组普通进程杀掉、留下半重启的坏状态）。前端
   `doRestart` 收到 `needsElevation` 时不关对话框、切到提权阶段；点「以管理员权限重启」才调
   `restart_service_elevated`，取消/失败走 `重启失败：${e}`。Rust 侧 `elevate.rs` 用同一个 exe
   以 `runas` 拉起自己（`--elevated-restart=<server|client> --nonce=<hex>`、`SW_HIDE`、
   `SEE_MASK_NOCLOSEPROCESS`），助手在 `main()` 最开头被 `run_if_requested()` 拦截（绝不进
   Tauri、绝不显示窗口），按 `LaunchPolicy`（Server → `DowngradeWhenAdmin`、Client →
   `InheritToken`）在提权上下文里结束并重新拉起，结果写
   `%TEMP%\edit_config_gui_elevated_<nonce>.txt` 由父进程读回；UAC 取消（错误码 1223）→
   「已取消管理员授权（UAC），未做任何改动」。nonce 只允许十六进制（校验不过的错误路径再过滤
   成字母数字），`../` 之类的路径穿越拼不出来。

### 测试与验证

- `cargo test --release` → lib **109**（新增 `decode_console_output` 2 例、`classify_taskkill`
  1 例、`process_is_elevated` 1 例、`client_admin` 三分支 2 例）+ `tests/coverage.rs` 2，全绿、
  无 warning。
- `pnpm test` → 10 files / **129** tests（`status.test.ts` 8 → 14）；`pnpm check` 0 error 0 warning。
- 独立验证报告：8 条验收项 + 逐行核对 + 真实 release 产物探针；发现 F1（读结果失败路径漏
  `CloseHandle`/漏删临时文件）与 F2（`WAIT_FAILED/WAIT_ABANDONED` 被并入超时文案），本轮已
  用 `HelperGuard`（`Drop` 统一清理）与等待码 `match` 修掉。
- **未做真实 UAC 端到端**（本会话非交互、非管理员）：同意/取消两条路径、以及换管理员账号
  授权（over-the-shoulder，助手 `%TEMP%` 与父进程不同）需在交互提权会话手工验证，步骤见
  验证报告第 5 节。

### 本轮踩到的坑

- windows-sys 0.59 里 `ShellExecuteExW` / `SHELLEXECUTEINFOW` 被
  `#[cfg(feature = "Win32_System_Registry")]` 门控（结构体带 `hkeyClass` 字段），不加该 feature
  编不过；`GetACP`/`MultiByteToWideChar` 需要 `Win32_Globalization`。
- 任务书里给的 cp936「拒绝访问」字节 `E6 8B 92 E7 BB 9D E8 AE BF E9 97 AE` 其实是它的
  **UTF-8** 编码；真 GBK 是 `BE DC BE F8 B7 C3 CE CA`（按 GBK 字节单测已核对）。
- 本机 `taskkill` 输出是英文 ASCII（ACP 仍是 936），所以真正命中分类的是 `128 / not found`
  与 `access is denied` 两个分支；中文分支只由单测覆盖。

## 提权指示改为紫色 + 检测扩展到服务端（2026-10-19）

用户后续要求：不要金黄，改为**紫色**；并且不只是客户端，**服务端**也要检测是否以管理员权限
运行。两处改动（Rust 与前端并行，写入范围互不重叠；独立复核见验证报告第 8 节）：

1. **服务端提权检测**：`process::scan()` 本来就在一遍扫描里记录了 `server_elevated`（任一命中
   `SERVER_PROCS` 的进程 `TokenIsElevated=1`），但没往外暴露。`RunningInfo` 新增 `server_admin`
   （`detect()` 填 `scan.server_elevated`），与 `needs_elevation(target)` 的 `Server` 分支
   **同源同值**——前端渲染的紫色与后端「要不要走提权」来自同一个布尔，不会出现「显示紫色却直接
   kill」或「绿色却弹 UAC」的错配。token 查询全失败时为 `false`：服务端没有 `admin 变体` 那样的
   字面量线索，不猜（宁可尝试 kill 拿一个明确的拒绝访问）。
2. **前端紫色指示**：新增设计令牌 `--ecg-elevated`（浅色 `#8e44ad`、深色 `#c084fc`），服务端与
   客户端圆点都用 `class:admin={info?.server/client === true && info?.serverAdmin/clientAdmin === true}`
   + `aria-label` 三态；`.dot.admin` 仍声明在 `.dot.on` 之后（同特异性、后声明覆盖绿色）。确认框
   预提示泛化成按 target 取字段：`{targetLabel(target)}以管理员权限运行，重启需要提权（会弹出 UAC 确认）`。
3. **语义边界**：提权助手对服务端用 `DowngradeWhenAdmin`（既有约定：服务端不该带着管理员权限跑，
   否则客户端可能连不上），所以**提权重启后服务端会回到普通权限、指示由紫转绿**；客户端用
   `InheritToken`，保持提权形态（仍紫色）。这不是 bug，是两条不同的启动策略。

### 测试与验证（本轮）

- `pnpm test` → 10 files / **133** tests（`status.test.ts` 14 → 18，新增 4 个服务端用例）；
  `pnpm check` 0 error 0 warning。
- `cargo test --release` → lib **109** + `tests/coverage.rs` 2，全绿、无 warning（本轮不加 Rust
  用例，只在 `detect_does_not_panic` 里补了「未运行的服务端不可能被判定为提权」的不变量断言）。
- 未验证：真实以管理员权限运行的服务端进程上的 `server_admin` 取值（本机没有提权服务端在跑）；
  真实 UAC 端到端仍同上一节。

### 产物级复核（Lead）

源码冻结后 `pnpm build:dist`（vite 434ms + cargo release 40.95s，退出码 0）统一重建产物：仓库根
`edit_config_gui.exe` 与 `src-tauri/target/release/edit_config_gui.exe` 均 10,470,400 B、07:29:04，
SHA256 相同（`3612E853…`）。exe 字节扫描命中本次 vite 产出的哈希资源名 `index-CayQwl-Z.css` /
`index-DEFXsB9n.js`（旧的金黄版哈希不同 → 证明内嵌的是紫色版前端），以及 Rust 侧串
`serverAdmin`、`restart_service_elevated`。构建后 CSS 中 `.dot.on` 先于 `.dot.admin` 声明、取色
`var(--ecg-elevated,#8e44ad)`。新 exe 冒烟：助手参数校验 `--elevated-restart=bogus --nonce=zz`
→ 退出码 2 + 中文错误文件（已删、`%TEMP%` 无残留）；GUI 启动 5 秒存活、标题「配置编辑器」、
关闭后无 `edit_config_gui`/WebView2 孤儿。详见验证报告 §9。
