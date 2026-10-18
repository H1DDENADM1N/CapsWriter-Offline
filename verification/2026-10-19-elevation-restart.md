# task-3 独立验证报告：提权重启 / 管理员客户端检测 / taskkill 乱码修复

- 验证者：teammate `verifier`（独立于实现者）
- 仓库/分支：`C:\Users\user0\Documents\CapsWriter-Offline`，`CapsTranser`，HEAD `7b63bd5`
- 验证时间：2026-10-19
- 被验交付：`edit_config_gui` 的「taskkill 乱码修复 + 管理员客户端检测 + 提权助手 + 前端两阶段提权确认」

## 0. 方法与环境

- 环境事实（自测）：`whoami` = `rm\user0`；`whoami /priv`/令牌完整性 = **Medium Mandatory Level（S-1-16-8192）**，非提权会话（Administrators 为「Group used for deny only」）；Windows 活动代码页 = **936**；验证期间本机**无任何** CapsWriter 相关进程在跑（`Get-Process` 按 `caps|start_(server|client)|deeplx|hint_while` 匹配 = 0）。
- 硬约束执行：Rust 不在 PATH，所有 cargo 命令前加 `$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"`；**未运行任何会真实结束/拉起 CapsWriter 进程的命令，未触发 UAC**；写入范围仅本文件。
- 不采信实现者自述：所有结论均来自我自己的命令原始输出、以及对源码的逐行读取；实现者声明的测试数字被独立复跑核对。

## 1. 结论总览

| # | 验收项 | 结论 |
|---|---|---|
| 1 | `kill_procs` 分类：Denied→AccessDenied；128/"not found"→继续；非零非 not-found 的可读中文错误串 | **通过** |
| 2 | `decode_console_output` 边界（空/ASCII/非法序列/截断多字节）不 panic | **通过** |
| 3 | `needs_elevation` 预检在任何 kill 之前；无「预检=true 却已 kill」路径 | **通过（预检本身零 kill）**；另记录一条窄竞态残余风险 R1 |
| 4 | `parse_helper_args` 全部非法输入 + 合法输入 + nonce 校验后无路径穿越 | **通过** |
| 5 | `ShellExecuteExW` 参数与 1223 取消/超时分支资源释放 | **基本通过**；发现缺陷 **F1（读结果失败路径句柄/文件未释放）**，另有 F2（等待码归并） |
| 6 | 前端两阶段：needsElevation 时不调 elevated；reject 文案；金黄 class 与 aria-label；提示不冲突 | **通过** |
| 7 | 回归面：原 8 个前端用例 + 原 5 个 process.rs 用例仍在且通过；服务端降权未被破坏 | **通过** |
| 8 | 需求外改动盘点；`pnpm check`/`cargo test` 无 warning | **通过** |

**总体结论：交付可接受（通过）。** 未发现阻断性缺陷；发现 1 个低危资源释放缺陷（F1）与 1 个低危措辞/归并问题（F2），以及 3 条只能在本环境之外确认的残余风险（R1–R3，其中 UAC 端到端不可验证）。

## 2. 测试复跑（独立核对实现者数字）

命令与关键原始输出：

```
$env:PATH="$env:USERPROFILE\.cargo\bin;$env:PATH"; cargo test --release
# -> test result: ok. 107 passed; 0 failed; 0 ignored  （lib 单测）
# -> tests\coverage.rs: test result: ok. 2 passed; 0 failed
# -> 另两个 test 目标 0 passed；doc-tests 0 passed
# -> exit 0；rustc 无 warning（输出里只有 git CRLF 提示）

pnpm test
# -> Test Files 10 passed (10)；Tests 129 passed (129)；src/lib/components/status.test.ts = 14 tests

pnpm check
# -> svelte-check found 0 errors and 0 warnings
```

- 实现者声称 `cargo test --release` = lib 107 + coverage 2、`pnpm test` = 129 tests/10 files、`pnpm check` = 0/0：**全部与我的独立复跑一致**。
- 新测试确实存在且通过（`elevate`）：`parse_helper_args_accepts_valid_request` / `returns_none_without_flag` / `rejects_bad_target` / `rejects_missing_nonce` / `rejects_non_hex_nonce`、`result_path_is_under_temp_and_contains_nonce`、`generate_nonce_is_filename_safe_and_hex`、`nonce_for_result_sanitizes_unsafe_input`；`process` 新增 `decode_console_output_decodes_cp936_denied` / `decode_console_output_passes_ascii_through` / `classify_taskkill_branches` / `process_is_elevated_returns_a_verdict_for_self` / `needs_elevation_does_not_panic`。

## 3. 逐条验收

### 验收项 1 — kill_procs 分类：通过

在真实机器上抓取 `taskkill` 原始字节（未针对 CapsWriter 进程；`PID 4` 为 System 受保护进程，无法被结束，安全）：

```
taskkill /F /PID 4
# exit code 1，raw bytes:
# "ERROR: The process with PID 4 could not be terminated.\r\nReason: Access is denied.\r\n\r\n"

taskkill /IM definitely_not_a_process_xyz.exe /F
# exit code 128，raw bytes: "ERROR: The process \"...xyz.exe\" not found.\r\n"
```

- 本机 `taskkill` 输出实际是**英文 ASCII**（尽管 ACP=936），所以真正命中的是 `classify_taskkill` 的 `"access is denied" → Denied`、`128 / "not found" → NotFound` 两个分支。
- 代码核对：`classify_taskkill`（`edit_config_gui/src-tauri/src/process.rs:456`）先判 NotFound（`exit==128` 或文本含 `没有找到/找不到/not found`），再判 Denied（`拒绝访问` 或 `access is denied`/`access denied`），否则 `Failed`；`kill_procs`（`process.rs:534`）在 `taskkill` 成功时 `continue`、NotFound 时 `continue`，Denied 时返回 `ProcError::AccessDenied(text.trim())`，Failed 时返回可读的 `Kill(...)`。
- 因此「Denied 返回 AccessDenied 而非普通失败」「128/not found 继续」「非零非 not-found 为可读中文」三条均成立。
- 运行时佐证见验收项 4 的 H 用例：三个 SERVER 进程名全部 `not found`（exit 128），被正确当作 NotFound 跳过，错误文本最终只与 CreateProcess 有关，证明分类真的在跑。
- 可读性佐证：`decode_console_output` 对 GBK 拒绝访问字节解码为「拒绝访问」而非乱码（验收项 2）。

### 验收项 2 — decode_console_output 边界：通过

以 P/Invoke 直接验证 Windows 语义（`Add-Type` C#，FullLanguage），并用真实 release 产物跑探针（见验收项 4）：

```
GetACP() = 936
```

