# 配置编辑器重构设计（Tauri 2 + Svelte 5）

**日期：** 2026-10-18
**状态：** 待评审
**目标读者：** 本仓库的实现者与评审者

---

## 1. 背景与动机

现有配置编辑器 `edit_config_gui.py` + `util/edit_config_gui/` 基于 PySide6 + siui（PySide6-SiliconUI），共 15 个 Python 文件（入口 1 个 111 行 + 包内 14 个 6017 行 = 6128 行；合计 286 100 字节 ≈ 279 KB），其中 `client_config_page.py` 单文件就占 122 884 字节 / 2436 行。它存在四类实测问题。

### 1.1 覆盖不全

`config.toml` 当前共有 **162 个叶子键**（`tomllib` 权威解析；见 §3.1）。旧 GUI 源码中对 `config[a][b] = ...` 形式的字面写入只覆盖 **121 个**，缺失 **41 个**。按性质拆解：

| 类别 | 数量 | 键 |
|---|---|---|
| 派生占位符键（写入无效，见 §1.3） | 9 | `funasr_args.encoder_onnx_path` / `ctc_onnx_path` / `decoder_gguf_path` / `tokens_path` / `hotwords_path`、`sensevoice_args.model` / `tokens`、`paraformer_args.paraformer` / `tokens` |
| 动态表键（`client.additional_special_apps` 的任意 `<exe>` 子表） | 2 | `client.additional_special_apps.vlc.exe.hotkey` / `.name` |
| **真正缺失、且应用确实会读取** | **30** | 见下 |

真正缺失的 30 个键，全部经 `util/config.py` 或调用方确认被应用读取：

```
client.adb_addr                              config.py:159, adb_control.py:342
client.disable_exe_list                      config.py:62,  shortcut_handler.py:94
client.disable_exe_list_on_focus             config.py:61,  shortcut_handler.py:81
client.enable_adb_control                    config.py:158, adb_control.py:329
client.enter_apps                            config.py:86,  type_result.py:70
client.offline_translate_port_gemma2b        config.py:57
client.openai.api_key                        config.py:168, ai_optimize_language_expression.py:110
client.openai.base_url                       config.py:169, ai_optimize_language_expression.py:121
client.openai.model                          config.py:170
client.zhipuai.api_key                       config.py:166, ai_optimize_language_expression.py:62
client.zhipuai.model                         config.py:167
client.opencc_converter                      config.py:154, recv_result.py:139
client.prompt_style.prompt_{official,sweetheart,social,poetry,english,academic,customer_service,creative_writing}          ×8
client.prompt_style.prompt_{...}_shortcut                                                                                      ×8
debug.logger_level                           config.py:18,  safe_logger.py:82
server.check_port_usage_before_start         config.py:27,  core_server.py:51
```

即：**8 套提示词正文与其 8 个快捷键、全部 API Key 与 AI 模型名、ADB 相关配置、两个 exe 名单、`enter_apps`，在现有 GUI 里根本无法修改**，用户只能手改 TOML。

### 1.2 保存无保护

现有保存路径（`write_toml.py`）：

```python
from tomlkit import dump
def write_toml(config, config_path):
    with open(config_path, "w", encoding="utf-8") as f:
        dump(config, f)
```

直接 `open(..., "w")` 截断写。问题：

- 无备份，无原子替换 —— 写入过程中断电/崩溃得到半截文件。
- 无并发检测 —— 外部改动会被静默覆盖。
- 无 diff 预览、无撤销 —— 保存即生效，改错只能手工改回。
- 校验是逐字段「失焦即改」：`validate_addr()`（`client_config_page.py:167-186`）一旦发现地址非法，就在 :177 **直接把输入框覆写成 `127.0.0.1`**，并在右侧消息栏通知「已修改为默认值」（:181），用户输入当场丢失。同类「校验失败即覆写」在 `client_config_page.py` 里还有多处（如 :51 的默认值 lambda）。
- 「恢复默认值」按钮（`SetDefaultButton`）共 **41 个实例**、**42 条 connect 语句**，但**只有 40 个按钮真的接上了处理器**：
  - `client_config_page.py` 的 `stop_music_path_set_default`（实例化于 :619，加入布局于 :628）**从未 `.clicked.connect(...)`** —— 是个点了没反应的死按钮；用户想恢复 `assets/stop.mp3` 只能自己手打。
  - `file_seg_duration_set_default` / `file_seg_overlap_set_default` 各被 connect **两次**（:68 与 :74、:71 与 :77），重复绑定。

  全部默认值**硬编码在 lambda 里**，与出厂模板 `configs/default config.toml` 存在 **5 处实值偏差**：

| 键 | GUI 重置值 | 模板值 | 旧 GUI 源码 |
|---|---|---|---|
| `client.threshold` | `0.3` | `0.5` | `client_config_page.py:109` |
| `client.QQMusic_global_pause_hotkey` | `""` | `ctrl + alt + f5` | `client_config_page.py:87-89` |
| `client.CloudMusic_global_pause_hotkey` | `""` | `ctrl + alt + f6` | `client_config_page.py:90-92` |
| `client.PotPlayer_global_pause_hotkey` | `""` | `ctrl + alt + f7` | `client_config_page.py:93-95` |
| `client.foobar2000_global_pause_hotkey` | `""` | `ctrl + alt + f8` | `client_config_page.py:96-98` |

  （已用 `tomllib` 比对确认：`config.toml` 与 `configs/default config.toml` 在这 5 个键上的值一致，均为后者所列模板值。）

  即点「恢复默认值」会**把 4 个暂停快捷键清空**（功能被静默关闭）并**把阈值改成非出厂值**。这是硬编码双份事实来源的必然后果；新实现改为 schema 从 `configs/default config.toml` 导出默认值，单一来源（见 §9.2）。

### 1.3 派生占位符键

`config.toml` 中有 9 个键的值是 `${...}` 占位符：

```toml
[funasr_args]
encoder_onnx_path = "${model_paths.funasr_encoder_adaptor_path}"
ctc_onnx_path = "${model_paths.funasr_ctc_path}"
decoder_gguf_path = "${model_paths.funasr_llm_path}"
tokens_path = "${model_paths.funasr_tokens_path}"
hotwords_path = "${model_paths.funasr_hotwords_path}"

[sensevoice_args]
model = "${model_paths.sensevoice_path}"
tokens = "${model_paths.sensevoice_tokens_path}"

[paraformer_args]
paraformer = "${model_paths.paraformer_path}"
tokens = "${model_paths.paraformer_tokens_path}"
```

**全仓库没有任何代码解析 `${...}`**（已 grep `\$\{`、`format_map`、`string.Template`、`substitute`，零命中）。`util/config.py:242-246, 262, 278` 实际读的是 `model_paths` 段的真实路径：

```python
class FunASRArgs:
    encoder_onnx_path: str = config["model_paths"]["funasr_encoder_adaptor_path"]
    ctc_onnx_path: str = config["model_paths"]["funasr_ctc_path"]
    ...
class SenseVoiceArgs:
    model: str = config["model_paths"]["sensevoice_path"]
    tokens: str = config["model_paths"]["sensevoice_tokens_path"]
class ParaformerArgs:
    paraformer: str = config["model_paths"]["paraformer_path"]
    tokens: str = config["model_paths"]["paraformer_tokens_path"]
```

结论：这 9 个键在 TOML 里是**装饰性占位**，改它们不产生任何效果。新编辑器必须把它们呈现为**只读**，并说明真实生效位置，否则用户会改了没反应、以为程序坏了。

### 1.4 交互逻辑问题

- 条件显隐靠散落的 `xxx_changed()` 方法内手动 `hide()` / `show()`（如 `use_offline_translate_function_changed`、`hold_mode_changed`、`play_start_music_changed`），新增字段易漏。
- 9 个 `SiPage` 各自重复实现了「读取、校验、保存、重置」四套样板代码。
- 校验失败只在控制台 `print` + 右侧消息栏提示，表单本身不变红。
- 没有全局搜索、没有脏态提示、没有未保存拦截。

### 1.5 目标

用 **Tauri 2 + Svelte 5** 重写，达成：

1. **全覆盖** —— 162 个键全部可见，可编辑键全部可编辑。
2. **注释与结构保留** —— `toml_edit` 就地改值，不重新序列化。
3. **更安全** —— 校验、diff 预览、原子写入、自动备份、并发检测。
4. **更方便** —— 搜索、脏态提示、快捷键录制、标签式列表编辑、条件显隐声明化。
5. **抛弃 PySide6 + siui** —— 新实现零 Python GUI 依赖。

---

## 2. 范围

### 2.1 范围内

- 新建 `edit_config_gui/` Tauri 2 项目（Rust + Svelte 5 前端）。
- 覆盖 `config.toml` 全部 162 个叶子键。
- 删除旧的 `edit_config_gui.py` 与 `util/edit_config_gui/`（15 个文件）。
- 保留 `config.toml` 的注释、键顺序、`[section]` 结构与值类型。
- 生成单文件可执行程序（`edit_config_gui.exe`）。
- 服务端/客户端进程运行状态检测与「需重启生效」提示。

### 2.2 范围外

- 不修改 `config.toml` 本身的内容与注释文本。
- 不修改 `util/config.py`、`core_server.py`、`core_client.py` 等业务代码。
- 不修改 `config_selector.py` / `start_server_gui.py` / `start_client_gui.py`（它们也用 PySide6，但属于独立程序，本次不动）。
- 不做配置项的在线校验（如「端口是否被占用」）—— 只做格式与类型校验。
- 不引入远程配置、多用户、配置版本管理等新能力。

---

## 3. 配置键全量清单

### 3.1 权威统计

`tomllib` 解析当前 `config.toml`：

| 段 | 叶子键数 |
|---|---|
| `debug` | 1 |
| `server` | 15 |
| `client`（含 4 个子表） | 95 |
| `libretranslate` | 1 |
| `deeplx` | 3 |
| `model_paths` | 13 |
| `funasr_args` | 15 |
| `sensevoice_args` | 12 |
| `paraformer_args` | 7 |
| **总计** | **162** |

类型分布：`str` 85、`bool` 58、`int` 14、`list` 3、`float` 2。

`client` 段的 4 个子表：`zhipuai`(2)、`openai`(3)、`prompt_style`(16)、`additional_special_apps`(2 个叶子 = 1 个 `vlc.exe` 子表 × 2)。

`client` 下另有 2 个**非 ASCII 键**：`多音字`(bool)、`声调`(bool)。它们被 `util/config.py:94-95` 直接读取：

```python
多音字: bool = config["client"]["多音字"]
声调: bool = config["client"]["声调"]
```

新编辑器的路径表示法必须支持非 ASCII 与含点的键名（见 §5.2）。

### 3.2 三个配置模板的一致性

`configs/` 下有三个模板，经 `tomllib` 比对：

| 文件 | 叶子键数 | 与 `config.toml` 键集合一致 |
|---|---|---|
| `configs/default config.toml` | 162 | ✅ 完全一致 |
| `configs/debug config.toml` | 162 | ✅ 完全一致 |
| `configs/minimal config.toml` | 160 | ❌ 缺 `client.additional_special_apps` 整段 |

因此：**schema 的键集合断言要以 `configs/default config.toml` 为基准**（162 键），`minimal` 因缺少动态表不作为基准。动态表在 schema 中作为「可增删的键值对编辑区」处理，其内部键不作为固定 schema 项。

### 3.3 值类型陷阱

大量数值以**字符串**形式存储，不能擅自转成整数：

```toml
server.speech_recognition_port = "6016"     # str
client.speech_recognition_port = "6016"     # str
server.offline_translate_port = "6017"      # str
client.offline_translate_port = "6017"      # str
client.offline_translate_port_gemma2b = "11434"   # str
deeplx.online_translate_port = "1188"       # str
client.start_music_volume = "100"           # str
client.stop_music_volume = "50"             # str
```

而另一些是真整数：

```toml
client.audio_name_len = 20                  # int
client.mic_seg_duration = 60                # int
server.* 无 int
funasr_args.n_predict = 512                 # int
```

保存时必须按**原 TOML 值类型**写回，不按 schema 声明的语义类型转换（schema 的 `type` 用于选择和校验控件，写回以文档中原类型为准）。见 §7.3。

### 3.4 列表类型

3 个 `list` 键：

