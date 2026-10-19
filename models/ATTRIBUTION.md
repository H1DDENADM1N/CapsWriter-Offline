# 模型署名与许可证（Model Attribution）

本项目使用的离线 AI 模型权重**不随源码仓库分发**，需按 [模型下载方式.txt](模型下载方式.txt) 单独下载；但**发布整合包时会一并分发**，故在此声明来源与许可。

各模型的完整说明见 [docs/开源许可.md](../docs/开源许可.md) 第 9 节。

---

## 1. SenseVoice 语音识别模型

- **目录**：`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/`
- **上游**：[iic/SenseVoiceSmall](https://www.modelscope.cn/models/iic/SenseVoiceSmall)（阿里巴巴达摩院 FunAudioLLM）
- **转换导出**：[k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) releases
- **许可证**：**Apache-2.0**
- **支持语言**：中文、粤语、英语、日语、韩语

## 2. Paraformer 中文语音识别模型

- **目录**：`paraformer-offline-zh/`
- **上游**：[iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx](https://www.modelscope.cn/models/iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx)
- **分发**：[yiyu-earth/sherpa-onnx-paraformer-zh-2024-04-25](https://huggingface.co/yiyu-earth/sherpa-onnx-paraformer-zh-2024-04-25)
- **许可证**：**Apache-2.0**

## 3. 标点恢复模型

- **目录**：`sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12/`
- **上游**：[iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch](https://www.modelscope.cn/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch)
- **分发**：[csukuangfj](https://www.modelscope.cn/models/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12)（经 sherpa-onnx 导出）
- **许可证**：**Apache-2.0**

## 4. Fun-ASR-Nano 语音识别模型（GGUF）

- **目录**：`Fun-ASR-Nano-GGUF-2026-02-09/`
- **上游权重**：[FunAudioLLM/Fun-ASR-Nano-2512](https://www.modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512)（阿里巴巴达摩院 FunAudioLLM）
- **GGUF 转换与推理实现**：[HaujetZhao/Fun-ASR-GGUF](https://github.com/HaujetZhao/Fun-ASR-GGUF)（**MIT**）
- **上游模型许可**：ModelScope 未标注 SPDX，适用 **[FunASR Model Open Source License Agreement v1.1](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)**（Copyright (C) 2023-2028 Alibaba Group）

### FunASR 模型协议要点（v1.1）

- 允许自由使用、复制、修改、分享模型权重及其衍生（含微调模型）。
- **必须**在使用、复制、修改、分享时**标注来源与作者信息**，并**保留模型名称**。
- 不得进行无端贬损、恶意抹黑或人身攻击，否则视为自动放弃本协议下全部许可。
- 违反条款则许可自动终止，须停止使用并销毁副本。
- 免责：模型仅用于参考与学习，阿里集团不承担任何直接或间接损失。

> 因此分发时必须保留 `model.int8.onnx` / `*.gguf` 等原始文件名与模型卡名称，并在文档中注明「模型来自阿里巴巴达摩院 FunAudioLLM / ModelScope iic 系列」。

## 5. 中译英离线翻译模型（CC-BY-4.0，需署名）

- **目录**：`Helsinki-NLP--opus-mt-zh-en/`
- **上游**：[Helsinki-NLP/opus-mt-zh-en](https://huggingface.co/Helsinki-NLP/opus-mt-zh-en)（Helsinki-NLP 团队）
- **原始权重**：[OPUS-MT zho-eng opus-2020-07-17.zip](https://object.pouta.csc.fi/Tatoeba-MT-models/zho-eng/opus-2020-07-17.zip)
- **训练语料**：[OPUS](https://opus.nlpl.eu/) 与 [Tatoeba](https://tatoeba.org/) 平行语料
- **许可证**：**CC-BY-4.0**（[许可全文](../LICENSES/CC-BY-4.0.txt) / [官方页面](https://creativecommons.org/licenses/by/4.0/)）

### 署名声明（CC-BY-4.0 §3(a)）

> 本模型由 **Helsinki-NLP** 团队基于 **OPUS-MT** 项目训练，训练数据来自 **OPUS** 与 **Tatoeba** 平行语料库。
> 原始模型：<https://huggingface.co/Helsinki-NLP/opus-mt-zh-en>
> 以 **Creative Commons Attribution 4.0 International (CC-BY-4.0)** 许可发布。
> 本项目未对模型权重做任何修改，仅原样打包分发。
> 许可证全文：<https://creativecommons.org/licenses/by/4.0/legalcode>

---

## 汇总表

| 模型目录 | 许可证 | 是否需署名 | 许可全文 |
| --- | --- | --- | --- |
| `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | Apache-2.0 | 需保留版权与许可声明 | [Apache-2.0.txt](../LICENSES/Apache-2.0.txt) |
| `paraformer-offline-zh` | Apache-2.0 | 需保留版权与许可声明 | [Apache-2.0.txt](../LICENSES/Apache-2.0.txt) |
| `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12` | Apache-2.0 | 需保留版权与许可声明 | [Apache-2.0.txt](../LICENSES/Apache-2.0.txt) |
| `Fun-ASR-Nano-GGUF-2026-02-09` | FunASR 模型协议 v1.1 | **必须**标注来源并保留模型名称 | [MODEL_LICENSE](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE) |
| `Helsinki-NLP--opus-mt-zh-en` | **CC-BY-4.0** | **必须**署名 Helsinki-NLP / OPUS-MT / Tatoeba | [CC-BY-4.0.txt](../LICENSES/CC-BY-4.0.txt) |