- 正确常量核对：`MB_ERR_INVALID_CHARS = 0x08`。（自我纠错记录：我第一次误用 `0x80`，那其实是 `WC_ERR_INVALID_CHARS`，会让严格转换一律返回 0；源码用的是 0x08，正确。）
- 936 逐例行为：纯 ASCII 严格转换成功；GBK「拒绝访问」严格转换成功；孤立 `0x80` 在 cp936 映射为 `€` 不算非法；截断的 GBK 首字节 `B7` 严格转换返回 0 → 落到非严格分支（替换字符）；截断尾序列 `BE DC BE F8 B7` 严格失败 → 非严格得到「拒绝?」；`00 41` → 「 A」不丢 NUL。
- 探针实测（真实编译产物）：空切片 → `""`；ASCII 原样透传；cp936 拒绝访问 → `拒绝访问`；含非法序列 → 不 panic；被截断多字节 → 不 panic。
- 代码路径：`decode_console_output`（`process.rs:483`）空输入走 `String::from_utf8_lossy`（永不 panic）；否则取 `GetACP()`，按 `strict in [true,false]` 依次调用 `multi_byte_to_wide`（`process.rs:499`）→ `String::from_utf16`，最终兜底 `from_utf8_lossy`。严格失败必然回落，`from_utf16` 返回 `Result`，无 panic 路径。

### 验收项 3 — needs_elevation 预检在 kill 之前：通过（附窄竞态残余 R1）

三处调用链逐一读取：

- `commands::restart_service`（`edit_config_gui/src-tauri/src/commands.rs:444`）在取到 `base_dir` 后、于 `commands.rs:454` 先 `process::needs_elevation(target)`，为真则**直接**返回 `needs_elevation=true`，不调用 restart、不 kill。
- `process::restart`（`process.rs:332`）内部同样先 `needs_elevation()`，为真即返回，否则转 `restart_with_policy(..., DowngradeWhenAdmin)`。
- `kill_procs` 只在 `restart_with_policy`（`process.rs:352`）里、且在该预检之后被调用。
- 探针实测本会话（非管理员、无进程）：`needs_elevation(Server)=false`、`needs_elevation(Client)=false`，`is_admin=false`；无 panic。

**结论：预检路径本身零 kill 成立。** 但存在一条设计内（且已在 `commands.rs:440-442` 注释声明）的窄竞态：`kill_procs` 按名字顺序逐个 `taskkill`，若前面的进程结束成功、后面的某个返回 Denied，则 `commands.rs:464-467` 把这个 `AccessDenied` 映射为 `needsElevation=true` —— 此时**已经 kill 了一部分进程**。触发条件是「预检扫描时目标提权不可探测（token 查询失败且 variant 非 admin 变体），而 kill 时进程实为提权」的窗口期。属残余风险 R1，见第 5 节。

### 验收项 4 — parse_helper_args 非法/合法输入与路径穿越：通过

用**真实 release 产物**（`Start-Process -Wait`，工作目录设为隔离空目录 `%TEMP%\ecg_verify_empty_cwd`，无 launcher 可达、无 CapsWriter 进程）跑助手模式，安全（不 kill 任何进程、不拉起任何东西、不触发 UAC）：

| 用例 | 参数 | 退出码 | 结果文件内容 |
|---|---|---|---|
| A | `--elevated-restart=bogus --nonce=zz` | 2 | `err:--elevated-restart 的目标非法（只允许 server 或 client）：bogus` |
| B | `--elevated-restart=client --nonce=../../x` | 2 | `edit_config_gui_elevated_x.txt` = `err:--nonce 非法（必须匹配 ^[0-9a-fA-F]{1,64}$）：../../x`（**无穿越**，被净化为 `x`） |
| C | `--elevated-restart=client`（无 nonce） | 2 | `edit_config_gui_elevated_invalid.txt` = `err:提权助手缺少 --nonce 参数` |
| D | 65 字符 nonce | 2 | 文件名取前 64 字符，`err:nonce 非法` |
| E | `--elevated-restart=../server --nonce=abc` | 2 | target 非法 |
| F | 重复标志：先 `client` 再 `bogus` | 2 | 值非法即中止（`目标非法...bogus`） |
| G | `--nonce=`（空值） | 2 | `err:nonce 非法` |
| H | `--elevated-restart=server --nonce=deadbeef` | 1 | `edit_config_gui_elevated_deadbeef.txt` = `err:启动进程失败：CreateProcessW 失败（错误码 2：系统找不到指定的文件。 (os error 2)）` |

- 用例 H 是关键正例：证明合法请求真的走完了 `kill_procs`（对三个 SERVER 进程名各跑一次 `taskkill`，全部 exit 128 → 正确判 NotFound 跳过）后才在拉起 launcher 处失败；本机无 launcher 可达，故未结束/未拉起任何东西，结果文件写入了带校验 nonce 的 `%TEMP%` 文件。
- 探针（真实编译产物，直接调用库函数）补充：`parse_helper_args` 对 nonce 路径穿越、反斜杠、盘符、非 ASCII、路径型 target、缺 nonce、65 字符 nonce 全部返回 `Err`；合法输入返回 `Ok(Some)`；只给 nonce 不给 target 返回 `Ok(None)`（等价于正常 GUI 启动）；重复合法标志后者胜出；恰好多余的无关参数被忽略；`result_path(\"ab\")` 位于 `%TEMP%` 下。
- 路径穿越防线已核到代码：`result_path`（`elevate.rs:40-42`）= `std::env::temp_dir().join(format!(\"edit_config_gui_elevated_{nonce}.txt\"))`，nonce 只有在 `nonce_is_valid`（`elevate.rs:88-90`，非空、长度 ≤64、全部 `is_ascii_hexdigit`）通过后才用于拼路径；错误路径用 `nonce_for_result`（`elevate.rs:94-109`）把字符过滤为 `is_ascii_alphanumeric`、`take(64)`、兜底 `invalid`，因此**未校验值不可能拼出穿越路径**。
- 收尾检查：所有临时结果文件已清理，遗留 = 无；隔离 cwd 保持为空。

### 验收项 5 — ShellExecuteExW 参数与资源释放：基本通过，发现 F1、F2

代码核对（`elevate.rs:173-258`）：