```toml
client.disable_exe_list = [""]                        # 单层字符串数组
client.disable_exe_list_on_focus = [""]               # 单层字符串数组
client.enter_apps = [["happ.exe", 0.5], ["hexin.exe", 0.5]]   # 二维：[[exe名, 延迟秒]]
```

`enter_apps` 的语义见 `util/client/type_result.py:68-77`：

```python
def _match_enter_app(process_name: str):
    for item in Config.enter_apps:
        app, delay = item[0], item[1]
        if app.lower() == process_name:
            return delay
    return None
```

即每项是 `[进程名, 自动回车延迟秒数]`。编辑器需要专门的二维编辑器，不能让用户手写 TOML 数组。

`disable_exe_list` / `disable_exe_list_on_focus` 的消费方分别是 `util/client/shortcut_handler.py:89-97`（`check_process`，进程在跑就禁用）与 `:81-86`（`check_focus`，进程是前台就禁用）。两者默认值都是 `[""]`——一个**占位用的空串**：`get_target_names("")` 得到 `[""]`，而 `proc_name` 永远不为空，所以它匹配不到任何进程，等于「空列表」。

新编辑器在读取时把**只含空串的数组规整为空列表**显示（用户看到的是「暂未添加」而不是一行空白），保存时若列表为空则写回 `[""]` 以保持与出厂模板一致的结构。这条规则同时避免了「用户看到一行空白但删不掉」的困惑。`enter_apps` 默认值不是空串占位，保持原样。

---

## 4. 架构

### 4.1 目录结构

```
edit_config_gui/
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts
├── svelte.config.js
├── tsconfig.json
├── index.html
├── src/
│   ├── main.ts
│   ├── App.svelte
│   ├── app.css
│   ├── bridge.ts                    # 唯一 invoke() 封装点
│   └── lib/
│       ├── schema/
│       │   ├── types.ts             # FieldMeta / SectionMeta / PageMeta
│       │   ├── server.ts            # debug + server
│       │   ├── client.ts            # client 主表（72 直接键）
│       │   ├── aiProviders.ts       # client.zhipuai + client.openai
│       │   ├── promptStyles.ts      # client.prompt_style（16 键）
│       │   ├── additionalApps.ts    # client.additional_special_apps 动态表
│       │   ├── translate.ts         # libretranslate + deeplx
│       │   ├── modelPaths.ts        # model_paths（13 键）
│       │   ├── modelArgs.ts         # funasr_args / sensevoice_args / paraformer_args
│       │   └── index.ts             # 汇总 + 按页分组
│       ├── components/
│       │   ├── Sidebar.svelte
│       │   ├── SearchBox.svelte
│       │   ├── Section.svelte
│       │   ├── Field.svelte         # 按 FieldMeta.widget 分发
│       │   ├── DirtyBar.svelte
│       │   ├── DiffDialog.svelte
│       │   └── widgets/
│       │       ├── TextWidget.svelte
│       │       ├── IntWidget.svelte
│       │       ├── FloatWidget.svelte
│       │       ├── BoolWidget.svelte
│       │       ├── EnumWidget.svelte
│       │       ├── PathWidget.svelte
│       │       ├── HotkeyWidget.svelte
│       │       ├── StringListWidget.svelte
│       │       ├── PairListWidget.svelte      # enter_apps 专用
│       │       ├── LongTextWidget.svelte
│       │       ├── SecretWidget.svelte        # API Key 掩码 + 显示切换
│       │       ├── ReadonlyWidget.svelte
│       │       └── DynamicTableWidget.svelte  # additional_special_apps
│       └── stores/
│           ├── config.ts            # original / current / dirty
│           └── toast.ts
└── src-tauri/
    ├── Cargo.toml
    ├── build.rs
    ├── tauri.conf.json
    ├── capabilities/default.json
    ├── icons/icon.ico
    └── src/
        ├── main.rs
        ├── lib.rs
        ├── config_doc.rs            # toml_edit 文档模型
        ├── patch.rs                 # 补丁应用 + diff
        ├── validate.rs              # 校验规则
        ├── hotkey.rs                # 快捷键解析
        ├── model_paths_resolve.rs   # 派生键只读解析
        ├── file_io.rs               # 备份 / 原子写 / 指纹
        ├── process.rs               # 进程检测
        └── commands.rs              # #[tauri::command] 定义
```

### 4.2 分层职责

| 层 | 位置 | 职责 | 禁止 |
|---|---|---|---|
| 元数据层 | `src/lib/schema/` | 162 个键的标题、说明、控件、校验、默认值、显隐条件 | 不做 IO，不做业务判断 |
| 呈现层 | `src/lib/components/` | 由元数据渲染表单，管理焦点/搜索/折叠 | 不直接读写文件 |
| 状态层 | `src/lib/stores/` | original / current / dirty 三份状态 | 不做校验（交给 Rust） |
| 桥接层 | `src/bridge.ts` | 7 个命令的类型化封装 | 不含业务逻辑 |
| 文档层 | `src-tauri/src/config_doc.rs` | 解析、读取、写入、保留格式 | 不做校验 |
| 校验层 | `src-tauri/src/validate.rs` + `hotkey.rs` | 与旧 `ValueCheck` 等价 | 不碰文件（除路径存在性检查） |
| 文件层 | `src-tauri/src/file_io.rs` | 备份、原子替换、指纹 | 不解析 TOML |

### 4.3 技术选型

| 需求 | 选型 | 理由 |
|---|---|---|
| 桌面壳 | Tauri 2 | 体积小、Rust 侧可做原子写与进程检测 |
| 前端框架 | Svelte 5（runes 语法） | 编译期响应式，无虚拟 DOM，产物小 |
| 构建 | Vite 7 + pnpm | 与 Svelte 5 官方模板一致 |
| TOML 编辑 | `toml_edit` 0.22 | **唯一能保留注释/顺序/格式的 Rust TOML 库** |
| 哈希 | `sha2` | 文件指纹 |
| 文件替换 | Windows `ReplaceFileW`（`windows-sys` 0.59，feature `Win32_Storage_FileSystem` + `Win32_Foundation`） | 原子替换 + 原子备份 + 保留 ACL；签名与行为已在本机实测 |
| 进程检测 | `sysinfo` | 跨平台进程列表 |
| 前端测试 | `vitest` | 与 Vite 同源 |
| Rust 测试 | `cargo test` | 内建 |

已实测：`rustc 1.99.1` / `cargo 1.99.1`（位于 `%USERPROFILE%\.cargo\bin`，需手动加 PATH）、`node v24.21.0`、`pnpm 12.11.2`。Tauri 2 已在本机成功编译（首次失败唯一原因是缺 `src-tauri/icons/icon.ico`，补一个合法 ICO 后 `cargo build` 通过）。`cargo-tauri` CLI 未安装，改用 `pnpm add -D @tauri-apps/cli` 走本地依赖，不污染全局。

---

## 5. 数据模型

### 5.1 前端字段元数据

`src/lib/schema/types.ts`：

```ts
export type ValueType =
  | 'string' | 'integer' | 'float' | 'boolean'
  | 'stringArray' | 'pairArray';

export type WidgetKind =
  | 'text' | 'int' | 'float' | 'bool' | 'enum' | 'path'
  | 'hotkey' | 'stringList' | 'pairList' | 'longText'
  | 'secret' | 'readonly' | 'dynamicTable';

export type ValidatorId =
  | 'ip' | 'localListenableIp' | 'port' | 'fileExist' | 'dirExist'
  | 'hotkey' | 'url' | 'singleLine' | 'ipPort' | 'regexClass';

export interface FieldMeta {
  /** 点分路径，段内可含非 ASCII；每一段存放在 segments 中避免歧义 */
  path: string;
  segments: string[];
  title: string;
  note?: string;                 // 来自 config.toml 的注释原文
  type: ValueType;
  widget: WidgetKind;
  default?: string | number | boolean | unknown[];
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  validators?: ValidatorId[];
  allowEmpty?: boolean;
  pathMode?: 'file' | 'directory';
  fileSuffix?: string;
  visibleWhen?: { path: string; equals?: unknown; in?: unknown[] };
  /** 只读派生：真实生效位置 */
  derivedFrom?: string;
}

export interface SectionMeta {
  id: string;
  title: string;
  note?: string;
  fields: FieldMeta[];
}

export interface PageMeta {
  id: string;
  title: string;
  /** 未保存修改计数角标由 store 提供 */
  sections: SectionMeta[];
}
```

### 5.2 路径表示法

`client.additional_special_apps.vlc.exe.hotkey` 中 `vlc.exe` 是**一个含点的表键**。为消除歧义，`FieldMeta` 同时携带 `segments: string[]`（如 `['client','additional_special_apps','vlc.exe','hotkey']`），Rust 侧一律用 `segments` 定位，`path` 仅用于展示与搜索。

`client.多音字`、`client.声调` 的 `segments` 为 `['client','多音字']`，Rust 的 `toml_edit` 键定位天然支持 UTF-8。

### 5.3 Rust 侧文档模型

```rust
// config_doc.rs
pub struct ConfigDoc {
    doc: toml_edit::DocumentMut,
}

impl ConfigDoc {
    pub fn parse(text: &str) -> Result<Self, TdError>;
    pub fn to_plain_json(&self) -> serde_json::Value;
    pub fn get(&self, segments: &[String]) -> Option<&toml_edit::Item>;
    /// 就地改值：按原有 Item 类型写回，保持注释与格式
    pub fn set_typed(&mut self, segments: &[String], value: &PatchValue) -> Result<(), TdError>;
    pub fn to_toml_string(&self) -> String;
}
```

`to_plain_json` 把文档转成纯 JSON（值 + 类型标签）供前端渲染：

```rust
// 每个叶子输出 { "value": <json>, "tomlType": "string"|"integer"|"float"|"boolean"|"array" }
pub fn to_plain_json(&self) -> serde_json::Value;
```

### 5.4 补丁结构

```rust
// patch.rs
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(tag = "kind", content = "value")]
pub enum PatchValue {
    Str(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    StrArray(Vec<String>),
    PairArray(Vec<(String, f64)>),
    /// 动态表中的一个条目：segments 指向该条目的键（如 ["client",
    /// "additional_special_apps", "vlc.exe"]），value 是它的字段映射。
    /// 只用于「新增或改单个条目」，**没有整表替换变体**（见 §9.5 的反例）。
    TableRow(std::collections::BTreeMap<String, String>),
    /// 删除一个键或一个动态表条目
    Delete,
}

pub struct Patch {
    pub segments: Vec<String>,
    pub value: PatchValue,
}

pub struct ApplyResult {
    pub diff: String,        // unified diff
    pub changed: Vec<Vec<String>>,
    pub new_text: String,    // 不落盘；仅供 diff 预览
}
```

> **为什么没有 `Table`（整表替换）变体**：实测 `Table::clear()` + 重建会丢掉每个条目的行尾注释（§7.4 结论 5、§9.5 反例）。因此动态表的增/改/删一律降级为「定位到单个条目」的 `TableRow` / `Delete` 补丁，由 Rust 侧逐项 `Table::insert` / `Table::remove`。前端只需对比出差异项并发补丁，不发送整张表。

**补丁顺序**：同一批 `Vec<Patch>` 内按前端给出的顺序依次应用。删除类补丁**在数组类补丁之后应用**（Rust 侧分两趟：先 `StrArray`/`PairArray`/`TableRow`，后 `Delete`），避免「先删后建」时索引错位。

### 5.5 状态模型

```ts
// stores/config.ts
interface ConfigState {
  original: Record<string, { value: unknown; tomlType: string }>;  // 打开时快照
  current: Record<string, unknown>;
  dirty: Set<string>;          // path 字符串集合
  fingerprint: FileFingerprint; // mtime + size + sha256
  filePath: string;
}
```

`dirty` 在每次 `current[k] = v` 后按 `deepEqual(current[k], original[k].value)` 重算。撤销单字段 = 恢复 `original[k]`。

---

## 6. 键覆盖设计

### 6.1 页面划分

页面与 `config.toml` 的段一一对应；`client` 段因含 4 个子表且直接键多达 72 个，拆为 **4 个页面**（主体 + AI 服务商 + 提示风格 + 附加特殊应用）。加上其余 8 个段页与「关于」页，共 **13 页**。

