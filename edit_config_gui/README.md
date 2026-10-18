# edit_config_gui

CapsWriter-Offline 的图形化配置编辑器。Tauri 2 + Svelte 5，前端资源内嵌，产物是仓库根的**单文件** `edit_config_gui.exe`。

它取代了原来的 PySide6 + siui 实现。旧实现只覆盖 121/162 个键、写文件时直接截断覆盖，而且校验失败会**把用户输入覆写**成默认值——这三件事是这个重写的主要动机。

## 它做什么

- 覆盖 `config.toml` 的全部 **162 个叶子键**：151 个可编辑 + 9 个由 `model_paths` 派生的只读占位键（可一键跳转到真正生效的那一行）+ 2 个动态表条目。
- 保存前**预览 unified diff**，确认后才写盘；写入用 `ReplaceFileW` 原子替换，原文件备份为 `config.toml.bak`。
- 注释、键序、行尾注释、CRLF、值类型（字符串型的端口、浮点、布尔）全部保持原样——`toml_edit` 在保留装饰的前提下改值，不重新序列化整份文件。
- 打开后如果文件被外部改过，保存时会报冲突，给「重新加载」与「强制覆盖」两个选择，不会静默覆盖。
- 客户端/服务端进程是否在跑会显示在底部状态栏，可直接重启（管理员会话下会尝试降权启动）。若检测到服务端或客户端**以管理员权限运行**，对应的圆点会从绿色变**紫色**（浅色 `#8e44ad` / 深色 `#c084fc`，`aria-label` 为「服务端以管理员权限运行」/「客户端以管理员权限运行」）；此时若管理器自身不是管理员，重启会先在确认框里提示，点「以管理员权限重启」才会弹 UAC 走提权助手。

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

pnpm test         # 前端 133 个用例 / 10 个文件（schema 12 + 拼音 8 + 搜索 15 + stores 27 + 控件 16 + 渲染 9 + 导航 12 + 面板 7 + 保存 9 + 状态 18）
pnpm check        # svelte-check，必须 0 error 0 warning
pnpm gen:schema-paths   # 改了 schema 后重新生成 Rust 侧的键清单

pnpm build:dist   # 构建 release 并把 exe 复制到仓库根
```

Rust 侧：

```powershell
cd edit_config_gui/src-tauri
cargo test --release   # lib 109 + tests/coverage.rs 2
```

## 产物位置

`pnpm build:dist` 之后：

- `edit_config_gui/src-tauri/target/release/edit_config_gui.exe`（构建产物）
- `edit_config_gui.exe`（仓库根，由 `scripts/copy-dist.mjs` 复制）

前端资源由 Tauri 内嵌进 exe，不需要旁边放 `dist/`。

## 改 schema 的注意事项

字段元数据在 `src/lib/schema/*.ts`，是**唯一**的界面来源：控件、校验器、显隐条件、搜索关键词都由它驱动。

改完必须同步三处，否则测试会红：

1. `pnpm gen:schema-paths` —— 生成 `src-tauri/tests/schema_paths.json`；
2. `node scripts/gen-pinyin-map.mjs` —— 新增标题里的汉字要进拼音表，否则 `Ctrl+K` 搜不到；
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

## 为什么不用 `std::fs::rename` 做原子替换

实测：`Move-Item -Force` 与 `std::fs::rename` 都会**丢掉目标文件的自定义 ACL**（例如别人给 `config.toml` 加的 `Everyone:(R)`），而 `ReplaceFileW` 保留。用 `ReplaceFileW` 的第三个参数传备份路径，备份与替换是一步完成的，不会出现「备份好了但替换失败」的中间态。

## 目录

```
edit_config_gui/
├─ src/                  # Svelte 前端
│  ├─ lib/schema/        # 字段元数据（162 键的唯一来源）+ 覆盖断言
│  ├─ lib/components/    # 字段行、控件、导航、对话框
│  ├─ lib/stores/        # 配置状态、保存状态机、导航、命令面板
│  └─ bridge.ts          # 唯一 import invoke 的地方
├─ src-tauri/src/        # Rust
│  ├─ config_doc.rs      # 解析 / CRLF 归一化 / 叶子枚举
│  ├─ patch.rs           # 补丁应用（decor 搬运、动态表、diff）
│  ├─ validate.rs        # 10 个校验器
│  ├─ file_io.rs         # 指纹 / ReplaceFileW / 回滚
│  ├─ hotkey.rs          # 与 Python keyboard 逐字等价的解析器
│  ├─ process.rs         # 进程检测、服务端/客户端令牌完整性、受限重启（含 taskkill 输出解码）
│  ├─ elevate.rs         # 提权助手：runas 拉起自身、结果文件回传（一次性、无窗口）
│  └─ commands.rs        # 9 个 IPC 命令
└─ scripts/              # 构建期脚本（键清单、拼音表、复制产物）
```