- `cbSize = size_of::<SHELLEXECUTEINFOW>()`、`fMask = SEE_MASK_NOCLOSEPROCESS`（用于取 `hProcess`）、`lpVerb = \"runas\"`、`nShow = SW_HIDE`；`exe`/`parameters`/`lpDirectory` 都是本地 `Vec<u16>`，由 `wide`（`elevate.rs:261`）与 `wide_os`（`elevate.rs:266`）追加 NUL 终止符，且声明在调用之前、生命周期完整覆盖 `ShellExecuteExW`（**NUL 结尾与生命周期均满足**）。
- `lpParameters` = `--elevated-restart=<server|client> --nonce=<hex>`：两个值都是固定字面量或合法 hex，不含空格/引号，且 exe 走 `lpFile`、目录走 `lpDirectory`，不参与命令行解析，**无转义/注入问题**。
- `ShellExecuteExW` 返回 0：取 `GetLastError`，`ERROR_CANCELLED == 1223` → `Err(\"已取消管理员授权（UAC），未做任何改动\")`（与前端 reject 文案链路一致）；其它错误 → `Err(\"拉起提权助手失败（ShellExecuteExW 错误码 {code})\")`。此分支**尚未创建进程**，因此无需释放句柄 —— 该路径正确。
- 超时分支（`elevate.rs:227-235`）：`WaitForSingleObject(..., 120_000) != WAIT_OBJECT_0` 时 `TerminateProcess` + `CloseHandle` + 删除结果文件 + 返回「等待提权助手超时」——**句柄与文件都释放了**，符合验收要求。
- 成功分支：读结果文件（`.trim()`）→ 删除 → `CloseHandle`。

发现缺陷：

- **F1（低危，资源释放遗漏）**：`elevate.rs:237-240` 的「读取结果文件失败」错误路径（`read_to_string` 返回 `Err` 时）**直接返回错误，既没有 `CloseHandle(info.hProcess)`，也没有删除结果文件**。每次命中即泄漏一个进程句柄（GUI 长期存活期间累积）+ 遗留一个临时文件。正常单次运行不触发；可触发场景见残余风险 R2（over-the-shoulder UAC → 提权账号的 `%TEMP%` 与父进程不同 → 读失败）。**修复建议**：把 `CloseHandle` 与 `remove_file` 抽成该函数末尾的统一清理（或 guard），保证所有返回路径都执行；读失败时也先删除结果文件。
- **F2（低危，措辞/归并）**：`elevate.rs:227` 的 `wait != WAIT_OBJECT_0` 把 `WAIT_FAILED`/`WAIT_ABANDONED` 与 `WAIT_TIMEOUT` 归为一类，随后对可能无效的句柄调用 `TerminateProcess`，并向用户报「等待提权助手超时」——非超时场景下文案不准确。**修复建议**：区分 `WAIT_TIMEOUT` 与其它值，仅超时时 `TerminateProcess`，失败分支给独立文案。

补充（非缺陷的工程观察）：`restart_service_elevated` 是 `async fn` 但直接同步调用 `spawn_elevated_helper`（内部 `ShellExecuteExW` + `WaitForSingleObject` 阻塞）。其设计上先释放会话锁，阻塞的是 Tauri 异步执行器线程而非会话；UAC 等待发生在 `ShellExecuteExW` 内、**不受 120s 超时约束**（超时只覆盖助手自身工作），这点是正确设计。仅提示：极端情况下一个执行器线程被占用较久，但 Tauri 命令跑在线程池上，未见实际影响。

### 验收项 6 — 前端两阶段：通过

`edit_config_gui/src/bridge.ts`：`RunningInfo += clientAdmin: boolean`；导出 `type ServiceTarget = 'server' | 'client'`；`RestartOutcome { degraded: boolean; needsElevation: boolean }`；`restartService` → invoke `'restart_service'`；`restartServiceElevated` → invoke `'restart_service_elevated'`。

`edit_config_gui/src/lib/components/StatusBar.svelte`：

- `doRestart(target)`：先清 notice → `await bridge.restartService(target)`；若 `outcome?.needsElevation === true` 则置 `elevating=true` 并 **`return`**（对话框保持打开，**不调用** `restartServiceElevated`）；否则 degraded → `degradeNotice(target)`，`closeDialog()`，`refresh()`；异常 → `closeDialog()` + `notice = 重启失败：${...}`。
- `doRestartElevated(target)`：`await bridge.restartServiceElevated(target)` → degraded → `degradeNotice`，`closeDialog()`，`refresh()`；reject → 同样文案。
- `askRestart` 同时重置 `elevating=false`；`closeDialog` 同时清 `pending` 与 `elevating`。
- 确认框两阶段：`elevating ? 需要管理员权限重启{label} : 确认重启{label}？`；提权阶段提示「结束{label}需要管理员权限，下一步会弹出 UAC 确认；请在弹窗中允许后继续。」，按钮为「取消 / 以管理员权限重启」。
- 降权提示与新增提权预提示**不冲突/不叠加**：二者在不同对话框分支（预提示只在 `target==='client' && clientAdmin===true && !isAdmin` 且处于非提权阶段；`degradeNotice` 是关闭对话框后的通知），实测用例也未见同屏叠加。
- 金黄 class：客户端圆点 `class:admin={info?.client === true && info?.clientAdmin === true}`；CSS 中 `.dot.on`（约 206 行，绿 `var(--ecg-ok,#2f9e44)`）之后才声明 `.dot.admin`（约 210-213 行，金 `var(--ecg-warn,#b8860b)`）；两者同特异性、后声明者胜，故同时挂 `on`+`admin` 时显示**金色**。
- `aria-label` 精确值：`客户端以管理员权限运行` / `客户端运行中` / `客户端未运行`。

测试断言核对（`edit_config_gui/src/lib/components/status.test.ts`，mocks 用 `vi.hoisted` 含 `restartServiceElevated`）：原 8 个用例保留（5 个 StatusBar + 3 个 Onboarding），新增 6 个，共 14：金黄+aria-label；普通客户端无 admin class；`clientAdmin && !isAdmin` 确认框预提示文案；`needsElevation=true` 对话框不关且未调 `restartServiceElevated`；提权阶段点按钮才调 `restartServiceElevated('client')` 且对话框关闭；提权 reject 显示「重启失败：用户拒绝了 UAC」。

### 验收项 7 — 回归面：通过

- 原 8 个前端用例与新 6 个用例全部在 `pnpm test`（129/129）中通过；原 5 个 `process.rs` 用例 `name_match_rules` / `whitelist_accepts_exact_literal_names` / `whitelist_has_no_core_scripts` / `whitelist_rejects_path_like_names` / `detect_does_not_panic` 仍在且通过。
- 降权（DEGRADE）未被破坏：我对照了 **HEAD 旧版** `process.rs`，旧 `restart_launcher`（旧 `process.rs:206-224`）本来就对**所有** launcher 在管理员场景下走 `spawn_downgraded`（explorer 降权）——即客户端走 explorer 降权是**既有行为**，本次改动没有把降权缺陷「扩散」到客户端。
- 新增 `LaunchPolicy::InheritToken` 只被提权助手使用：`restart_with_policy` 中 `DowngradeWhenAdmin` 分支仍走 `restart_launcher`（管理员 → explorer 降权，失败回退 `spawn_normal` 并 `degraded=true`），`InheritToken` 分支直接 `resolve_launcher + spawn_normal`，**仅提权助手引用**。因此「客户端正常重启仍走 explorer 降权、服务端走降权」的既有语义保持不变。
- 探针实测：`detect()` 全 false、`is_admin=false`、`is_whitelisted(\"../x\")=false`（白名单/路径型拒绝未被破坏）。