| 页 | 覆盖段/子表 | 键数 |
|---|---|---|
| 服务端 | `server` | 15 |
| 客户端 | `client` 主表（不含子表） | 72 |
| AI 服务商 | `client.zhipuai` + `client.openai` | 5 |
| 提示风格 | `client.prompt_style` | 16 |
| 附加特殊应用 | `client.additional_special_apps` | 动态 |
| LibreTranslate | `libretranslate` | 1 |
| DeepLX | `deeplx` | 3 |
| 模型路径 | `model_paths` | 13 |
| FunASR 参数 | `funasr_args` | 15 |
| SenseVoice 参数 | `sensevoice_args` | 12 |
| Paraformer 参数 | `paraformer_args` | 7 |
| 调试 | `debug` | 1 |
| 关于 | — | 静态 |

`client` 主表 72 直接键 + 子表 23 键（2+3+16+2）= 95，与服务端统计一致。

「关于」页内容：程序版本、`config.toml` 绝对路径、项目地址、旧 GUI 迁移说明（哪些键是新增可编辑的）。

### 6.2 新增页面的键

旧 GUI 缺失、新 GUI 必须提供的 30 个键，落位如下：

| 页 | 新增键 |
|---|---|
| 服务端 | `server.check_port_usage_before_start` |
| 客户端 | `client.enable_adb_control`、`client.adb_addr`、`client.disable_exe_list`、`client.disable_exe_list_on_focus`、`client.enter_apps`、`client.offline_translate_port_gemma2b`、`client.opencc_converter` |
| AI 服务商 | `client.openai.api_key`、`client.openai.base_url`、`client.openai.model`、`client.zhipuai.api_key`、`client.zhipuai.model` |
| 提示风格 | `client.prompt_style.*` 全部 16 键（8 正文 + 8 快捷键） |
| 调试 | `debug.logger_level` |

### 6.3 控件分配

| 键 | 控件 | 说明 |
|---|---|---|
| `debug.logger_level` | enum | `TRACE`/`DEBUG`/`INFO`/`SUCCESS`/`WARNING`/`ERROR`/`CRITICAL`，loguru 标准级别 |
| `server.model` | enum | `FunASR`/`Sensevoice`/`Paraformer`（旧 GUI `server_config_page.py` 顺序） |
| `server.addr` | text + `localListenableIp` | |
| `server.speech_recognition_port` | text + `port` | **写回字符串** |
| `server.offline_translate_port` | text + `port` | **写回字符串** |
| `client.addr` | text + `ip` | 允许远程 IP（旧 GUI 误用 `localListenableIp`，见 §9.2） |
| `client.speech_recognition_port` | text + `port` | **写回字符串** |
| `client.offline_translate_port` | text + `port` | **写回字符串** |
| `client.offline_translate_port_gemma2b` | text + `port` | **写回字符串** |
| `deeplx.online_translate_port` | text + `port` | **写回字符串** |
| `client.start_music_volume` / `stop_music_volume` | text + `int 0..100` | **写回字符串** |
| `client.threshold` | float, min 0.1, max 2.0, step 0.1 | 沿用旧 GUI 范围（`client_config_page.py:858-860`）；语义是秒（`send_audio.py:74`、`shortcut_handler.py:490`），不是 0..1 比例 |
| `client.check_microphone_usage_by` | enum | `注册表`/`按键` |
| `client.convert_to_traditional_chinese_main` | enum | `简`/`繁` |
| `client.opencc_converter` | text | opencc 转换器名，默认 `s2t` |
| `client.ai_provider` | enum | `openai`/`zhipuai` |
| `client.prompt_style_selection` | enum | 8 种风格（`official`/`sweetheart`/`social`/`poetry`/`english`/`academic`/`customer_service`/`creative_writing`），模板默认 `english`；遇未知值保留原文并加一条自定义选项（沿用旧 GUI 的兜底行为） |
| `client.online_translate_target_languages_libretranslate` | enum | `zh`/`en`/`ru`/`fr`/`ko`（+ 允许自由输入） |
| `client.online_translate_target_languages` | enum | `JA`/`EN`/`RU`/`FR`/`KO`（+ 允许自由输入） |
| `sensevoice_args.language` | enum | `auto`/`zh`/`en`/`ja`/`ko`/`yue` |
| `sensevoice_args.provider` | enum | `cpu`/`cuda`/`coreml` |
| `sensevoice_args.sample_rate` / `paraformer_args.sample_rate` | enum | `16000`/`44100`/`48000`，**写回 int** |
| `sensevoice_args.decoding_method` / `paraformer_args.decoding_method` | text | sherpa-onnx 解码方法名 |
| `client.adb_addr` | text + `ipPort` | 形如 `192.168.3.127:10101`，**不是纯 IP**，不能套 `ip` 校验器；`enable_adb_control=false` 时整组隐藏 |
| `client.trash_punc` | text + `regexClass` | 要丢弃的标点集合，模板值 `，。,.`（4 个字符，含全角逗号 U+FF0C 与句号 U+3002）；被 `util/client/strip_punc.py:22` 原样拼进字符类，见 §8.0.1 |
| `client.stop_music_volume` | text + `int 0..100` | **写回字符串**（同 `start_music_volume`） |
| `client.openai.api_key` / `client.zhipuai.api_key` | secret | 掩码显示 + 「显示」按钮；空 = 未配置 |
| `client.openai.model` / `client.zhipuai.model` | text | 模型名，自由填写（服务商改名频繁，不做枚举） |
| `sensevoice_args.rule_fsts` / `rule_fars` | text | sherpa-onnx 规则文件路径列表，**模板默认为空串**，`allowEmpty: true` |
| `client.disable_exe_list` / `disable_exe_list_on_focus` | stringList | 标签式增删 |
| `client.enter_apps` | pairList | `(进程名, 延迟秒)` 表格 |
| `client.additional_special_apps` | dynamicTable | `(exe, 快捷键, 名称)` 三列表 |
| `client.prompt_style.prompt_*` | longText | 8 个多行编辑器，可恢复默认 |
| `client.prompt_style.prompt_*_shortcut` | hotkey | 8 个录制控件 |
| `client.*_global_pause_hotkey`（4 个） | hotkey, `allowEmpty: true` | 留空 = 不暂停 |
| `client.speech_recognition_shortcut` / `offline_translate_shortcut` / `online_translate_shortcut` | hotkey, 不允许空 | |
| `client.vscode_exe_path` | path(file, `.exe`), `allowEmpty: true` | 空 = 不用该功能 |
| `client.start_music_path` / `stop_music_path` | path(file, `.mp3`) | |
| `deeplx.exe_path` | path(file, `.exe`) | |
| `libretranslate.api` / `deeplx.api` | text + `url` | |
| `client.openai.base_url` | text + `url`, `allowEmpty: true` | 空 = 用官方端点 |
| 其余 `model_paths.*` | path(file 或 directory) | 见 §6.4 |
| 9 个派生键 | readonly | 见 §6.5 |

**其余 14 个数值键的取值范围与步进**沿用旧 GUI 的实测设置，避免新编辑器给出旧版不接受的边界值：

| 键 | 控件 | min | max | step |
|---|---|---|---|---|
| `client.audio_name_len` | int | 10 | 200 | 1 |
| `client.mic_seg_duration` | int | 10 | 60 | 1 |
| `client.mic_seg_overlap` | int | 0 | 10 | 1 |
| `client.file_seg_duration` | int | 10 | 60 | 1 |
| `client.file_seg_overlap` | int | 1 | 60 | 1 |
| `client.start_music_volume` / `stop_music_volume` | int（**写回字符串**） | 0 | 100 | 1 |
| `funasr_args.n_predict` | int | 1 | 2048 | 1 |
| `funasr_args.n_threads` | int | 0 | 32 | 1（0 = 自动） |
| `funasr_args.similar_threshold` | float | 0.3 | 1.0 | 0.1 |
| `funasr_args.max_hotwords` | int | 1 | 100 | 1 |
| `sensevoice_args.num_threads` / `paraformer_args.num_threads` | int | 1 | 32 | 1 |
| `sensevoice_args.feature_dim` / `paraformer_args.feature_dim` | int | 1 | 1024 | 1 |
| `sensevoice_args.sample_rate` / `paraformer_args.sample_rate` | enum（**写回 int**） | — | — | — |

> 边界策略：`min`/`max` 只在控件层约束，**不作为校验器**。理由是这些数值键的消费端没有任何越界检查（如 `ws_recv.py:64` 直接 `seg_duration + seg_overlap * 2`），用户手工把 `config.toml` 改成超范围值再打开编辑器时，若用 min/max 当校验器会立刻报错并可能阻止保存一个**本来可用**的配置。新编辑器的做法是：值在范围内→正常；超范围→控件标黄提示「超出常规范围，仍将按原值保存」，但**不阻断保存**，只在用户主动调值时把范围约束施加到新值上。这与 `model_paths` 路径的「只警告不阻断」是同一策略（§9.3）。

#### 6.3.1 未逐一列举的 93 个键由派生规则覆盖

上表逐条点名了 69 个键。剩余 93 个**不逐个手写**，由三条派生规则生成，规则本身在 §10.2 的覆盖测试里被自动验证，因此不会漏：

| 规则 | 适用键 | 生成结果 |
|---|---|---|
| **R1：`bool` 类型 → `BoolWidget`（开关）** | 全部 **58 个 `bool` 键**，按段分布：`server` 11、`client` 38、`funasr_args` 6、`sensevoice_args` 2、`paraformer_args` 1。含 `client.多音字`/`client.声调` 两个非 ASCII 键、`client.save_audio`/`save_markdown`/`save_non_kwd_markdown` 与 `client.file_save_srt`/`file_save_txt`/`file_save_json`/`file_save_merge` 这 7 个保存开关、`funasr_args.vulkan_enable`/`flash_attn`/`enable_ctc`/`directml_enable`/`vulkan_force_fp32`/`verbose`、`sensevoice_args.debug`/`use_itn`、`paraformer_args.debug`、`client.enable_adb_control`/`restore_key`/`suppress`/`paste` 等 | 每键一个开关控件，标签与说明取自 schema 的 `title`/`description`（由 `config.toml` 注释生成） |
| **R2：`client.prompt_style.*` 的 16 键成对生成** | 8 个正文 `prompt_<style>` + 8 个 `prompt_<style>_shortcut` | 每种风格渲染为一个「正文 longText + 快捷键 hotkey」的成对卡片，共 8 张；风格名从 16 个键的公共前缀枚举得到，不硬编码 8 个名字 |
| **R3：`str` 且表内未点名 → `text` 控件** | 其余 **69 个 `str`**（`85 个 str − 16 个 prompt_style`）中，凡未被 §6.3 表格点名的（如 `client.trash_punc`、`sensevoice_args.rule_fsts` 等已点名的则以表内规则为准） | 单行文本框，附 `singleLine` 校验 |

`bool` 键的标题与注释**一律取自 `config.toml` 自身的注释块**（schema 生成时解析每个键上方的 `#` 行为 `description`），因此 58 个开关不需要人工编文案——这也是「结构保留」落到 UI 上的方式。

**闭合链条（已用 `tomllib` 实测校验，各桶互斥、求和恰好 162）：**

| 桶 | 规则 | 键数 |
|---|---|---|
| `bool`（R1） | 开关控件，枚举自实际类型 | **58** |
| `client.prompt_style.prompt_*`（R2） | 8 张「正文 + 快捷键」成对卡片 | **16** |
| 其余 `str`（R3） | 单行 `text`（个别在 §6.3 表内被点名成 enum/path/secret/hotkey 的，以表内规则优先） | **69** |
| `int` | 数字输入，范围见上表；无范围的走通用 min/max | **14** |
| `float` | 同上 | **2** |
| `list` | `stringList` × 2 + `pairList` × 1 | **3** |
| **合计** | | **162** ✅ |

注意「表内点名」与「派生规则」不是并列关系：§6.3 表逐字点名了 87 个真实叶子键（其中 9 个是 `bool`，与 R1 重叠），这些键**按表内规则渲染**（如 `client.stop_music_volume` 是 `str` 但要走 `int 0..100` + 写回字符串，不能当普通文本）。R1/R2/R3 只是兜住**表内未点名**的部分，保证无遗漏。

§10.2 的 `schema_covers_every_leaf_key` 与前端 `schema_paths` 断言共同保证：**任何未被上述任一规则覆盖的键都会让测试失败**，而不需要人手数一遍。

### 6.4 模型路径控件

