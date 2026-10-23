# 第三方许可原文（Third-Party License Texts）

本目录收录本项目**随包分发**的第三方组件所需的许可协议原文。各组件的具体归属、版本与用途见 [docs/开源许可.md](../docs/开源许可.md)。

## 文件索引

| 文件 | SPDX 标识 | 适用组件 |
| --- | --- | --- |
| [NOTICE.txt](NOTICE.txt) | —（归属登记） | **先看这里**。登记「许可正文必须逐字保留、版权行不能写进许可文件」的组件：`ffmpeg.exe` / `ffplay.exe`（GPL-2.0-or-later）、`hint_while_recording.exe`（内嵌 AHK 解释器，GPL-2.0）、`util/ahk/*.ahk`（AGPL-3.0 与一份未声明许可） |
| [MIT.txt](MIT.txt) | `MIT` | **含完整版权声明**（不只是条款正文）。覆盖：本项目自身（见根目录 `LICENSE`）、PyStand（`Copyright (c) 2022 Linwei`，嵌在 `start_*_gui.exe` / `config_selector.exe` 里）、ggml/llama.cpp（`Copyright (c) 2023-2026 The ggml authors`，两个 `bin/` 下的 30 个 DLL）、DeepLX（`Copyright (c) 2022 OwO Network Limited`）。`site-packages/` 里的 37 个 MIT 发行版各自在 `*.dist-info/LICENSE*` 内自带许可，不在此重复 |
| [Apache-2.0.txt](Apache-2.0.txt) | `Apache-2.0` | sherpa-onnx、transformers、openai、sentencepiece、huggingface_hub、tokenizers、safetensors、opencc-python-reimplemented、watchdog、requests、flatbuffers、Tauri 系 crate、m3-svelte |
| [BSD-2-Clause.txt](BSD-2-Clause.txt) | `BSD-2-Clause` | numba（Python，自带许可）；entities、webidl-conversions（npm，编进 `edit_config_gui.exe`，**版权行已补进本文件**） |
| [BSD-3-Clause.txt](BSD-3-Clause.txt) | `BSD-3-Clause` | Flask、Werkzeug、Jinja2、MarkupSafe、itsdangerous、click、colorama、httpx、websockets、numpy、sympy、psutil、protobuf、networkx、joblib、Pygments、fsspec、idna、pycparser（Python，各自在 `*.dist-info/licenses/` 内自带许可）；source-map-js、tough-cookie（npm）与 brotli / brotli-decompressor / alloc-no-stdlib / alloc-stdlib / num_enum / num_enum_derive（Rust）编进 `edit_config_gui.exe`，**版权行已补进本文件** |
| [MPL-2.0.txt](MPL-2.0.txt) | `MPL-2.0` | **certifi**、**clipman**、tqdm（前端另有 lightningcss）、Rust 侧 cssparser / cssparser-macros / dtoa-short / option-ext / selectors |
| [LGPL-3.0.txt](LGPL-3.0.txt) | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | **PySide6**、PySide6_Essentials、PySide6_Addons、PySide6_Pdf、PySide6_WebEngine、shiboken6 |
| [GPL-2.0.txt](GPL-2.0.txt) | `GPL-2.0-or-later` | **`ffmpeg.exe`、`ffplay.exe`**（以 `--enable-gpl --enable-libmp3lame` 构建） |
| [AGPL-3.0.txt](AGPL-3.0.txt) | `AGPL-3.0` | **`util/ahk/GetCaretPosEx.ahk`、`util/ahk/app-list.ahk`**（派生自 [abgox/InputTip](https://github.com/abgox/InputTip)，Copyright (C) 2023-present abgox） |
| [PSF-2.0.txt](PSF-2.0.txt) | `PSF-2.0` | 嵌入式 CPython 3.14.8（`runtime/`）、pywin32、typing_extensions |
| [Unicode-3.0.txt](Unicode-3.0.txt) | `Unicode-3.0` | Rust 侧 icu4x 系列、unicode-ident、zerovec 等 18 个 crate |
| [CC-BY-4.0.txt](CC-BY-4.0.txt) | `CC-BY-4.0` | 离线中译英模型 `models/Helsinki-NLP--opus-mt-zh-en/`（需署名 Helsinki-NLP / OPUS-MT / Tatoeba） |
| [../assets/fonts/LICENSE.txt](../assets/fonts/LICENSE.txt) | `OFL-1.1` | **`assets/fonts/MapleMono-NF-CN-Regular.ttf`**（Maple Mono NF CN 7.900，Copyright 2022 The Maple Mono Project Authors）。**该许可原文不复制到本目录**：OFL-1.1 §2 要求每份字体副本都自带版权声明与许可，因此它与字体二进制放在同一目录随包分发，详见 [docs/开源许可.md §9](../docs/开源许可.md) |
| [LLVM-exception.txt](LLVM-exception.txt) | `Apache-2.0 WITH LLVM-exception` | `util/fun_asr_gguf/bin/libomp.dll`、`util/qwen_ctc/bin/libomp.dll`（LLVM OpenMP 运行时） |
| [Zlib.txt](Zlib.txt) | `Zlib` | Rust 侧 adler2、miniz_oxide 等 |
| [CC0-1.0.txt](CC0-1.0.txt) | `CC0-1.0` | mdn-data；numpy / torch 的许可组合之一；tinyvec |
| [MIT-0.txt](MIT-0.txt) | `MIT-0` | @csstools/color-helpers、@csstools/css-syntax-patches-for-csstree |
| [ISC.txt](ISC.txt) | `ISC` | shellingham（Python，自带许可）；picocolors、saxes（npm，编进 `edit_config_gui.exe`，**版权行已补进本文件**） |
| [Unlicense.txt](Unlicense.txt) | `Unlicense` | filelock、Rust 侧 aho-corasick 等 |
| [0BSD.txt](0BSD.txt) | `0BSD` | adler2（`0BSD OR MIT OR Apache-2.0`）、numpy 许可组合之一 |
| [BSL-1.0.txt](BSL-1.0.txt) | `BSL-1.0` | torch 的许可组合之一 |
| [CNRI-Python.txt](CNRI-Python.txt) | `CNRI-Python` | regex（`Apache-2.0 AND CNRI-Python`） |
| [BlueOak-1.0.0.txt](BlueOak-1.0.0.txt) | `BlueOak-1.0.0` | lru-cache（前端传递依赖） |

## 使用说明

1. **再分发**本项目发布包时，请保持本目录原样随包附带，不要删除或修改这些文件。
2. 若替换了某个组件（例如自行编译 PySide6 或改用 `--disable-gpl` 构建 FFmpeg），请同步更新本目录与 [docs/开源许可.md](../docs/开源许可.md)。
3. `FFmpeg` / `FFplay` 的**对应源代码**获取方式：见 [readme.md](../readme.md) 的「FFmpeg & FFplay」章节（含完整 `./configure` 参数），或访问 <https://ffmpeg.org/download.html>。
4. 各许可原文均取自官方或 SPDX 权威来源，**条款正文**未做任何实质性修改；`LLVM-exception.txt` 仅截取了例外条款部分，其正文引用的 Apache-2.0 全文见本目录 `Apache-2.0.txt`。
5. **`MIT.txt`、`BSD-2-Clause.txt`、`BSD-3-Clause.txt`、`ISC.txt` 这四份在条款正文之外补写了版权声明**，其余文件仍是纯条款正文。原因：这四类许可都要求「在副本中附上版权声明与许可」，而本包随包分发的 PyStand 启动器、llama.cpp 的 DLL、`deeplx_windows_amd64.exe`，以及编进 `edit_config_gui.exe` 的 npm / Rust 依赖，**都不带自己的 `LICENSE` 文件**；只附一份写着 `<year> <owner>` 占位符的通用模板等于没有履行该义务。补写的内容只有版权行与来源 URL，**条款正文一字未改**。Python 包不在此列 —— 它们的 `*.dist-info/licenses/` 里已经自带真实版权行，重复一遍只会带来维护负担。四条 MIT 版权行的出处见 [docs/开源许可.md](../docs/开源许可.md) §3、§7、§8，BSD / ISC 的见 §5、§6。
6. **GPL / AGPL 组件的版权行不能写进许可文件**（那两个许可要求正文逐字保留），统一登记在 [NOTICE.txt](NOTICE.txt)：`ffmpeg.exe`、`ffplay.exe`、`hint_while_recording.exe`、`util/ahk/*.ahk`。
7. `alloc-stdlib` 与 `saxes` 的上游发布包里没有 `LICENSE` 文件，本目录只能登记它们的许可标识与已知版权方（`alloc-stdlib` 见 `BSD-3-Clause.txt` 中的说明，`saxes` 上游写的是 `Copyright (c) Contributors`），无法补出更具体的版权行。