### 验收项 8 — 需求外改动盘点与 warning：通过

`git diff --stat`：8 个改动文件共 **666 插入 / 66 删除**；新增未跟踪文件仅 `edit_config_gui/src-tauri/src/elevate.rs`。

- `Cargo.toml` +4 行：恰为两个 feature（`Win32_Globalization` 与实现者声明的偏差 (b) `Win32_System_Registry`）+ 2 行注释；`Cargo.lock` **未改动**（无新增依赖）。
- 偏差 (b) 独立复核为**必要且正确**：在 windows-sys 0.59 的源里，`ShellExecuteExW` 与 `SHELLEXECUTEINFOW` 都被 `#[cfg(feature = \"Win32_System_Registry\")]` 门控（`SHELLEXECUTEINFOW` 有 `hkeyClass: Registry::HKEY` 字段），所以不加该 feature 无法编译。
- 逐文件 diff 审阅：`commands.rs`（引入 `elevate`、`restart_service` 预检 + AccessDenied 映射、新增 `restart_service_elevated`）、`lib.rs`（`pub mod elevate` + 注册第 9 个命令）、`main.rs`（Tauri 之前调用 `run_if_requested`）、`bridge.ts`、`StatusBar.svelte`（上表所述两阶段）——**每一处 hunk 都属本次三项需求，无需求外行为改动**。
- 相关常量独立核对（windows-sys 0.59）：`MB_ERR_INVALID_CHARS=8`、`TOKEN_QUERY=8`、`TokenElevation=20`、`PROCESS_QUERY_LIMITED_INFORMATION=4096`、`SEE_MASK_NOCLOSEPROCESS=64`、`ERROR_CANCELLED=1223`、`SW_HIDE=0`，与源码用法一致。
- warning：`cargo test --release` 未见 rustc warning；`pnpm check` = 0 error 0 warning。**实现者声明的偏差 (a)(c) 亦复核成立**：(a) cp936 解码 `BE DC BE F8 B7 C3 CE CA` = 「拒绝访问」，而任务书给的 `E6 8B 92 E7 BB 9D E8 AE BF E9 97 AE` 实为 UTF-8 的「拒绝访问」，故任务书字节确实写错；(c) `needs_elevation` 预检确实在 `commands.rs:454` 与 `process.rs` 内各有一处。

## 4. 运行时可执行证据汇总

- 真实 release 产物：`edit_config_gui/src-tauri/target/release/edit_config_gui.exe` 存在；探针以 `rustc` 链接 `target/release/deps/libedit_config_gui_lib.rlib`（并 `-L native` 指向 windows_x86_64_msvc 0.52.6/0.53.1 的 lib）直接调用库函数，因此行为来自**实际交付产物**而非我重写的逻辑。
- 字节层独立核对（PowerShell `Encoding`）：`cp936(拒绝访问)` 与 `utf8(拒绝访问)` 双向解码/错配均复现原始乱码前提（GBK 字节按 UTF-8 解 = `�ܾ�����`；UTF-8 字节按 GBK 解 = `鎷掔粷璁块棶`）。
- 助手模式 8 个用例（A–H，见验收项 4）全部安全执行、无遗留文件。
- `process_is_elevated` API 序列实测（P/Invoke 走真实 pid）：自身 pid = `Some(false)`（中等完整性）、explorer = `Some(false)`；System(4)/winlogon/lsass/services/csrsm/dwm/Registry/smss 等受保护进程均返回 `null`（`OpenProcess` 失败）且**无崩溃/panic**。
  - **限制**：本会话无法获得一个「提权的非受保护进程」，因此「跨完整性级别的 token 查询返回 `Some(true)`」未被实测到。

## 5. 残余风险与未验证项

- **R1（窄竞态，设计内）**：`kill_procs` 逐名 kill 过程中，若后续名字返回 Denied，则 `commands.rs:464-467` 的映射会在**已 kill 部分进程**后置 `needsElevation=true`。触发窗口很窄（预检未探测到提权而 kill 时已提权）。预检本身零 kill，故非缺陷；建议在报告中保留该说明。
- **R2（未验证，UAC/提权上下文）**：over-the-shoulder UAC（用*另一个*管理员账号授权）时，提权助手的 `%TEMP%` 与父进程不同，父进程读不到结果文件 → 命中 **F1**（句柄泄漏 + 残留文件）并报「读取结果失败」，即使重启实际已成功。本会话非交互且非管理员，无法执行真实 UAC，**端到端未验证**。
- **R3（未验证 + 轻微设计观察）**：`restart_service_elevated`（`commands.rs:478-489`）不自行核对 `needsElevation`，任何前端调用都会弹 UAC；当前前端只在 `needsElevation=true` 后调用，故无实际影响。另外，助手模式绕过 GUI 的会话校验（`run_if_requested` 在 Tauri 之前），但能力被限制为「固定 server/client + 白名单 launcher」，与 GUI 已有能力等价，**不构成新的提权面**（它自身不提权，只是让调用者在自身权限下重启）。
- **未验证项（明确）**：真实 UAC 端到端（同意/取消两种路径在提权上下文中的行为）、跨完整性 `process_is_elevated == Some(true)`（**已由 §7 c) 更新为已验证**）、助手在真实提权上下文里对管理员客户端的结束行为。

### 人工验证步骤（需交互提权会话，本会话不可执行）

