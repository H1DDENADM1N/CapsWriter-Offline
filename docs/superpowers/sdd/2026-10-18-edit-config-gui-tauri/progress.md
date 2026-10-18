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
| 18 | DirtyBar、DiffDialog 与保存流程 | 待办 | — |
| 19 | 进程状态栏、重启与引导态 | 待办 | — |
| 20 | 主题与外观 | 待办 | — |
| 21 | 替换产物、清理旧实现与文档 | 待办 | — |
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