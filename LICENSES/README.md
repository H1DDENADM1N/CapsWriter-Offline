# 第三方许可原文（Third-Party License Texts）

本目录收录本项目**随包分发**的第三方组件所需的许可协议原文。各组件的具体归属、版本与用途见 [docs/开源许可.md](../docs/开源许可.md)。

## 文件索引

| 文件 | SPDX 标识 | 适用组件 |
| --- | --- | --- |
| [MIT.txt](MIT.txt) | `MIT` | 本项目自身（见根目录 `LICENSE`）；PyStand、DeepLX、ggml/llama.cpp、pycaw、sounddevice、keyboard、jieba、pypinyin、rich、tomlkit、loguru、pydantic、typer、urllib3、setuptools 等 |
| [Apache-2.0.txt](Apache-2.0.txt) | `Apache-2.0` | sherpa-onnx、transformers、openai、sentencepiece、huggingface_hub、tokenizers、safetensors、opencc-python-reimplemented、watchdog、requests、flatbuffers、Tauri 系 crate、m3-svelte |
| [BSD-2-Clause.txt](BSD-2-Clause.txt) | `BSD-2-Clause` | numba、entities、webidl-conversions |
| [BSD-3-Clause.txt](BSD-3-Clause.txt) | `BSD-3-Clause` | Flask、Werkzeug、Jinja2、MarkupSafe、itsdangerous、click、colorama、httpx、websockets、numpy、sympy、psutil、protobuf、networkx、joblib、Pygments、fsspec、idna、pycparser、source-map-js、tough-cookie |
| [MPL-2.0.txt](MPL-2.0.txt) | `MPL-2.0` | **certifi**、**clipman**、tqdm（前端另有 lightningcss）、Rust 侧 cssparser / cssparser-macros / dtoa-short / option-ext / selectors |
| [LGPL-3.0.txt](LGPL-3.0.txt) | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | **PySide6**、PySide6_Essentials、PySide6_Addons、PySide6_Pdf、PySide6_WebEngine、shiboken6 |
| [GPL-2.0.txt](GPL-2.0.txt) | `GPL-2.0-or-later` | **`ffmpeg.exe`、`ffplay.exe`**（以 `--enable-gpl --enable-libmp3lame` 构建） |
| [AGPL-3.0.txt](AGPL-3.0.txt) | `AGPL-3.0` | **`util/ahk/GetCaretPosEx.ahk`、`util/ahk/app-list.ahk`**（派生自 [abgox/InputTip](https://github.com/abgox/InputTip)，Copyright (C) 2023-present abgox） |
| [PSF-2.0.txt](PSF-2.0.txt) | `PSF-2.0` | 嵌入式 CPython 3.14.8（`runtime/`）、pywin32、typing_extensions |
| [Unicode-3.0.txt](Unicode-3.0.txt) | `Unicode-3.0` | Rust 侧 icu4x 系列、unicode-ident、zerovec 等 18 个 crate |
| [CC-BY-4.0.txt](CC-BY-4.0.txt) | `CC-BY-4.0` | 离线中译英模型 `models/Helsinki-NLP--opus-mt-zh-en/`（需署名 Helsinki-NLP / OPUS-MT / Tatoeba） |
| [LLVM-exception.txt](LLVM-exception.txt) | `Apache-2.0 WITH LLVM-exception` | `util/fun_asr_gguf/bin/libomp.dll`（LLVM OpenMP 运行时） |
| [Zlib.txt](Zlib.txt) | `Zlib` | Rust 侧 adler2、miniz_oxide 等 |
| [CC0-1.0.txt](CC0-1.0.txt) | `CC0-1.0` | mdn-data；numpy / torch 的许可组合之一；tinyvec |
| [MIT-0.txt](MIT-0.txt) | `MIT-0` | @csstools/color-helpers、@csstools/css-syntax-patches-for-csstree |
| [ISC.txt](ISC.txt) | `ISC` | shellingham、picocolors、saxes |
| [Unlicense.txt](Unlicense.txt) | `Unlicense` | filelock、Rust 侧 aho-corasick 等 |
| [0BSD.txt](0BSD.txt) | `0BSD` | adler2（`0BSD OR MIT OR Apache-2.0`）、numpy 许可组合之一 |
| [BSL-1.0.txt](BSL-1.0.txt) | `BSL-1.0` | torch 的许可组合之一 |
| [CNRI-Python.txt](CNRI-Python.txt) | `CNRI-Python` | regex（`Apache-2.0 AND CNRI-Python`） |
| [BlueOak-1.0.0.txt](BlueOak-1.0.0.txt) | `BlueOak-1.0.0` | lru-cache（前端传递依赖） |

## 使用说明

1. **再分发**本项目发布包时，请保持本目录原样随包附带，不要删除或修改这些文件。
2. 若替换了某个组件（例如自行编译 PySide6 或改用 `--disable-gpl` 构建 FFmpeg），请同步更新本目录与 [docs/开源许可.md](../docs/开源许可.md)。
3. `FFmpeg` / `FFplay` 的**对应源代码**获取方式：见 [readme.md](../readme.md) 的「FFmpeg & FFplay」章节（含完整 `./configure` 参数），或访问 <https://ffmpeg.org/download.html>。
4. 各许可原文均取自官方或 SPDX 权威来源，未做任何实质性修改；`LLVM-exception.txt` 仅截取了例外条款部分，其正文引用的 Apache-2.0 全文见本目录 `Apache-2.0.txt`。