1. **准备**：以**非管理员**普通账号登录的交互桌面；先用「以管理员身份运行」启动 `start_client_gui_admin.exe`（或在管理器里用管理员方式拉起客户端），使管理器自己仍为普通权限。
2. **检测**：打开 `edit_config_gui`，确认状态栏客户端圆点为**金黄**且 `aria-label=\"客户端以管理员权限运行\"`（普通客户端应为绿色 + `客户端运行中`）。
3. **预检零 kill**：点「重启客户端」，弹确认框时应出现预提示「客户端以管理员权限运行，重启需要提权（会弹出 UAC 确认）」；点「确认重启」后**第一阶段的对话框保持打开**，标题变为「需要管理员权限重启客户端」，且提权助手尚未启动（任务管理器里不应出现新的 `edit_config_gui.exe`）。用 Process Monitor/Monitor 观察 `taskkill` 调用时，应看到**一次都没有**对 admin 客户端执行结束操作（预检为真即返回）。
4. **UAC 同意路径**：点「以管理员权限重启客户端」，在 UAC 弹窗选「是」；预期：管理员客户端被结束、按原 variant 重新拉起、对话框关闭；`%TEMP%\edit_config_gui_elevated_*.txt` 应在成功后**不存在**（已被删除）；事件日志/进程树确认提权助手 `edit_config_gui.exe --elevated-restart=client --nonce=<hex>` 短暂出现后退出。
5. **UAC 取消路径**：重复第 3 步后在 UAC 弹窗选「否」；预期：对话框关闭并显示「重启失败：已取消管理员授权（UAC），未做任何改动」（`elevate.rs:246` 的 ERROR_CANCELLED=1223 文案，前端统一加「重启失败：」前缀），**磁盘与进程零改动**（客户端仍在运行、无 result 残留文件）。
6. **跨完整性 token 查询（已由 §7 c) 独立验证，此项可选）**：在**非管理员**会话里对第 1 步的 admin 客户端 pid 手工调用 `process_is_elevated`（或直接看状态栏是否金黄），确认返回 `true` 而非 `None`。
7. **Over-the-shoulder（R2）**：在 UAC 弹窗中选择**另一个管理员账号**输入凭据，观察结果文件是否因 `%TEMP%` 不同而读失败（验证 F1 的触发条件与该路径的句柄/文件残留），并据此确认 F1 修复效果。

## 6. 结论与建议

- 三项需求的核心验收点均有**独立、可复现的运行时证据或逐行代码核对**支撑，测试数字与实现者声明一致，无需求外改动，无编译/类型 warning。
- 建议（不阻断合并）：修复 **F1**（统一清理 `hProcess` 与结果文件，覆盖读失败路径）；顺带处理 **F2**（区分 `WAIT_TIMEOUT` 与其它等待码）；在具备交互提权环境时补一次真实 UAC 端到端（同意 + 取消）与 R2（不同账号授权）验证。

## 7. 增量复核（F1/F2 修复后）

- 复核对象（冻结修订）：HEAD `7b63bd5` + 工作树；相对 task-3 声称只改了 `edit_config_gui/src-tauri/src/elevate.rs`（F1+F2）与 `edit_config_gui/src-tauri/src/process.rs`（纯测试）。复核者只读实现，仅追加本节。
- 冻结行号基准：`elevate.rs` 共 393 行；`process.rs` 共 954 行。

### a) 测试复跑与新测试语义

命令与关键原始输出：

```
# 1) 全量
$env:PATH="$env:USERPROFILE\.cargo\bin;$env:PATH"; cargo test --release   # src-tauri 下
# -> test result: ok. 109 passed; 0 failed; 0 ignored   （lib）
# -> tests\coverage.rs: test result: ok. 2 passed; 0 failed
# -> 其余目标 0 passed；exit 0

# 2) 只跑两条新测试
cargo test --release client_admin
# -> running 2 tests
# -> test process::tests::client_admin_falls_back_to_variant_only_when_token_query_failed ... ok
# -> test process::tests::client_admin_prefers_token_verdict_over_variant_name ... ok
# -> test result: ok. 2 passed; 0 failed; 107 filtered out

# 3) 全新目标目录强制重编译（检查 warning）
$env:CARGO_TARGET_DIR="$env:TEMP\ecg_verify_target_fresh"; cargo check --release --all-targets
# -> Finished `release` profile [optimized] target(s) in 1m 26s
# -> 日志 8086 字节；'warning|error\[|^error' 匹配行数 = 0
```

- lib **109 passed / 0 failed**（107 + 2）、coverage.rs **2 passed**、exit 0 —— 与 Lead 自报一致；两条新测试**确实在跑**且通过。
- `--all-targets` 在**全新 CARGO_TARGET_DIR** 下重编（日志含 `Compiling edit_config_gui`），warning/error 匹配行数 = 0，独立确认**无 rustc warning**（我此前的 `cargo test` 是增量缓存，本条以强制重编为准）。
- 代码核对 `client_admin_from`（`process.rs:217-225`）三分支：`client_elevated → true`；否则 `client_elevation_known → false`；否则 `client_variant == Some(CLIENT_ADMIN_EXE)`。测试断言与之一一对应：① `CLIENT_EXE + true + known → true`；② `CLIENT_ADMIN_EXE + false + known → false`（UAC 被关时名字是 admin、令牌实为中等完整性）；③ `CLIENT_EXE + false + known → false`；④ `CLIENT_ADMIN_EXE + false + unknown → true`（回退）；⑤ `CLIENT_EXE/None + false + unknown → false`。语义正确、无遗漏分支。
- **结论：通过。**

### b) `elevate.rs` 清理路径逐条审计

`spawn_elevated_helper`（`elevate.rs:205-294`）的**每一条** return / `?` 早退路径：

| # | 路径（行） | 句柄归属 | 结果文件归属 | 是否泄漏 |
|---|---|---|---|---|
| 1 | `current_exe()` 失败 `?`（L221） | 尚未创建句柄 | L219 已删同名残留、尚未产生新文件 | 否 |
| 2 | `ShellExecuteExW` 返回 0 → `return Err`（L243-250） | 未创建进程、无 `hProcess` | 无 | 否 |
| 3 | `info.hProcess.is_null()` → `return Err`（L252-254） | 无句柄可关 | 无 | 否 |
| 4 | `WAIT_OBJECT_0` → 继续（L261） | guard | guard | 否 |
| 5 | `WAIT_TIMEOUT` → `TerminateProcess` + `return Err`（L262-266） | guard `Drop` → `CloseHandle` | guard `Drop` → `remove_file` | 否 |
| 6 | 其它等待码 → `return Err`（L267-272，**未** TerminateProcess） | guard `Drop` | guard `Drop` | 否 |
| 7 | `read_to_string` 失败 `?`（L275-276，**正是 F1**） | guard `Drop` | guard `Drop` | 否 |
| 8 | 成功 / `degraded` / `err:` 分支（L280-293） | guard `Drop` | guard `Drop` | 否 |

- **guard 建立时点正确**：`let _guard = HelperGuard::new(info.hProcess, path.clone())` 在 `WaitForSingleObject` 之后（L258），且该行到函数末尾之间**没有任何早退**，因此第 4–8 条路径全部被覆盖；第 1–3 条早退发生在 guard 之前，但此时既无有效 `hProcess` 也未产生结果文件，无泄漏。
- **不会双重 `CloseHandle`**：全文件 `CloseHandle` 仅出现在 `Drop`（L195，grep 确认）；`HelperGuard::new` 仅被调用一次（L258）；`process: Option<HANDLE>` 在 `Drop` 里 `take()` 后置 `None`，只会关一次；且绑定是 `let _guard`（**不是** `let _`），保证活到作用域末尾而非立即析构。
- **`WAIT_TIMEOUT` 之外不再 `TerminateProcess`**：`TerminateProcess` 仅出现在 `WAIT_TIMEOUT` 分支（L264，grep 确认），`other` 分支只返回错误。
- 仍存在的唯一残留（已在代码注释 L176-177 声明）：over-the-shoulder UAC 时助手把结果写进**另一个管理员账号**的 `%TEMP%`，父进程既读不到也删不掉那份文件 —— 即残余风险 **R2 保持不变**（父进程侧句柄已由 guard 正确回收）。
- **结论：F1 修复通过、F2 修复通过。**

