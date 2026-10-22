# Qwen3-CTC 头的「语言串味」问题排查

> 排查日期：2026-10-22
> 现象：英文音频转写时，英文单词被替换成对应的**中文译文**
> （例如 `we` → `我们`、`or` → `或`、`intro to` → `intro 到`、`thank` → `谢谢`）
> 复现素材：`P1-女孩要勇敢而不必完美.mp4`（TED 演讲，全英文，763 s）

## 结论

**不是解码 bug，也不是音频问题，是 `aiinfra4` 这个 CTC 头的权重行为。**

`models/qwen-ctc-aiinfra4/` 里的 CTC 头（v2，`global_step 339707`）是在
「AI-infra 中英混读语料」上续训的。上游对该轮次语料的描述是：

> `aiinfra`：在 v1-ja-sc 之上再续训一轮 **AI-infra 中英混读语料**（372 h / 545 个视频）
> —— [bench-asr-ctc/bench/models.py](https://github.com/JazerJu/bench-asr-ctc) `QwenAiinfraEngine`

该语料是**中英对照字幕**，于是 CTC 头学到了「英文语音 → 中文字幕」这层映射。
遇到 AI 技术领域的英文内容（恰好 TED 这段讲的就是编程与计算机科学）时，
这层映射就会被触发，把英文词替换成中文对应词。

## 证据链

| # | 验证方式 | 结果 | 排除了什么 |
|---|---|---|---|
| 1 | 引擎层直接解码（绕开服务端） | 中文是 **CTC 头的原始输出** | 服务端后处理（标点/数字归一化/拼接） |
| 2 | 换用**上游 bench-asr-ctc 原版** `QwenEngine` 代码跑同一段音频 | **输出完全相同的中文** | 本仓库的解码实现差异 |
| 3 | 换用**独立引擎 SenseVoice** 转同一段音频 | **纯英文，0 汉字** | 音频里含中文人声 / 中文旁白 |
| 4 | 同一编码器 + 同一 `tokens.txt`，**只换 CTC 头** | v1 头 → 干净英文；v2 头 → 中文译文 | 编码器、`tokens.txt`、特征提取 |

第 4 条是决定性的：其余条件完全相同，只有头不同，行为不同。

## 影响面

整段 TED（763 s，切成 25 个 30 s 片段）：

| CTC 头 | 含中文的片段 | 汉字占比 | 最坏片段 |
|---|---|---|---|
| v1 `Qwen3-ASR-CTC.v1.fp16.onnx` | **0 / 25** | **0.00 %** | — |
| v2 `Qwen3-ASR-CTC.fp16.onnx`（aiinfra4） | **10 / 25** | 0.57 % | t=570s，16/104 字符是中文 |

污染**不是全局的**，只出现在特定片段：

- 通用英语（`models/sherpa-onnx-sense-voice-.../test_wavs/en.wav`）→ v2 头输出 0 汉字，正常
- 中文音频 → v2 头正常
- 中英混合（`zh_en_hotword_cw` / `zh_en_mlsys`）→ v2 头正常
- **AI 技术领域的英文内容 → v2 头出现译文**（本例）

所以这是**领域偏置**，不是语言识别错误。

## 可选的处理方式

### 方式 A：换用 v1 头（推荐）

`v1` 头与编码器同目录托管在 HF 上：
`JazerJu/glm-asr-ctc-bench` 的 `qwen-ctc/Qwen3-ASR-CTC.fp16.onnx`（96.8 MB）。

已下载并放到 `models/qwen-ctc-aiinfra4/Qwen3-ASR-CTC.v1.fp16.onnx`
（`.onnx` 已在 `.gitignore` 中，不会入库）。

切换只需改一行 `config.toml`：

```toml
[model_paths]
qwen_ctc_ctc_path = "models/qwen-ctc-aiinfra4/Qwen3-ASR-CTC.v1.fp16.onnx"
```

代价：

| 项 | v1 | v2 (aiinfra4) |
|---|---|---|
| 英文 AI 领域 | 干净 | 出现译文 |
| 中文数字写法 | 汉字（"二零二六年"） | 阿拉伯数字（"2026年"） |
| 上游 AISHELL-1 CER | 5.31 % | 5.53 % |
| 单段 30 s 耗时（CPU） | 1.35 s | 2.04 s |
| 上游 LibriSpeech test-clean WER | 6.93 % | 6.53 % |

即：v1 英文更干净，中文略差一点、略慢。

### 方式 B：保留 v2 头 + 后处理过滤

**不推荐**。无法可靠区分「英文被误译成中文」与「真中文语音被正确转写」，
后处理会误删正常中文内容。

### 方式 C：两个头都装，配置可切换

两个头都放进 `models/`，在 `[qwen_ctc_args]` 增加一个头文件选项。
最灵活，但要多占 96.8 MB 磁盘。

## 诊断工具

`dev/qwen_ctc_lang_check.py` —— 排查同类问题时可直接复用：

```bash
# 抽音频（任意格式 -> 16k 单声道 wav）
ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 out.wav

# 扫描整段音频，统计每个 30s 片段的中文占比
.venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav

# 对比两个 CTC 头（验证是否与头有关）
.venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav --heads v1 v2

# 打印「英文里夹中文」的具体位置
.venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav --spot

# 用独立引擎（SenseVoice）交叉验证音频里到底有没有中文人声
.venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav --cross-check
```

示例输出（`--spot`）：

```
  --- t=420s  han=4/329 ---
      …othing at all perfection[或] it turns out that our g…
      …g but not enough just to[他们] to code my friend loved…
      … ofolumbia teaches intro[到] java tells me about off…
```

## 参考

- 上游推理代码：[JazerJu/bench-asr-ctc](https://github.com/JazerJu/bench-asr-ctc)（`bench/models.py`）
- 权重仓库：[JazerJu/glm-asr-ctc-bench](https://huggingface.co/JazerJu/glm-asr-ctc-bench)
  - `qwen-ctc/`：编码器 + **v1** CTC 头 + `tokens.txt` + `preprocessor_config.json`
  - `qwen-ctc-aiinfra4/`：**v2** CTC 头（q4 / q4f16 / fp16）+ `config.json`
- 导出管线：[JazerJu/Qwen3-ASR-CTC-GGUF](https://github.com/JazerJu/Qwen3-ASR-CTC-GGUF)