| 键 | pathMode | 后缀 |
|---|---|---|
| `model_paths.model_dir` | directory | — |
| `model_paths.funasr_dir` | directory | — |
| `model_paths.punc_model_dir` | directory | — |
| `model_paths.opus_mt_dir` | directory | — |
| `model_paths.funasr_encoder_adaptor_path` | file | `.onnx` |
| `model_paths.funasr_ctc_path` | file | `.onnx` |
| `model_paths.funasr_llm_path` | file | `.gguf` |
| `model_paths.funasr_tokens_path` | file | `.txt` |
| `model_paths.funasr_hotwords_path` | file | `.txt` |
| `model_paths.sensevoice_path` | file | `.onnx` |
| `model_paths.sensevoice_tokens_path` | file | `.txt` |
| `model_paths.paraformer_path` | file | `.onnx` |
| `model_paths.paraformer_tokens_path` | file | `.txt` |

旧 GUI 对这几个文件键调用 `ValueCheck.is_file_exist(path)` 时**未传后缀**（`model_paths_config_page.py:287,333,377,423,471,517,561,607,651`），新实现补上后缀校验，但**校验失败只警告不阻断**（模型文件可能尚未下载，见 §9.3）。

### 6.5 派生只读键

9 个 `${model_paths.*}` 键渲染为只读，显示当前生效值：

```ts
{
  path: 'funasr_args.encoder_onnx_path',
  segments: ['funasr_args','encoder_onnx_path'],
  title: 'Encoder ONNX 路径（派生）',
  type: 'string',
  widget: 'readonly',
  derivedFrom: 'model_paths.funasr_encoder_adaptor_path',
}
```

只读控件展示：`<当前占位符原文>` + 「实际生效：`<model_paths 解析值>`」+ 说明「该值由 `model_paths` 段决定，修改 `funasr_args` 段不生效」。点击「跳转」定位到对应 `model_paths` 字段。

映射表：

| 派生键 | 真实来源 |
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

注意：这 9 个键在 TOML 中**仍然存在**，保存时**不删除、不改写**（保持 `config.toml` 结构完整，符合「结构保留」）。

### 6.6 覆盖断言

用一个测试锁定覆盖率：

```rust
// src-tauri/tests/schema_coverage.rs
#[test]
fn schema_covers_every_leaf_key() {
    let schema = load_schema_paths();                    // 从 src/lib/schema 生成的 JSON
    let doc = std::fs::read_to_string("../configs/default config.toml").unwrap();
    let actual = collect_leaf_segments(&doc);            // toml_edit 遍历
    let actual_set: BTreeSet<Vec<String>> = actual.into_iter().collect();
    let schema_set: BTreeSet<Vec<String>> = schema.into_iter().collect();
    assert_eq!(schema_set, actual_set);
}
```

前端 schema 在构建期被序列化成 JSON 供 Rust 测试读取（`vite build` 时产出的 `src/lib/schema/index.ts` 由一个小脚本导出），或者更简单：测试直接读一份手写的 `src-tauri/tests/schema_paths.json`，并在前端加一个 vitest 断言「schema 导出的 segments 集合 == `schema_paths.json`」。两种方案都保证双向一致。

**选定方案**：前端 vitest 断言 schema → `schema_paths.json`（构建期生成），Rust 测试断言 `schema_paths.json` → `configs/default config.toml`。两侧各管一段，链条闭合。

若 `config.toml` 未来新增键，Rust 测试立即失败，强制补 schema。

---

## 7. 保存流程（安全性核心）

### 7.1 七命令接口

```rust
// commands.rs
#[tauri::command] async fn open_config(path: String) -> Result<Opened, CmdError>;
#[tauri::command] async fn preview_save(state, patches: Vec<Patch>) -> Result<Preview, CmdError>;
#[tauri::command] async fn commit_save(state, patches: Vec<Patch>, fingerprint: FileFingerprint) -> Result<Committed, CmdError>;
#[tauri::command] async fn reload_config(state) -> Result<Opened, CmdError>;
#[tauri::command] async fn pick_path(state, mode: PickMode, suffix: Option<String>) -> Result<Option<String>, CmdError>;
#[tauri::command] async fn running_processes() -> Result<Vec<RunningInfo>, CmdError>;
#[tauri::command] async fn restart_service(state, target: ServiceTarget) -> Result<(), CmdError>;
```

只注册这 7 个命令；`capabilities/default.json` 只授权 `core:default` 与这 7 个自定义命令，**不授予 `fs:*`、`shell:*`、`process:*` 权限**。所有磁盘与进程操作经 Rust，前端无直接文件访问或执行能力。

尤其注意 `restart_service` 不接受任意 exe 路径——参数 `ServiceTarget` 是枚举（`Server` / `Client`），Rust 侧按 §9.4 的固定白名单解析出 exe 名，避免前端把一个命令注入接口变成任意程序启动器。

`pick_path` 需要 `state` 是因为文件对话框要挂在主窗口上（`tauri-plugin-dialog` 的 blocking 变体），并且返回后要按 §6.4 的 `fileSuffix` 与 `pathMode` 做一次存在性/后缀预检。

#### config.toml 的定位规则（启动时）

`open_config(path: String)` 的 `path` 由 Rust 在启动时解析后注入，不让前端猜。解析顺序：

1. **命令行第一个参数**（若给出且是存在的文件）——支持 `edit_config_gui.exe "D:\某处\config.toml"`，也方便测试时指定 fixture。
2. **exe 所在目录的 `config.toml`**。这是主路径：打包后 `edit_config_gui.exe` 与 `config.toml`、`start_server_gui.exe` 同在仓库根，与旧 PyStand 版的相对布局一致。
3. **当前工作目录的 `config.toml`**——开发模式下 `pnpm tauri dev` 的 cwd 是 `edit_config_gui/`，此级仅作兼容兜底。
4. 以上都不存在 → 进入「未找到配置」状态：界面正常打开但只显示一个引导卡片，提供「选择 config.toml…」按钮（走 `pick_path` 的 file 模式）与「打开所在文件夹」。**不静默创建空 config.toml**——凭空生成一个缺注释缺键的文件会破坏「结构保留」的前提。

> 为什么不能沿用旧版的「cwd 决定一切」：旧 `edit_config_gui.py:109` 写的是 `ConfigEditor("config.toml")`，纯相对路径，靠 PyStand 把 cwd 设成 exe 目录才成立。Tauri 产物从资源管理器、开始菜单快捷方式、或任意 shell 里启动时 cwd 均不可控，必须改成以 `current_exe()` 的父目录为锚。`config_selector.py:33-35` 同样依赖 `Path.cwd()`，属于既有行为，本次不改。

解析结果记在 `ConfigDoc` 里，后续 `preview_save` / `commit_save` / `reload_config` 全部使用这个绝对路径，前端不再传路径（`commit_save` 只传 `fingerprint`）。这样即使前端被注入也无法把写入重定向到别的文件。

### 7.2 预览与提交分离

```
open_config
  → 读文件 → ConfigDoc::parse → to_plain_json
  → { data, fingerprint: {mtime, size, sha256} }
  → 前端存 original/current

用户编辑 → dirty 集合

点「保存」
  → preview_save(patches)
      → 全部校验（任一失败 → Err（含字段路径与文案），不进入下一步）
      → 在内存副本上 set_typed 逐条应用
      → 生成 unified diff（对比原文与改后文本）
      → 返回 { diff, changed }
  → 前端弹 DiffDialog 展示 diff

用户在 diff 弹窗点「确认写入」
  → commit_save(patches, fingerprint)
      → 重新读文件，重算指纹，与传入 fingerprint 比对
          不一致 → Err(FileChangedExternally)，前端提示「重载 / 覆盖?」
      → 全部校验再跑一次（防止预览与提交之间状态变化）
      → 在内存副本上 set_typed 应用到真实文档文本（含 §7.4 的 LF 归一/CRLF 还原）
      → 写 config.toml.tmp（同目录）→ flush → sync_all
      → ReplaceFileW(config.toml.tmp → config.toml, 备份槽 = config.toml.bak)
          失败 → 删 .tmp，原文件未动，返回 IO 错误
      → 回读 config.toml，用 toml_edit 重新解析，验证可解析且键集合未变
          失败 → 用 .bak 回滚，返回错误
      → 返回 { fingerprint, valid: true }
  → 前端清空 dirty、刷新 original
```

**关键点**：diff 展示的是 Rust 用真实 `toml_edit` 算出的文本差异，不是前端模拟；提交时再算一遍，两次结果必须一致（不一致说明期间文件被改）。

**备份与替换是一步，不是两步。** 实测 `ReplaceFileW(replaced, replacement, backup, …)` 的语义（本机 Windows，实测三组）：

| 场景 | `.bak` 传入前 | 返回 | 替换后 `config.toml` | 替换后 `.bak` | `.tmp` |
|---|---|---|---|---|---|
| `.bak` 不存在 | 无 | `TRUE` | 新内容 | **旧内容**（自动生成） | 已消失 |
| `.bak` 已存在（第二次保存） | 旧内容 | `TRUE` | 新内容 | **被替换前的上一版内容**（自动覆盖） | 已消失 |

即：**`ReplaceFileW` 自己就把「被替换的旧文件」搬进备份槽，并覆盖同名旧备份**。所以不要先手动 `copy config.toml → .bak` 再调 `ReplaceFileW`——那会写两遍备份，且在两步之间崩溃会留下不一致状态。一次调用同时获得：原子替换 + 原子备份 + 保留原文件的 ACL/安全描述符。

**关于 ACL**（实测：给 `target.toml` 额外加一条 `Everyone:Read` ACE，`.tmp` 不加，替换后对比 SDDL）：

| 操作 | 替换后 `target.toml` 的 ACL | 自定义 ACE（`Everyone:Read`） |
|---|---|---|
| `ReplaceFileW` | == 原 `target.toml` 的 ACL（SDDL 字符串完全相等） | **保留** |
| `Move-Item -Force`（等价 `std::fs::rename`） | == 被移入的 `.tmp` 的 ACL | **丢失** |

所以选 `ReplaceFileW` 而非 `std::fs::rename` 不只是为了原子性——`rename` 会把 `.tmp` 的安全描述符带到 `config.toml` 上，如果用户曾给 `config.toml` 设过特殊权限（共享目录、只读锁等），一次保存就会静默清掉。`.bak` 的 ACL 实测也等于原 `target.toml` 的 ACL，符合「备份就是原文件」的语义。

失败时（实测，`windows-sys 0.59` 的 `ReplaceFileW`，三种备份参数对比）：

| `lpBackupFileName` | 返回值 | 结果 |
|---|---|---|
| `NULL`（`std::ptr::null()`） | 非零（成功） | 替换成功，不产生备份 |
| 空字符串 `""` | **0（失败）** | `ERROR_PATH_NOT_FOUND`；`config.toml` 保持旧内容、`.tmp` 仍存在 |
| 真实路径 | 非零（成功） | 替换成功，旧内容进备份槽 |

所以：**跳过备份要传 `NULL`，绝不能传空字符串**——注意 PowerShell 里 `$null` 传给 `string` 形参会变成空串，这就是早期用 P/Invoke 探测时看到「传 null 也失败」的真实原因。Rust 侧必须显式用 `std::ptr::null()`，不能用 `""`。

失败后 `config.toml` 与 `.bak` 都不动、`.tmp` 还留着新内容，可安全删除后报错。**实现必须检查返回值，不能假设成功。** 回滚同样走 `ReplaceFileW`（用 `.bak` 作为 replacement、给一个临时废弃槽作为 backup），实测可把文件还原。

### 7.3 类型保真

`set_typed` 的写入规则：

1. 若目标键**已存在**，按原有 `Item` 类型写：
   - 原是 `Value::String` → 无论 patch 是 `Int` 还是 `Str`，写字符串。
   - 原是 `Value::Integer` → 写整数。
   - 原是 `Value::Float` → 写浮点。
   - 原是 `Value::Boolean` → 写布尔。
   - 原是 `Array` → 写数组（元素类型按原数组元素类型）。
2. 若目标键**不存在**（新增动态表项），按 `PatchValue` 的类型写。
3. 类型冲突（如原是字符串、patch 是 `PairArray`）→ 返回 `TypeMismatch` 错误，拒绝写入。

这样 `server.speech_recognition_port` 永远保持 `"6016"` 字符串形式，不会因为用户输入了数字而被改成整数。