### c) 跨完整性 token 查询（更新 task-3 的未验证项）

只读枚举（P/Invoke，未 kill 任何进程、未触发 UAC）：

```
current user SID = S-1-5-21-515283951-224335582-3681225686-1001
=== Some(true) total = 18 ===   （全部 SameUser=True，OpenErr=0）
  PowerToys(10904), PowerToys.AlwaysOnTop(14784), PowerToys.Awake(14804),
  PowerToys.FancyZones(14832), PowerToys.QuickAccess(12740),
  sing-box(17796), snow_shot(2096), satelite-proxy(20972), TrafficMonitor(11376),
  iSCSIAgent(3296), PopBlock(1972), conhost(3596), rundll32(3400),
  taskhostw(15124), crashpad_handler(9572), XiaoYao_快速跳转(10844/15212/16108)
=== 反向样本（同用户、不同完整性）===
  PowerToys.PowerLauncher(14468) = Some(false)
  PowerToys.Peek.UI(14728)       = Some(false)
=== verdict tally ===   null 129 | Some(false) 104 | Some(true) 18
```

- 从本 **Medium 非管理员**会话，用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `OpenProcessToken(TOKEN_QUERY)` + `GetTokenInformation(TokenElevation)` 对**同用户提权进程**查询**成功返回 Some(true)**（18 个，`OpenProcess`/`OpenProcessToken` 错误码全 0）。
- 反向样本证明查询有区分度：同用户的 `PowerToys.PowerLauncher`/`Peek.UI` 返回 Some(false)，并非一律 true。
- Lead 列举的 `SystemInformer.exe` 本次**不在运行进程表中**，故未复核该名字；`PowerToys.exe`、`sing-box.exe`、`snow_shot.exe` 三个均已复核为 Some(true)，证据等价。
- **结论：task-3 第 5 节「跨完整性 `process_is_elevated == Some(true)` 未实测」一条更新为已验证。** 真实场景下 `process_is_elevated` 对同用户提权进程返回 `Some(true)`，因此状态栏金黄指示与 `needs_elevation` 预检可靠；`client_admin_from` 的 variant 回退只是 token 查询全失败时的兜底。
- **与 Lead 的实测一致**（唯一差异：SystemInformer 未运行，故该名字未复核，不构成异议）。

### d) 改动面审计

```
git status --short
 M Cargo.toml / commands.rs / lib.rs / main.rs / process.rs / bridge.ts / StatusBar.svelte / status.test.ts
 ?? edit_config_gui/src-tauri/src/elevate.rs
 ?? verification/
git diff --stat   # 8 files changed, 725 insertions(+), 66 deletions(-)
  process.rs 508 | Cargo.toml 4 | commands.rs 41 | lib.rs 4 | main.rs 6
  bridge.ts 42 | StatusBar.svelte 117 | status.test.ts 69
```

- 与 task-3 复核时的逐文件行数对比：**只有 `process.rs` 变了**（449 → 508，+59）；其余 7 个文件行数与 task-3 **完全一致**；`elevate.rs` 为未跟踪文件（内容已变）、`verification/` 是我的报告目录。**无其它实现文件被改动。**
- `process.rs` 的生产代码未变（函数定义行号逐一与 task-3 记录相同）：`is_admin 149`、`scan 169`、`client_admin_from 217`、`detect 231`、`needs_elevation 251`、`process_is_elevated 272`、`is_whitelisted 319`、`restart 332`、`restart_with_policy 352`、`restart_launcher 390`、`resolve_launcher 425`、`classify_taskkill 456`、`decode_console_output 483`、`multi_byte_to_wide 499`、`kill_procs 534`、`spawn_normal 571`、`spawn_downgraded 610`、`spawn_with_token 676`、`last_error 725`、`wide 733`、`command_line 742`；新增仅测试模块 `client_scan 870`、两个测试 `888` / `911`。**确认为纯测试追加。**
- **结论：通过，无需求外改动。**

### 增量结论

- a) lib 109 / coverage 2 / 0 failed / 0 warning，两条新测试真实运行且三分支语义正确 —— **通过**。
- b) F1 已修复：`HelperGuard` 覆盖全部 guard 之后的早退路径（含原漏网的 `read_to_string` 失败），guard 之前的三条路径本就无句柄/无文件；无双重 `CloseHandle`；非超时不再 `TerminateProcess` —— **通过**。
- c) 跨完整性 `Some(true)` 已被独立复现，task-3 的未验证项**更新为已验证**；与 Lead 一致。
- d) 仅 `elevate.rs` + `process.rs`（测试）变化，无需求外改动 —— **通过**。
- 仍待交互提权会话人工验证：真实 UAC 端到端（同意/取消）、提权上下文中的助手行为、R2（over-the-shoulder UAC 的跨账号 `%TEMP%` 残留，父进程侧无法清理）；R3 维持原判。

## 8. 需求变更复核：紫色 + 服务端提权检测

（章节标题采用 task-7 任务书原文；Lead 消息里写作「增量复核（紫色 + 服务端提权检测）」，指同一节。）

- **需求变更（用户 m00372 逐字）**：「不用金黄色了，改为检测服务端和客户端是否管理员权限运行，在左下的服务端和客户端运行状态指示予以区分，显示为紫色，」→ 相对 §7 冻结修订两处变更：① 提权指示颜色 金黄 `#b8860b` → **紫色**；② 提权检测从「仅客户端」扩展到「**服务端 + 客户端**」。本节只记录重新判定；前 7 节里「金黄」的旧描述已失效（§5 两处已由 Lead 更新为紫色/取消文案），本节不改前文。
- 冻结修订规模：`process.rs` **968 行**（`[System.IO.File]::ReadAllLines` = `Get-Content` = 968；Lead 已更正：先前「预期 508」是 `git diff --stat` 口径而非行数）、`StatusBar.svelte` 305 行、`bridge.ts` 216 行、`app.css` 164 行、`status.test.ts` 243 行。

### 结论表