### 7.4 注释与格式保留（已实测，含一处必须规避的陷阱）

对真实 `config.toml`（852 个 CRLF 行、306 行注释、162 个键）逐项实测 `toml_edit 0.22`：

**结论 1：输入归一化到 LF 后，往返字节完全一致。**

```rust
let raw = fs::read_to_string(path)?;             // 含 \r\n
let lf  = raw.replace("\r\n", "\n");
let doc: DocumentMut = lf.parse()?;
let out = doc.to_string().replace('\n', "\r\n");  // 写回前恢复
assert_eq!(out, raw);                             // ✅ 实测 true
```

**结论 2（陷阱）：直接把 CRLF 文本喂给 `DocumentMut::parse` 会破坏换行符。**

| 做法 | `\r\n` 数 | 裸 `\n` 数 | 字节还原 |
|---|---|---|---|
| 直接 `parse(raw)` 后 `to_string()` | 852 → **199** | 0 → **653** | ❌ false |
| 先归一 LF、写完再还原 CRLF | 852 | 0 | ✅ true |

原因：`toml_edit` 把 `\r\n` 当作键值 decor 的一部分逐段保存，但多行字符串、数组内部等位置会被重新排版成 LF，产生**混合换行**（199 个 CRLF + 653 个裸 LF），文件全文被污染。**必须走「归一化 → 编辑 → 还原」三步**，这是硬性实现约束。

**结论 3：不修改时字节完全一致；改单行键只变那一行。**

- 纯往返（不调任何 setter）：`out == raw` 为 true。
- 逐键写入探针值（遍历全部 162 个键，按原类型各写一个探针值）：**154 个单行键全部只改变 1 行**，其余行（含 306 行注释、空行、键顺序、行尾注释）逐行相同；换行符全部保持 CRLF。
- 剩余 8 个是多行字符串键（`client.prompt_style.prompt_*` 8 个正文），行数变化是**语义正确**的：写入不含换行的新值时，`"""` 三引号块从多行折叠为单行，行数随之减少。这不是格式损坏。

**结论 4：多行字符串与特殊字符由 `toml_edit` 自动选择正确的引号形式，回读值恒等于写入值。**

| 写入值 | 实际落盘形式 | 回读 == 写入 |
|---|---|---|
| `第一行中文\n第二行带"引号"` | `"""` 多行三引号 | ✅ |
| `don't stop` | `"don't stop"` | ✅ |
| `say "hi"` | `'say "hi"'`（改用字面量单引号） | ✅ |
| `a"""b` | `'a"""b'` | ✅ |
| `C:\path\to` | `'C:\path\to'` | ✅ |
| `a\tb`（制表符） | `"a\tb"` | ✅ |
| `""`（空串） | `""` | ✅ |

即：**无需自己转义**，交给 `toml_edit` 的 `Value::from(&str)` 即可。但**禁止把含换行的值写进单行键**——实测 `server.addr = "a\nb"` 会被自动升格成 `"""` 三引号多行形式，虽然仍可解析，但会把单行配置改成 4 行，破坏用户预期。写入前须按字段类型校验：单行控件（text/enum/path/hotkey/port）拒绝含 `\n` 的值，只有 `longText` 控件（8 个提示词）允许换行。

**结论 5：动态表 `client.additional_special_apps` 的增删改精确可控。**

该表在 TOML 里是 `[client.additional_special_apps]` 表头 + 一行行内表：

```toml
[client.additional_special_apps]
"vlc.exe" = { hotkey = "ctrl + alt + f9", name = "VLC Media Player" } # VLC 设置全局快捷键后需要重启 VLC 才能生效
```

实测增删改：

| 操作 | 行数变化 | 逐行对比 |
|---|---|---|
| 改 `hotkey` 值 | 0 | 只该行变化，**行尾注释保留** |
| 新增一项 | +1 | 只有 1 行新增，紧跟在 `vlc.exe` 行之后；**无任何原有行消失** |
| 删除一项 | −1 | 只有该行消失；**表头与表尾注释块全部保留** |
| 整表清空后重建 | 0（净） | 表头注释、表尾注释块保留，**但每个条目的行尾注释会丢** —— 故实际实现禁用此路径（见 §9.5） |

因此**不需要**在表头注释上做手工搬运（§12 原风险项可降级）。实现只需 `Table::insert` / `Table::remove` + `InlineTable`，不重建整个 `Table`。

**结论 6：数组（`enter_apps` / `disable_exe_list*`）编辑需修一处 decor。**

`toml_edit` 给数组元素保存了 `prefix`（通常是分隔用的空格）。直接 `Array::remove(0)` 删掉首元素后，原第二元素的 `prefix = " "` 会成为新的首元素前缀，输出成 `[ ["hexin.exe", 0.5]]`（多一个空格）。实测修复方式：

```rust
arr.remove(0);
if let Some(first) = arr.get_mut(0) { first.decor_mut().set_prefix(""); }  // 清掉多余空格
```

追加元素时对称处理：新元素 `set_prefix(" ")`。按此规则重建 `enter_apps` 后，输出与原始格式**逐字符一致**：

```toml
enter_apps = [["happ.exe", 0.5], ["hexin.exe", 0.5]]   # ✅ 与原文件相同
```

`disable_exe_list` 改值为 `["a.exe", "b.exe"]` 时，行尾注释与其后注释块均保留；改为空数组输出 `[]`。

**定义「注释与格式无损」的可执行判据**（进 `cargo test`，见 §10.1）：

1. 不修改任何键时：`emit(parse(normalize(raw))) == raw`（字节相等）。
2. 修改任一单行键时：输出行数 == 原始行数，且仅 1 行不同。
3. 所有修改场景下：输出的 `\r\n` 计数 == 总 `\n` 计数（无裸 LF）。
4. 所有修改场景下：原文件的 306 行注释一行不少（多行字符串折叠场景除外——那里注释可能随内容移动，需按「注释多重集相等」判定）。

新增的 `# 如果不修改任何键` 这类守卫测试，是防止后续升级 `toml_edit` 版本时静默破坏格式的关键。

### 7.5 失败模式

| 失败 | 行为 |
|---|---|
| 校验失败 | 整批拒绝，不写任何键；返回全部错误 |
| 文件被外部修改 | 拒绝写入，前端提示「重载 / 强制覆盖」 |
| 写 `.tmp` 失败（磁盘满/无权限） | 删除 `.tmp`，原文件不变，返回 IO 错误 |
| `ReplaceFileW` 返回 FALSE | 原文件与 `.bak` 均未动（实测），删除 `.tmp`，返回错误 + `GetLastError` 文案 |
| 回读解析失败 | 用 `.bak` 反向 `ReplaceFileW` 回滚（实测可行），返回错误。这是最后一道防线 |

注意：**不存在「备份成功但替换失败」或「替换成功但备份失败」的中间态**——`ReplaceFileW` 把两者做成一个原子操作（§7.2 实测）。唯一可能的中间态是「`.tmp` 已写入但 `ReplaceFileW` 未执行」，此时原文件与 `.bak` 都还是旧状态，删除 `.tmp` 即可完全恢复。

---

## 8. 校验规则

全部在 Rust 侧实现，与旧 `util/edit_config_gui/value_check.py` 等价。

| ValidatorId | 规则 | 错误文案 | 来源 |
|---|---|---|---|
| `ip` | `IPv4Address` 可解析 | 不是有效的IP地址 | `ValueCheck.is_ip` |
| `localListenableIp` | `ip` + private/loopback/link-local/`0.0.0.0` | 不是有效的本地可监听IP地址 | `ValueCheck.is_local_listenable_ip` |
| `port` | 整数且 1023 ≤ p ≤ 65535 | 端口号必须在1023到65535之间 / 不是有效的端口号 | `ValueCheck.is_local_listenable_port` |
| `fileExist` | 存在且是文件；给定 `fileSuffix` 时后缀匹配 | 文件不存在 / 不是有效的文件 / 文件格式不正确，预期后缀为X | `ValueCheck.is_file_exist` |
| `dirExist` | 存在且是目录 | 目录不存在 | `ValueCheck.is_dir_exist` |
| `hotkey` | 等价 `keyboard.parse_hotkey` | 快捷键格式不正确 | `ValueCheck.is_hotkey` |
| `url` | 空则按 `allowEmpty`；否则须以 `http://` 或 `https://` 开头 | URL必须以http://或https://开头 | `ValueCheck.is_valid_url` |
| `ipPort` | `host:port` 或纯 `host`（消费端会补 `:5555`），port 走 `port` 规则 | 不是有效的地址 / 端口号必须在1023到65535之间 | 新增，仅 `client.adb_addr`（见 §8.0.1） |
| `regexClass` | 非空，且不含会破坏 Python 字符类的字符 | 该配置项不能为空 / 该字符不能用于此处 | 新增，仅 `client.trash_punc`（见 §8.0.1） |
| `singleLine` | 值不得含 `\n` / `\r` | 该配置项不能包含换行符 | 新增（§7.4 结论 4）；仅 8 个 `longText` 提示词字段豁免 |

**IPv4 private 判定**需与 Python `ipaddress` 一致：`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`；`is_link_local` 为 `169.254.0.0/16`；`is_loopback` 为 `127.0.0.0/8`。

`allowEmpty: true` 的字段为空时不跑校验（4 个暂停快捷键、`vscode_exe_path`、`openai.base_url`）。`client.disable_exe_list = [""]` 这种「空列表占位」按空数组处理，不视为错误。

### 8.0.1 两个旧 GUI 完全不校验的键（新增校验器，属行为变更）

这两个键旧 GUI 从未纳入 `value_check.py`，但各有实测可复现的故障路径：

**`client.trash_punc`（标点集合）**——消费端 `util/client/strip_punc.py:22`：

```python
clean_text = re.sub(f"(?<=.)[{Config.trash_punc}]$", "", text)
```

值被**原样拼接进正则字符类**。已在本机 `re` 上逐个字符实测：

| 值 | 生成的 pattern | 结果 |
|---|---|---|
| `，。,.`（模板值，4 字符） | `(?<=.)[，。,.]$` | ✅ 正常 |
| `""`（空串） | `(?<=.)[]$` | ❌ `re.error: unterminated character set` —— 点「恢复默认值」若清空即触发 |
| `\` | `(?<=.)[\]$` | ❌ `re.error: unterminated character set` |
| `^` | `(?<=.)[^]$` | ❌ `re.error: unterminated character set`（`^` 在类首表示取反） |
| `[` | `(?<=.)[[]$` | ⚠️ 能编译但**不匹配 `[` 自身**，且触发 `FutureWarning: Possible nested set` —— 静默失效 |
| 其余全部可打印 ASCII（含 `]` `(` `)` `*` `+` `?` `.` `-`） | — | ✅ 正常且能匹配自身（这些字符在字符类内失去特殊含义） |

→ 校验器 `regexClass`：**非空**，且**不含 `\`、`^`、`[`** 这三个字符。错误文案分别为「该配置项不能为空」/「该字符不能用于此处」。这是**行为变更**（旧版允许写坏，然后运行时崩在 `strip_punc`），需在发布说明标注。

**`client.adb_addr`（手机 adb 地址）**——消费端 `util/client/adb_control.py:341-349`：

```python
addr = str(Config.adb_addr).strip()
if not addr:
    return ""
if ":" not in addr:
    addr = f"{addr}:5555"
```

模板值 `192.168.3.127:10101`。旧 GUI 完全不展示该键，用户只能手改 TOML。消费端**不做任何格式校验**，写错只会得到「连接手机失败」。

→ 校验器 `ipPort`：接受 `host:port` 或纯 `host`（消费端会自动补 `:5555`，故纯 host 必须合法）；有 `:` 时 port 部分套 `port` 规则。**不做** `ip` 严格校验（保留主机名可用性）。`enable_adb_control=false` 时该字段隐藏，不参与全量校验。

### 8.1 快捷键解析（唯一有实质移植风险）

Python `keyboard` 库的真实解析链（已读源码确认，非推测）：

1. `parse_hotkey(hotkey)`（`keyboard/__init__.py`）：

```python
def parse_hotkey(hotkey):
    if _is_number(hotkey) or len(hotkey) == 1:
        scan_codes = key_to_scan_codes(hotkey)
        step = (scan_codes,); steps = (step,); return steps
    elif _is_list(hotkey):
        ...
    steps = []
    for step in _re.split(r',\s?', hotkey):
        keys = _re.split(r'\s?\+\s?', step)
        steps.append(tuple(key_to_scan_codes(key) for key in keys))
    return tuple(steps)
```

2. `key_to_scan_codes(key)`（`keyboard/__init__.py`）：先 `normalize_name(key)`；若结果属于 `sided_modifiers = {'ctrl','alt','windows','shift'}`，则递归尝试 `left <name>` 与 `right <name>`，任一成功即可；否则调 `_os_keyboard.map_name(normalized)`，抛异常即非法。

3. `normalize_name`（`_winkeyboard.py`，Windows 后端，**覆盖** `_canonical_names.py` 的同名函数）：

```python
def normalize_name(name):
    if not name or not isinstance(name, basestring):
        raise ValueError('Can only normalize non-empty string names. Unexpected '+ repr(name))
    if len(name) > 1:
        name = name.lower()
    if name != '_' and '_' in name:
        name = name.replace('_', ' ')
    return canonical_names.get(name, name)
```

4. `map_name(name)`（`_winkeyboard.py`）：`_setup_name_tables()` 后查 `from_name[name]`，缺失则抛 `ValueError('Key name ... is not mapped to any known key.')`。

关键实测数据（`from_name` 与 `canonical_names` 是**两张不同的表**）：

| 表 | 项数 | 作用 |
|---|---|---|
| `canonical_names`（`_canonical_names.py`） | 1171 | 仅做**别名归一**（`escape`→`esc`、`return`→`enter`、`del`→`delete`、`_`→`-`），其 1086 个 value 里只有 70 个能被 `from_name` 接受 |
| `from_name`（`_winkeyboard.py`，运行时 `_setup_name_tables()` 构建） | **205** | 真正的**合法键名全集**，是唯一权威判据 |

因此**只需嵌入 205 个合法键名 + 1171 项别名表**，不必移植按键码表（`to_name` 有 2760 项，与校验无关）。

**Rust 实现（已用 35 个用例逐条比对 Python 实测结果，0 处不符）**：

```rust
const SIDED_MODIFIERS: [&str; 4] = ["ctrl", "alt", "windows", "shift"];

fn normalize_name(name: &str) -> Option<String> {
    if name.is_empty() { return None; }
    let lower = if name.chars().count() > 1 { name.to_lowercase() } else { name.to_string() };
    let replaced = if lower != "_" && lower.contains('_') { lower.replace('_', " ") } else { lower };
    Some(CANONICAL_NAMES.get(replaced.as_str()).cloned().unwrap_or(replaced))
}

fn is_valid_key(name: &str) -> bool {
    let Some(n) = normalize_name(name) else { return false };
    if SIDED_MODIFIERS.contains(&n.as_str()) {
        return is_valid_key(&format!("left {n}")) || is_valid_key(&format!("right {n}"));
    }
    ACCEPTED_NAMES.contains(&n.as_str())          // 205 项 HashSet
}

fn is_valid_hotkey(hk: &str) -> bool {
    if hk.is_empty() { return false; }                              // Python: len('')==1 为假，但空段必失败
    if hk.chars().count() == 1 || hk.parse::<i64>().is_ok() {       // _is_number 或单字符
        return is_valid_key(hk);
    }
    for step in split_step(hk) {            // 等价 re.split(r',\s?', hk)
        for key in split_plus(&step) {      // 等价 re.split(r'\s?\+\s?', step)
            if !is_valid_key(&key) { return false; }
        }
    }
    true
}

/// 复刻 re.split(r',\s?', s)：逗号后最多吃掉一个空白字符
fn split_step(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut it = s.chars().peekable();
    while let Some(c) = it.next() {
        if c == ',' {
            out.push(std::mem::take(&mut cur));
            if it.peek().is_some_and(|n| n.is_whitespace()) { it.next(); }
        } else {
            cur.push(c);
        }
    }
    out.push(cur);
    out
}

/// 复刻 re.split(r'\s?\+\s?', s)：'+' 前后各最多吃掉一个空白字符
fn split_plus(s: &str) -> Vec<String> {
    let chars: Vec<char> = s.chars().collect();
    let is_ws = |c: char| c.is_whitespace();
    let (mut out, mut cur, mut i) = (Vec::new(), String::new(), 0usize);
    while i < chars.len() {
        let lead = if is_ws(chars[i]) && chars.get(i + 1) == Some(&'+') { 1 }
                   else if chars[i] == '+' { 0 }
                   else { cur.push(chars[i]); i += 1; continue; };
        let mut end = i + lead + 1;
        if end < chars.len() && is_ws(chars[end]) { end += 1; }
        out.push(std::mem::take(&mut cur));
        i = end;
    }
    out.push(cur);
    out
}
```

切分细节（必须与 Python 的 `_re.split(r',\s?', ...)` / `_re.split(r'\s?\+\s?', ...)` 等价）：

- 逗号后**最多**吃掉一个空格；`+` 前后**最多**各吃掉一个空格。**不是** `split('+')` —— 那样 `"ctrl + alt + f5"` 会切成 `["ctrl ", " alt ", " f5"]`，三段都带空格，全部误判为非法。
- 因此 `"  ctrl  +  alt  +  f5  "` 切成 `[" ctrl  ", " alt  ", " f5  "]` → 首段仍带前导空格 → 归一后查不到 → **非法**（与 Python 一致，**不做 trim**）。
- `"ctrl + shift + ,"` 先按逗号切成 `["ctrl + shift + ", ""]` → 含空段 → **非法**（实测 Python 同样拒绝）。
- 单字符与纯数字整体短路：`"+"` 与 `"_"` 在 `len == 1` 分支直接走 `is_valid_key`，不会进 `split_plus`，否则 `"+"` 会被切成两个空串。`"_"` 经别名表映射为 `"-"`，合法。`"3"` 走 `_is_number` 分支同样短路。
- 空串必须最先拦掉：Python 的 `len('') == 1` 为假，会落到正则分支切出 `[""]`，最终因空段失败——结果同样是非法，但 Rust 侧显式早退更清晰。

**构建期表导出**：用脚本从 `.venv` 的 `keyboard` 包导出两张表到 `src-tauri/src/`：

```python
from keyboard import _winkeyboard as wk, _canonical_names as cn
wk._setup_name_tables()
json.dump(sorted(wk.from_name.keys()), open('accepted_names.json','w'), ensure_ascii=False)  # 205 项, 1.7 KB
json.dump(cn.canonical_names, open('canonical_names.json','w'), ensure_ascii=False)            # 1171 项, 22.1 KB
```

两个 JSON 用 `include_str!` + `serde_json` 在首次校验时惰性解析（`OnceLock`）。导出脚本放 `edit_config_gui/scripts/export_hotkey_tables.py`，生成的 JSON 提交进仓库——这样构建不依赖 `.venv`，且表内容可审计。

**必须通过的既有行为**（下表 22 行，展开为一对一用例共 **27 个**：19 个合法 + 8 个非法。已用 `.venv` 的 `keyboard` 逐条跑过，27/27 与规格期望一致）：

下表是**最小回归集**，写进 `cargo test` 必须逐条通过。除这 27 个之外，还做了一轮**大规模对拍**（见 §8.1.1）以确保 Rust 移植与 Python 在边角输入上不漂移。

| 输入 | 期望 |
|---|---|
| `caps lock` | 合法 |
| `ctrl + alt + f5` | 合法 |
| `Ctrl + Alt + F5` | 合法（大小写不敏感） |
| `left shift` | 合法 |
| `ctrl + alt + [` | 合法 |
| `f13` | 合法 |
| `f24` | 合法 |
| `space` / `enter` / `shift` | 合法 |
| `+` | 合法（加号键） |
| `_` | 合法（别名映射到 `-`） |
| `esc` / `escape` | 合法（`escape` 经别名表归一为 `esc`） |
| `ctrl+alt+f5`（无空格） | 合法 |
| `alt+a, alt+b` | 合法（两段组合） |
| `volume up` / `left windows` / `alt+f4` | 合法 |
| `f999` | 非法 |
| `f25` | 非法 |
| 空串 `""` | 非法（除 `allowEmpty` 字段） |
| `ctrl + ` | 非法 |
| `mouse left` | 非法 |
| `  ctrl  +  alt  +  f5  `（首尾空格） | 非法（与 Python 一致，不自动 trim） |
| `ctrl + shift + ,` | 非法（逗号切出空段） |
| `鼠标` | 非法 |

#### 8.1.1 大规模对拍（已完成）

为确认移植无漂移，用真实数据做了 841 例对拍：把 `config.toml` 中实际出现的全部快捷键值、修饰符 × 主键的组合爆炸（8 种修饰符 × 33 个主键 × 3 种空格写法）、逗号分段组合、单字符与纯数字、大小写与空白变体全部喂给 Python 的 `keyboard.parse_hotkey` 与上述 Rust 实现，逐条比对。

- 用例数 **841**（合法 432 / 非法 409）
- **差异 0 处**

本机复现方式：`edit_config_gui/scripts/export_hotkey_tables.py` 导出两张表后，用 `cargo test` 里的 `hotkey_parity` 用例读同一份 `cases.txt` 断言逐行一致。这次对拍覆盖了旧规格伪代码会误判的一类输入（`"ctrl + alt + f5"` 被 `split('+')` 切成带空格的三段），因此 §8.1 的伪代码已按实测通过的版本改写。

注意：**不自动 trim**，这是 Python 的实际行为，必须一比一保留，否则校验会放行 Python 会拒绝的输入。

| 这 27 个用例全部写进 `cargo test` 的 `validate_hotkey` 用例表（§10.1）；841 例对拍集另存为 `src-tauri/tests/fixtures/hotkey_cases.txt` + `hotkey_expected.txt`，由 `hotkey_parity` 用例消费。

> 上表 27 例已用 `.venv` 里的 `keyboard` 逐条实测复核（19 合法 / 8 非法），与规格标注完全一致。附带确认两个别名：`keyboard.normalize_name('esc') == 'esc'`、`keyboard.normalize_name('escape') == 'esc'`、`keyboard.normalize_name('_') == '_'`（`_` 原样返回但 `parse_hotkey` 能把 `_` 解析成扫描码 `(12,)`，即减号）。

### 8.2 校验时机

- 字段失焦：单字段校验，内联红框 + 错误文案。
- 每次输入变更：仅做「无副作用」的格式校验（ip/port/hotkey/url），不碰文件系统。
- `preview_save` / `commit_save`：全量校验（含 `fileExist`/`dirExist`），任一失败整批拒绝。

---

## 9. 交互设计

### 9.1 布局

```
┌─────────────────────────────────────────────────────────┐
│ 配置编辑器  config.toml            [搜索框]    [⚙ 进程提示] │
├──────────────┬──────────────────────────────────────────┤
│ 服务端     ① │                                          │
│ 客户端     ③ │  ▸ 基础                                    │
│ AI 服务商     │    地址         [127.0.0.1        ] [选]  │
│ 提示风格      │    端口         [6016             ]       │
│ 附加应用      │  ▸ 录音                                    │
│ LibreTranslate│    ...                                    │
│ DeepLX       │                                          │
│ 模型路径      │                                          │
│ FunASR 参数   │                                          │
│ SenseVoice    │                                          │
│ Paraformer    │                                          │
│ 调试         │                                          │
├──────────────┴──────────────────────────────────────────┤
│ 已修改 3 项      [放弃]  [预览并保存 Ctrl+S]              │
└─────────────────────────────────────────────────────────┘
```

### 9.2 相对旧 GUI 的交互改进

| 项 | 旧 | 新 |
|---|---|---|
| 全局搜索 | 无 | 顶部搜索框，按标题/键名/注释过滤，回车跳转并高亮 |
| 脏态 | 无提示 | 导航项角标计数 + 底部脏状态栏 |
| 未保存关闭 | 直接关 | 拦截确认 |
| 撤销 | 无 | 「放弃」回滚全部；单字段「恢复默认」 |
| 默认值 | 41 个实例 / 42 条 connect，其中 1 个按钮从未接线、2 个被重复绑定；5 处与出厂模板不一致（含 4 个暂停快捷键被清空） | schema 从 `configs/default config.toml` 导出，单一来源，无死按钮 |
| 校验反馈 | 控制台 print + 右侧消息栏 | 内联红框 + 错误文案 + 底部汇总 |
| 校验失败处理 | **覆写用户输入为默认值** | 保留输入，标红，阻止保存 |
| 快捷键 | 手打 `"ctrl + alt + f5"` | 录制模式：按下组合键自动填入 |
| 列表 | 手写 TOML 数组 | 标签式增删 |
| `enter_apps` | 不可编辑 | `(进程名, 延迟秒)` 表格 |
| 条件显隐 | 散落的 `xxx_changed()` | 声明式 `visibleWhen` |
| 变更可见性 | 保存即写，无预览 | diff 弹窗确认 |
| 注释 | 不展示 | 每字段下方以说明文字展示 TOML 注释 |
| 保存安全 | `open(w)` 截断写 | 备份 + 原子替换 + 回读校验 |

关于 `client.addr`：旧 GUI 用 `is_local_listenable_ip` 校验，但该键语义是「要连接的服务端地址」（`config.toml` 注释原文），允许远程地址。用户连局域网另一台机器时，`192.168.x.x` 通过，但公网 IP 会被旧 GUI 拒绝并覆写为 `127.0.0.1`。新实现改用 `ip` 校验（仍拒绝非法格式），这是**行为变更**，需在发布说明中标注。

### 9.3 模型文件缺失的处理

`model_paths.*` 指向的模型文件可能尚未下载（用户首次配置）。因此这些字段的 `fileExist` 校验**只警告不阻断**：

- 字段下方黄色提示：「文件不存在，可能尚未下载模型」。
- 保存时允许通过。
- 这与旧 GUI 的行为不同（旧 GUI 直接清空输入框），是刻意修正。

### 9.4 进程运行提示

进程名清单照抄 `util/server/restart.py:53-57` 与 `util/client/restart.py:52-57`（项目自己的停止清单，不是猜的）：

| 归属 | 进程名 |
|---|---|
| 服务端 | `start_server_gui.exe`、`python_CapsWriter_Server.exe`、`deeplx_windows_amd64.exe` |
| 客户端 | `start_client_gui_admin.exe`、`start_client_gui.exe`、`python_CapsWriter_Client.exe`、`hint_while_recording.exe` |

匹配规则与 `util/check_process.py:10-31` 一致：**大小写不敏感，且 `.exe` 后缀可省**（`get_target_names` 同时匹配 `foo.exe` 与 `foo`）。`core_server.py` / `core_client.py` 不作为匹配目标——它们由 `runtime\python_CapsWriter_Server.exe` / `runtime\python_CapsWriter_Client.exe` 启动（`start_server_gui.py:237`、`start_client_gui.py:1872`），进程名是后者，匹配脚本名会漏检。`config_selector.exe` 不参与检测（它不是本配置的消费方）。

检测结果在顶部常驻显示（服务端 ●运行中 / 客户端 ●运行中）。保存成功后若相关进程在跑，提示「配置已保存，需重启服务端/客户端后生效」。

**默认不自动重启**——重启会中断正在进行的语音输入。提供两个显式按钮：「重启服务端」「重启客户端」，语义对齐 `restart_server` / `restart_client`：先按上表逐个 `taskkill /IM <exe> /F`，再启动 GUI。

> **启动时的 cwd 必须显式设为 `config.toml` 所在目录**（即仓库根）。这是本次移植必须补上的一环：
> - 旧的 `start_exe`（`util/server/restart.py:32-36`、`util/client/restart.py:31-35`）执行的是 `start "" "<exe>"`，**没有传 `cwd`**，因而继承调用方进程的工作目录。旧配置编辑器由 PyStand 打包，其 cwd 恰好就是仓库根，所以一直没暴露问题。
> - 而 `core_server.py:39-41` 与 `core_client.py:35-36` 都把 `os.getcwd()` 当作 `BASE_DIR` 来加载相对路径的模型与配置。
> - 新编辑器是 Tauri 产物，从资源管理器双击或从任意目录启动时 cwd 不一定是仓库根。若直接用默认 cwd 拉起 `start_server_gui.exe`，服务端会以错误的 `BASE_DIR` 启动，表现为「模型加载失败」或「读不到 config.toml」。
> - 因此 Rust 侧用 `CreateProcessW` 的 `lpCurrentDirectory` 显式传入 `config.toml` 的父目录，`taskkill` 与 `start` 两步都要传。

客户端重启有一个分支差异：`restart_client` 拉起 `start_client_gui.exe`，`restart_client_admin` 拉起 `start_client_gui_admin.exe`（`util/client/restart.py:63-71`）。新编辑器按**当前正在运行的是哪个变体**决定拉起哪个：若检测到 `start_client_gui_admin.exe` 在跑就重启该变体，否则重启 `start_client_gui.exe`；两者都没跑时按 `start_client_gui.exe` 处理。服务端只有 `start_server_gui.exe` 一种。

服务端重启有一个**必须保留的既有陷阱**：`util/server/restart.py:66-69` 用 `is_admin()` 分流——当前进程是管理员时不能直接 `start`（会以管理员权限拉起服务端，导致客户端无法连接），必须走 `downgraded_via_explorer_token("start_server_gui.exe")` 借 explorer 的令牌降权启动。Rust 侧实现重启时**必须复刻这个判断**，否则用户从管理员身份的终端打开编辑器后点重启，客户端就连不上了。客户端重启无此问题（`restart_client` 直接 `start_exe`）。

`is_admin()` 的实现是 `shell32!IsUserAnAdmin`（`util/explorer_token_downgrade.py:17-21`，失败时返回 false）。降权路径的做法（`explorer_token_downgrade.py:104-201`）：`GetShellWindow` → `GetWindowThreadProcessId` 取 explorer PID → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` → `OpenProcessToken(TOKEN_DUPLICATE|TOKEN_QUERY)` → `DuplicateTokenEx` 建主令牌 → `CreateProcessWithTokenW`。本机实测：explorer.exe 的完整性级别是 **Medium**，经 `Start-Process explorer.exe <exe>` 代理拉起的进程也是 **Medium**，即降权确实生效。

> 本机当前会话**不是管理员**（`IsUserAnAdmin` = false），因此「管理员身份 + 降权重启」这条路径在本轮无法端到端实测。规格要求：实现时把 `is_admin` 与 `downgraded_via_explorer_token` 的逻辑一比一移植，并在代码注释里标注「此路径需管理员身份手工验证」，交付前由用户在有管理员权限的会话里手工跑一次。

### 9.5 附加特殊应用（动态表）

`client.additional_special_apps` 是一个「表键 → { hotkey, name }」的映射，键名是任意进程名（含点，如 `vlc.exe`）。渲染为三列表格：

| 进程名 | 全局快捷键 | 显示名称 | 操作 |
|---|---|---|---|
| `vlc.exe` | `ctrl + alt + f9` | VLC Media Player | [删除] |

新增行时校验：
- 进程名非空、不与已有行重复（去重按大小写不敏感比较，避免用户加出 `vlc.exe` 与 `VLC.exe` 两个只有一个会生效的行）。
- 快捷键走 `hotkey` 校验，允许空（空表示「不暂停」，见 `pause_other_audio.py:119-130`）。
- 显示名称非空。

> **匹配大小写必须精确保留，不要擅自小写化。** 这个表和 `disable_exe_list` / `enter_apps` 的匹配方式不同：
> - `additional_special_apps` 走 `util/client/pause_other_audio.py:101-102` 的 `if exe_name in special_apps_map`——**字典键精确相等、大小写敏感**。`exe_name` 来自 `session.Process.name()`（Windows 返回镜像文件的原始大小写），内置四键写的就是 `QQMusic.exe` / `CloudMusic.exe` / `PotPlayerMini64.exe` / `foobar2000.exe`。
> - `enter_apps` 走 `util/client/type_result.py:70-73`，`app.lower() == process_name`，而 `process_name` 在 `:131` 已 `.lower()`——**大小写不敏感**。
> - `disable_exe_list` / `disable_exe_list_on_focus` 走 `util/check_process.py:10-31`，`get_target_names` 先 `.lower()` 且额外允许省略 `.exe`——**大小写不敏感且后缀可省**。
>
> 所以编辑器三者都不能一律小写化：动态表的键要原样存用户输入（保存时保留大小写），只在去重/提示层面做大小写不敏感比较；`enter_apps` 的进程名可原样存，靠消费端自己 lower。

保存时按差异逐项应用，**不整表替换**：新增键走 `Table::insert`，删除键走 `Table::remove`，改值只改对应 `InlineTable` 的字段。实测（§7.4 结论 5）此做法下表头 `[client.additional_special_apps]`、表头注释块、表尾注释块全部保留，增删一项只增减 1 行，且不触及任何原有行。

新增行的**物理位置**已实测确认（对真实 config.toml 跑 toml_edit 0.22.27）：`Table::insert` 把新条目追加在本表最后一个数据行之后、表尾注释块之前。当前文件里即是插在 659 行 `"vlc.exe" = …` 之后、660 行 `# 如果还有除了 QQ音乐、网易云音乐…` 之前 —— 正好落在「数据区末尾」，不会跑到注释块下面变成孤儿数据。多重集对比结果为「删 0 行、增 1 行」，注释总数 306 保持不变。

> 反例：`Table::clear()` + 重建会丢掉每个条目的行尾注释（如 `# VLC 设置全局快捷键后需要重启 VLC 才能生效`）。实测可见该注释随被删项一起消失，而用户并没有删这一项。**因此禁止整表重建。**

### 9.6 主题与外观

- 图标使用 `assets/icon/config-icon.ico`（复制或引用到 `src-tauri/icons/`）。
- 窗口默认 1000×760，最小 760×520。
- 浅色/深色跟随系统。
- 中文界面，文案与 `config.toml` 注释保持一致。

---

## 10. 测试策略

### 10.1 Rust 单元测试（`cargo test`）

| 测试 | 断言 |
|---|---|
| `parse_real_config` | 解析真实 `config.toml` 成功，162 叶子键 |
| `byte_identical_roundtrip` | `emit(parse(normalize(raw)))` 与原始文件**字节相等**（最严格的格式守卫） |
| `crlf_preserved` | 任意修改后，输出的 `\r\n` 计数 == `\n` 计数（无裸 LF，无混合换行） |
| `single_line_key_touches_one_line` | 逐个修改 154 个单行键，每次输出行数不变且只有 1 行不同 |
| `comments_preserved_on_set` | 逐键写入探针值后重解析，注释行数 306 不变、键顺序不变、行尾注释仍在 |
| `newline_rejected_in_single_line` | 给 `server.addr` 写含 `\n` 的值返回校验错误，文件未被改成 `"""` 多行 |
| `type_fidelity_string` | `server.speech_recognition_port` 写 `"9999"` 后重新读，原值是 `TomlType::String` |
| `type_fidelity_int` | `client.audio_name_len` 写 `30` 后原值是 `Integer` |
| `type_fidelity_float` | `client.threshold` 写 `0.75` 后值为 `0.75`（精度不丢） |
| `type_mismatch_rejected` | 字符串键写 `PairArray` 返回 `TypeMismatch` |
| `diff_only_changed` | 改 3 个键，diff 只含这 3 行 |
| `atomic_write_failure` | 注入写失败，原文件字节不变 |
| `backup_contents` | `.bak` 内容 == 写入前原文；第二次保存后 `.bak` == 上一次内容 |
| `replace_keeps_acl` | 给目标文件加自定义 ACE，替换后 SDDL 与替换前相等 |
| `replace_null_backup_ok` | `lpBackupFileName` 传 `NULL` 时替换成功且不产生 `.bak`；传 `""` 时返回 0 且原文件不变（防回归：两种「无备份」写法语义不同） |
| `fingerprint_conflict` | 改 mtime 后 `commit_save` 返回 `FileChangedExternally` |
| `readback_validation` | 模拟写入后文件损坏，`commit_save` 恢复 `.bak` 并报错 |
| `validate_ip` | 9 个 IPv4 用例（含 `8.8.8.8` 通过 `ip`、拒绝 `localListenableIp`） |
| `validate_port` | `80`/`1023`/`1024`/`65535`/`65536`/`abc`/`0` |
| `validate_hotkey` | §8.1 全部 27 个最小回归用例（合法 + 非法双向） |
| `hotkey_parity` | 读 `tests/fixtures/hotkey_cases.txt` 841 例，逐行与 `hotkey_expected.txt` 相等（规格已用 Python 实测生成该期望，差异 0 处） |
| `validate_url` | `http://`、`https://`、`ftp://`、空串 |
| `validate_regex_class` | `，。,.` 通过；`""` / `\` / `^` / `[` 各返回一条错误；再对 31 个中日韩/全角标点（`，。、；：？！…—～·「」『』（）【】《》〈〉“”‘’｡､｢｣`）断言全部通过，防止把禁用集开得过大 |
| `validate_ip_port` | `192.168.3.127:10101` 通过；纯 `192.168.3.127` 通过（消费端补 `:5555`）；`host:70000` / `host:abc` / 空串各自返回对应错误 |
| `validate_file` | 存在/不存在/目录当文件/后缀不符 |
| `dynamic_table_replace` | 增删 `additional_special_apps` 项后，表头/表头注释/表尾注释/未触及项的**行尾注释**全部仍在，且行数只增减 1 |
| `array_prefix_normalized` | 删除 `enter_apps` 首元素后输出 `[["hexin.exe", 0.5]]`（无多余空格）；重建后与原文逐字符相同 |
| `config_location_precedence` | 命令行参数 > exe 同目录 > cwd；三者都无时返回 `NotFound` 且**不创建**文件 |
| `empty_string_list_roundtrip` | `disable_exe_list = [""]` 读入为空列表显示，原样保存后文本仍是 `[""]`，不做 `[]` |
| `dynamic_table_key_case_preserved` | 动态表键 `VLC.exe` 保存后仍是 `VLC.exe`，不被小写化 |
| `numeric_out_of_range_warns_only` | 把 `client.mic_seg_duration` 手工改成 `120`（超 60）后打开，字段标黄但仍可保存，保存后回读仍是 `120` |
| `numeric_range_applied_on_edit` | 承接上例，用户把该字段改值后新值落在 min/max 内（控件夹取），不会被写成 120 以外的越界值 |

**黄金测试**：遍历 `schema_paths.json` 全部 162 个 segments → 各写一个类型正确的探针值 → 重新解析 → 断言「只有被写键变化」「注释与顺序无损」「每个值回读等于写入值」。这是防回归的核心。

### 10.2 覆盖测试

- `schema_paths.json` 的 segments 集合 == `configs/default config.toml` 的叶子 segments 集合（双向相等）。
- 前端 vitest：schema 导出的 segments 集合 == `schema_paths.json`。

### 10.3 前端测试（`vitest`）

| 测试 | 断言 |
|---|---|
| `dirty_tracking` | 改字段后 dirty 含该 path，改回后不含 |
| `revert_all` | 「放弃」后 current == original，dirty 为空 |
| `revert_field` | 单字段恢复默认只改该字段 |
| `visibleWhen` | `use_online_translate_function=false` 时在线翻译字段不渲染 |
| `error_aggregation` | 3 个字段非法时返回 3 条错误 |
| `pair_list_roundtrip` | `enter_apps` 表格编辑后序列化为 `[["exe", 0.5]]` |

### 10.4 手工验收

1. `pnpm tauri build` 产出单文件 `edit_config_gui.exe`。
2. 双击打开真实 `config.toml`，确认 162 个键全部可见（13 页逐页点）。
3. 改 `client.speech_recognition_shortcut` 为 `ctrl + alt + f5`（录制），改 `enter_apps` 加一行，改一套提示词。
4. 预览 diff，确认只含改动的 3 处，且注释行未变。
5. 保存，`git diff config.toml` 确认只变这 3 处，注释与空行原样。
6. 撤销：重新打开，改回原值。
7. 并发：打开编辑器后在外部改 `config.toml`，再保存 → 必须提示冲突。
8. 未保存关闭 → 必须拦截。

---

## 11. 迁移与清理

### 11.1 删除

```
edit_config_gui.py                              (删除，入口)
util/edit_config_gui/                           (整目录删除，14 个 .py + __pycache__)
  about_page.py  clearly_type.py  client_config_page.py  deeplx_config_page.py
  funasr_args_config_page.py  libretranslate_config_page.py  model_paths_config_page.py
  paraformer_args_config_page.py  select_path.py  sensevoice_args_config_page.py
  server_config_page.py  set_default_button.py  value_check.py  write_toml.py
```

### 11.2 保留

- `pyproject.toml` 中 `pyside6` 依赖**保留**：`config_selector.py`、`start_server_gui.py`、`start_client_gui.py` 仍在使用。本次不迁移这三个程序。
- `tomlkit` 依赖保留（其他代码可能使用）。
- `assets/icon/config-icon.ico` 保留并复用。

### 11.3 产物替换

`edit_config_gui.exe`（仓库根，280 064 字节，当前是 PyStand 打包的旧 GUI）由新的 Tauri 产物替换。旧 exe 在构建成功后删除并提交新的。

### 11.4 文档

`readme.md` 需要改 4 处（行号为当前文件实测）：

| 行 | 现有内容 | 改为 |
|---|---|---|
| 8 | 「可方便修改**大部分**配置，更多自定义配置仍需手动修改 `config.toml` 文件」 | 「可修改 `config.toml` 全部配置项」——覆盖已完整，这句免责说明不再成立 |
| 190 | QQ音乐等「可通过 edit_config_gui.exe 配置 用于 播放/暂停 的快捷键」 | 保留（仍准确），可补「留空则不暂停」 |
| 406 | 「调试配置编辑器 GUI（edit_config_gui.py）另需手动下载 `siui` … 放在 `.venv/Lib/site-packages`」 | **删除整行**。新编辑器是 Rust + Svelte，不需要 siui，也不需要 `.venv` |
| 442-446 | 「启动配置编辑器GUI / `uv run edit_config_gui.py`」 | 改为「双击 `edit_config_gui.exe`」；若需从源码构建，补构建指令（见 §11.5） |

### 11.5 构建说明

新增 `edit_config_gui/README.md`，只写开发者需要的东西：`pnpm install`、`pnpm tauri dev`、`pnpm tauri build`、产物路径 `edit_config_gui/src-tauri/target/release/edit_config_gui.exe`、以及拷回仓库根的步骤。`pnpm tauri build` 的产物在 `src-tauri/target/release/` 下，**不是**仓库根，需要复制。这一步要在 `package.json` 里做成 `pnpm build:dist` 脚本，避免每次手动拷。

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **CRLF 文件被 `toml_edit` 重排成混合换行** | 整个 `config.toml` 的换行风格被污染（实测 852 个 CRLF → 199 CRLF + 653 裸 LF），git diff 变成全文改动 | 强制「LF 归一化 → 编辑 → CRLF 还原」三步（§7.4 结论 2）；`cargo test` 断言输出的 `\r\n` 计数 == `\n` 计数 |
| `toml_edit` 升级后静默改变格式 | 注释/顺序被破坏而无人发现 | 不修改场景的字节相等守卫测试 + 逐键黄金测试（§7.4 判据、§10.1） |
| 单行键被写入含换行的值 | 单行配置自动升格为 `"""` 多行块，行数暴增 | 按控件类型拦截：仅 8 个 `longText`（提示词）允许 `\n`，其余校验阶段拒绝（§7.4 结论 4） |
| 动态表整表重建丢行尾注释 | 用户没删的注释消失（实测 `Table::clear()` 会丢掉 `# VLC … 才能生效`） | 逐项 `insert`/`remove`，禁止整表重建（§9.5）；专项测试 `dynamic_table_replace` |
| 数组删除首元素产生多余空格 | 输出 `[ ["a", 0.5]]` 而非 `[["a", 0.5]]` | 删除后对新的首元素 `decor_mut().set_prefix("")`，追加时 `set_prefix(" ")`（§7.4 结论 6） |
| 用 `std::fs::rename` 做原子替换 | 会把 `.tmp` 的 ACL 带到 `config.toml`，静默清掉用户设过的特殊权限（实测 SDDL 不等） | 用 `ReplaceFileW`，实测保留目标 ACL 与备份 ACL（§7.2） |
| 「不备份」误传空字符串 | `ReplaceFileW` 返回 0 直接失败（`ERROR_PATH_NOT_FOUND`），保存功能在无备份场景下全挂 | 传 `NULL` 而非 `""`；专项测试 `replace_null_backup_ok`（§7.2） |
| 快捷键表与 Python 行为漂移 | 校验放行/拒绝与旧版不同 | 导出 `keyboard` 真实 `from_name`(205) + `canonical_names`(1171) 两张表；**已做 841 例对拍，差异 0 处**（§8.1.1）；`hotkey_parity` 用例固化该对拍集 |
| Tauri 打包体积/首次构建时长 | 构建慢 | 实测已能编译；使用 `pnpm add -D @tauri-apps/cli` 本地 CLI |
| 路径校验误伤（模型未下载） | 用户无法保存 | `model_paths.*` 只警告不阻断 |
| 动态表键名含点导致路径歧义 | 写错键 | 一律用 `segments` 数组定位 |
| 非 ASCII 键（`多音字`/`声调`） | 编辑失败 | `toml_edit` 原生支持 UTF-8 键；纳入黄金测试 |
| 用户误以为派生键可改 | 改了没效果 | 只读展示 + 跳转到真实来源 |
| `client.trash_punc` 被写入正则元字符 | `util/client/strip_punc.py:22` 把该值原样拼进字符类，`\` / `^` / 空串使 Python 抛 `re.error` 直接崩溃，`[` 则静默失效 | 新增 `regexClass` 校验器禁用 `\` `^` `[` 并禁空（§8.0.1）；`validate_regex_class` 用例固化，且断言 31 个中日韩标点仍可用 |
| `client.adb_addr` 写错格式 | 消费端 `adb_control.py:341-349` 不校验，只表现为「连接手机失败」，用户无从判断 | 新增 `ipPort` 校验器（§8.0.1）；`enable_adb_control=false` 时隐藏且不校验 |

---

## 13. 验收标准

1. 新编辑器可见并可编辑 `config.toml` 全部 162 个叶子键（9 个派生键为只读展示 + 跳转）。
2. 任意单行键改动保存后，`config.toml` 行数不变、只有该 1 行不同；注释行数（306）、键顺序、空行、行尾注释全部保留；全文换行符仍纯 CRLF（无裸 LF）。
3. 每个键写入后，TOML 值类型不变（字符串仍字符串，整数仍整数，浮点仍浮点）。
4. 保存流程包含：全量校验 → diff 预览 → 用户确认 → 备份 → 原子替换 → 回读校验。
5. 外部修改 `config.toml` 后保存被拒绝并提示。
6. 4 个暂停快捷键允许为空；空值保存后回读仍为空。
7. `client.addr` 接受任意合法 IPv4（含公网），非法格式拒绝且不覆写用户输入。
8. 服务端/客户端运行状态正确显示（认 `python_CapsWriter_Server.exe` 等真实进程名，大小写不敏感、`.exe` 可省）。
9. `restart_service` 只接受 `Server`/`Client` 枚举，无法被用来启动任意程序；服务端重启在管理员身份下走 explorer 令牌降权（需管理员会话手工验证一次）。
10. 旧 `edit_config_gui.py` 与 `util/edit_config_gui/` 已删除，仓库内不再有该 GUI 的 PySide6 代码。
11. `readme.md` 的 4 处更新已完成，其中 siui 那行已删除。
12. `cargo test` 与 `pnpm test` 全绿。
13. `pnpm tauri build` 产出可双击运行的 `edit_config_gui.exe`。
14. `config.toml` 按「命令行参数 > exe 同目录 > cwd」顺序定位；都找不到时打开引导态，**不创建**新文件。
15. `disable_exe_list` / `disable_exe_list_on_focus` 的 `[""]` 占位读入显示为「暂未添加」，保存后仍写回 `[""]`。
16. 动态表进程名保存时保留用户输入的大小写（只有去重比较不区分大小写）。
17. 从任意工作目录启动编辑器并点「重启服务端」，服务端能正确读到仓库根的模型与 `config.toml`（验证 §9.4 的 `lpCurrentDirectory`）。
18. `client.trash_punc` 写 `\` / `^` / `[` / 空串都被校验拦下并给出提示；模板值 `，。,.` 原样保存后，`util/client/strip_punc.py` 的行为与改动前一致（注释与值均未被 `toml_edit` 改写）。
19. `client.enable_adb_control=false` 时 `adb_addr` 隐藏且不参与全量校验；置 `true` 后填入 `192.168.3.127:10101` 可通过保存。

---

## 14. 未决事项

无。本规格所有决策均已定案。若评审提出变更，在评审意见中记录并更新本文档。