| # | 验收项 | 结论 |
|---|---|---|
| 1 | 服务端圆点带 `class:admin`（`server===true && serverAdmin===true`）+ 三态 aria-label | 通过 |
| 2 | `.dot.admin` 定义在 `.dot.on` 之后（覆盖绿）、取 `var(--ecg-elevated, #8e44ad)` | 通过 |
| 3 | 确认框预提示按 target 泛化且含 `!info?.isAdmin`；客户端文案逐字未变 | 通过 |
| 4 | app.css 浅/深两套都定义 `--ecg-elevated`（`#8e44ad` / `#c084fc`） | 通过 |
| 5 | bridge.ts `RunningInfo.serverAdmin` 与 Rust 字段同源 | 通过 |
| 6 | Rust `server_admin` + `detect` 取值 + `needs_elevation` Server 分支同源同值、无猜测回退 | 通过 |
| 7 | `pnpm test` 10 files / 133 tests；`status.test.ts` 18；`pnpm check` 0 errors 0 warnings | 通过 |
| 8 | `cargo test --release` lib 109 + coverage 2、0 failed；全新 target 强制重编 0 warning | 通过 |
| 9 | src 下无「金黄」残留、`--ecg-warn` 未用于 admin 圆点 | 通过 |
| 10 | 改动面与清单一致、无需求外**源码**改动 | 通过（另见 3 个清单外非源码文件） |
| 11 | 真实提权服务端进程上的 `server_admin` 取值、真实 UAC 端到端 | **无法验证** |

### 逐条证据

**1) 服务端圆点**（`StatusBar.svelte:118-127`）

```
118: <span
119:   class="dot"
120:   class:on={info?.server === true}
121:   class:admin={info?.server === true && info?.serverAdmin === true}
122-126: aria-label 三态 = '服务端以管理员权限运行' / '服务端运行中' / '服务端未运行'
127: ></span>
```

客户端圆点（`:129-138`）保持原条件与三态文案。测试断言（`status.test.ts:121-129`）用 `findByLabelText('服务端以管理员权限运行')` + `classList.contains('admin') === true` + `queryByLabelText('服务端运行中') === null`。

**2) CSS 覆盖顺序**（`StatusBar.svelte:215-222`）

```
215: .dot.on { background: var(--ecg-ok, #2f9e44); }
219: /* 服务端/客户端以管理员权限运行时用紫色，与普通权限的绿色区分开 */
220: .dot.admin { background: var(--ecg-elevated, #8e44ad); }
```

`.dot.admin` 在 `.dot.on` 之后、同特异性 → 后声明覆盖绿色（与旧金黄实现同一机制，仅换令牌）。

**3) 确认框预提示**（`StatusBar.svelte:181-183`）

```
181: {#if !info?.isAdmin && (target === 'server' ? info?.serverAdmin : info?.clientAdmin) === true}
182:   <p class="hint">{targetLabel(target)}以管理员权限运行，重启需要提权（会弹出 UAC 确认）</p>
```

`targetLabel('client') = '客户端'`，故客户端文案 = 「客户端以管理员权限运行，重启需要提权（会弹出 UAC 确认）」——与变更前逐字相同（旧测试 `:144` 与新测试同串）。服务端得到同构文案（`status.test.ts:147-154` 精确断言）。

**4) app.css 双色**：`:24-25` 注释「紫色：服务端/客户端以管理员权限运行（深色单独调过）」+ `--ecg-elevated: #8e44ad;`；`:66-67` 深色 `@media` 内同注释 + `--ecg-elevated: #c084fc;`。两套都定义，不是只在浅色。

**5) bridge.ts**：`RunningInfo.serverAdmin: boolean`（`:101-108`；`clientAdmin` 文档 `:96-99` 未动）。Rust 侧 `#[serde(rename_all = "camelCase")]`（`process.rs:72`）把 `server_admin` 序列化为 `serverAdmin`，与 bridge 同名同源。

**6) Rust 取值链**（`process.rs`）

- `ScanResult.server_elevated`（`:167`）。
- `scan()` `:193-197`：命中 `SERVER_PROCS` 任一 → `server = true`；`process_is_elevated(pid) == Some(true)` → `server_elevated = true`（只有 `Some(true)` 计入，`None`/`Some(false)` 不计）。
- `detect()` `:247`：`server_admin: scan.server_elevated`。
- `needs_elevation` Server 分支 `:265-270` 返回同一 `scan.server_elevated`，注释 `:266-267` 点明「与 `RunningInfo::server_admin` 同源同值（都取自这一遍扫描的 `server_elevated`）」。
- **无猜测回退**：server 分支没有 variant 字面量兜底，token 全失败即 `false`（`:268-269` 注释）。
- 不变量测试 `:788-791`：`if !info.server { assert!(!info.server_admin); }`，并把 `server_admin` 加进字段触碰元组 `:792-799`。
- 只有 `process.rs` 一个 Rust 文件变化（见 10）；`client_admin_from` 文档 `:222` 补了指向 `RunningInfo::server_admin` 的交叉引用，测试注释 `:899`「金黄」→「状态栏紫色」。

**7) 前端实跑**

```
pnpm test  -> Test Files  10 passed (10); Tests  133 passed (133)
              src/lib/components/status.test.ts (18 tests)  ← 原 14 + 新 4，无回归
pnpm check -> svelte-check found 0 errors and 0 warnings
```

`status.test.ts`：fixture `running()` `:36` 补 `serverAdmin: false`；两个客户端用例标题 `:104`/`:112` 已改「紫色」；新增 4 个服务端用例：`:121-129`（提权→admin class + aria「服务端以管理员权限运行」且「服务端运行中」不存在）、`:131-136`（普通服务端无 admin class）、`:147-154`（`serverAdmin=true && isAdmin=false` → 确认框出现「服务端以管理员权限运行，重启需要提权（会弹出 UAC 确认）」）、`:156-167`（`serverAdmin=false` 而 `clientAdmin=true` → 服务端圆点无 admin class、服务端无提权提示）。

**8) Rust 实跑与行数**

```
cargo test --release -> lib 109 passed / 0 failed / 0 ignored; tests\coverage.rs 2 passed; 其余 0; exit 0
# 0 warning 以全新 CARGO_TARGET_DIR 强制重编确证：
CARGO_TARGET_DIR=%TEMP%\ecg_verify_target_t7 cargo check --release --all-targets
  -> Finished `release` profile [optimized] target(s) in 1m 24s
  -> 日志 8086 字节；'warning|error\[|^error' 匹配行数 = 0
process.rs 行数：ReadAllLines = 968（Get-Content 计数亦 968）
```

**9) 残留 grep**：`edit_config_gui/src` 全目录 grep `金黄|ecg-warn|ecg-elevated|dot\.admin|dot\.on` → **无任何「金黄」**；`--ecg-warn` 仍在 `app.css:23/:65` 定义并被 `Sidebar.svelte:180`、`DiffDialog.svelte:238-239`、`DynamicTableWidget.svelte:163/185`、`StatusBar.svelte:242`（`.notice`）与 `:291`（`.hint`）使用——**均非 admin 圆点**；admin 圆点唯一取色点是 `StatusBar.svelte:221` 的 `--ecg-elevated`。

**10) 改动面**（`git status --short` / `git diff --stat`）

- 清单内源码 5 个，均有增量：`process.rs`（diff 统计 508→522）、`bridge.ts`（42→50）、`StatusBar.svelte`（117→128）、`status.test.ts`（69→109）、`app.css`（0→4）。
- 未再改动的既有文件（diff 行数与 §7 记录一致，证明 Rust 侧只有 process.rs 变化）：`Cargo.toml` 4、`commands.rs` 41、`lib.rs` 4、`main.rs` 6。
- **清单外 3 个非源码文件**：`edit_config_gui/README.md`（+13，文档：紫色指示、紫转绿语义、UAC 取消文案、目录清单）；`docs/superpowers/sdd/2026-10-18-edit-config-gui-tauri/progress.md`（+64，SDD 进度记录，含「金黄→紫色、检测扩展到服务端」的变更说明）；仓库根 `edit_config_gui.exe`（Bin 10662912 → 10470400 bytes，mtime 2026-10-19 07:09:39，构建产物）。三者均为文档/构建产物，**非源码行为改动**；exe 是否是 Lead 统一构建的产物请 Lead 确认（产物级证据按计划归 task-8）。
- **无其它源文件改动。**

**11) 语义边界（任务第 4 题）**

- `server_admin == true` 仅表示「一遍扫描中存在**以提权令牌运行**的、命中 `SERVER_PROCS` 的服务端进程」，与 `is_admin`（管理器自身）无关。
- 提权重启后的形态由助手策略决定（`elevate.rs:134-135`）：`ServiceTarget::Server → LaunchPolicy::DowngradeWhenAdmin`、`ServiceTarget::Client → LaunchPolicy::InheritToken`。故服务端被提权助手结束后按既有降权约定拉起 → 回到普通权限 → 指示**由紫转绿**；客户端继承提权令牌 → 保持提权形态 → **仍紫色**。与 README 新增说明、代码实际行为一致。
- `detect().server_admin` 与 `needs_elevation(Server)` 各自调用一次 `scan()`，但都取该次扫描的 `server_elevated`；两次扫描之间进程状态变化时可能出现短暂不一致（既有设计，非本次引入）。补充：`needs_elevation` 在 `is_admin()` 为真时恒 `false`（`:259-261`），而 `server_admin` 仍如实反映服务端令牌——此时紫色圆点显示服务端提权但不要求提权，属正确行为（管理员本来就能结束它）。

### 无法验证项（照旧）

- **真实提权服务端进程上的 `server_admin` 取值**：本机没有 CapsWriter 服务端在运行，且硬约束禁止运行会真实拉起 CapsWriter 进程或触发 UAC 的命令，无法制造「以管理员权限运行的 server 进程」来观察 `Some(true)`。判定链已由 §7 c) 的 P/Invoke 证据间接支撑：`process_is_elevated` 对同用户提权进程返回 `Some(true)`，而 `scan()` 对命中 `SERVER_PROCS` 的进程调用的正是同一函数。
- **真实 UAC 端到端（同意/取消）**：本会话非交互且非管理员，无法执行；人工步骤见 §5 末。

### §8 结论

1)–10) 全部**通过**，11) **无法验证**；无契约偏差；本次仅向报告追加本节，未改任何实现文件。

## 9. 产物级复核（Lead，task-8）

> 本节由 Lead 写（非 verifier）；§8 之后全部源码冻结，Lead 统一重建产物并复核。

1. **构建**：`pnpm build:dist` 退出码 0。`vite build` 434ms 产出 `dist/assets/index-CayQwl-Z.css`（24,003 B）与 `index-DEFXsB9n.js`（147,851 B）（07:28:22）；`cargo build --release` 40.95s；`scripts/copy-dist.mjs` 复制到仓库根（日志「已复制到仓库根：edit_config_gui.exe（10.0 MB）」）。
2. **新前端确实进了 dist**：`dist/assets/index-CayQwl-Z.css` grep → `.dot.admin` 1 处、`--ecg-elevated` 3 处、`#8e44ad` 2 处、`#c084fc` 1 处；构建后的 CSS 中 `.dot.on` @18467 **先于** `.dot.admin` @18523（同特异性、后声明覆盖绿），片段 `.dot.admin.svelte-1piydef{background:var(--ecg-elevated,#8e44ad)}`。`index-DEFXsB9n.js` grep → `serverAdmin` / `clientAdmin` / `restart_service_elevated` / `以管理员权限重启` / `服务端以管理员权限运行` 各 1 处。
3. **exe 内嵌的是本次构建的 dist**：仓库根 exe 的 Latin-1 字节扫描命中本次 vite 产出的**哈希资源名** `index-DEFXsB9n.js`（@7395056）与 `index-CayQwl-Z.css`（@7439755）——旧（金黄）构建的哈希文件名不同，故可证内嵌的确实是紫色版前端；同时命中 Rust 侧串 `serverAdmin`（@7599207）、`restart_service_elevated`（@7656708）。
4. **两个产物逐字节同一**：仓库根 `edit_config_gui.exe` 与 `src-tauri/target/release/edit_config_gui.exe` 均 10,470,400 B、mtime 07:29:04，SHA256 同为 `3612E8534A8C2AAD651155056739E0A873DC3F00B7D980E5D3432DCD01ADFA27`。时间戳链：`process.rs` 07:22:10 → `dist` 07:28:22 → `exe` 07:29:04。
5. **新 exe 的助手参数校验冒烟**（不触发 UAC、不 kill 任何进程）：`edit_config_gui.exe --elevated-restart=bogus --nonce=zz` → 退出码 **2**，结果文件单行 `err:--elevated-restart 的目标非法（只允许 server 或 client）：bogus`（中文正确、无路径穿越），读取后删除；`%TEMP%` 无 `edit_config_gui_elevated_*.txt` 残留。
6. **新 exe 的 GUI 启动冒烟**：启动 5 秒后仍存活、窗口标题「**配置编辑器**」；结束后无 `edit_config_gui` 进程与 WebView2 孤儿残留。
7. 方法说明：前端串（`dot.admin`/`--ecg-elevated`/`8e44ad`）在 exe 内**不可直接 grep**（Tauri 对前端资源做了压缩，直接扫描均为 `-1`），故前端内嵌证据用第 3 条的「exe 含本次 dist 的哈希文件名」证明；第 2 条的 dist 级 grep 提供内容证据。
