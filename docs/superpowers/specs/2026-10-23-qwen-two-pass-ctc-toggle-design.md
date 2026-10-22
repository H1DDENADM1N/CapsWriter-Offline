# Qwen 两遍引擎 + CTC 开关 设计

- 日期：2026-10-23
- 分支：`dev/QwenCTC`
- 需求原文（用户）："优化服务端，增加可选项：使用Qwen模型时是否启用 CTC"
- 范围修订（用户，逐条确认）：完整两遍引擎；`enable_ctc` / `llm_n_ctx` / `llm_n_threads` / `llm_n_predict` 入配置；`model_paths.qwen_llm_path` 预填但允许留空（空 + `enable_ctc=true` = 纯 CTC）；0.6B 配套 encoder 本期实现；**全部代码放 `util/qwen_ctc/`，不修改也不调用 `util/fun_asr_gguf/` 任何内容**；CTC 改为尽力而为（best-effort），0.6B 不再报错。

---

## 1. 目标

1. 为 `model = "QwenCTC"` 增加完整两遍识别：**CTC 首遍**（字级时间戳）→ **Qwen3-ASR LLM 二遍**（文本质量）。
2. 新增开关 `[qwen_ctc_args] enable_ctc`，语义与上游 JazerJu 一致，且"没配解码器"时行为与今天**完全一致**。
3. 支持两种模型尺寸：
   - **1.7B**：融合 encoder（现有 `Qwen3-ASR-Encoder.q4.onnx`，输出 2048 维）+ 1.7B CTC 头 + 1.7B LLM 解码器。
   - **0.6B**：拆分 encoder（`frontend` 896 维 → `backend` 1024 维）+ 0.6B LLM 解码器（**无 CTC 头**）。
4. LLM 的上下文长度、线程数、最大生成 token 数可配置。
5. 零回归：老配置（无新键）→ 解码器路径为空 → 纯 CTC，行为、输出、性能均不变。

## 2. 非目标（YAGNI）

- 不做热词注入（Qwen 路径不接热词，CTC 首遍也不产热词候选）。
- 不修改 `util/fun_asr_gguf/` 下任何文件，**不从该包 import 任何东西**（含 `llama`、`gguf.quants`）。
- 不为 0.6B 训练/寻找 CTC 头（公开渠道不存在）；0.6B 无字级时间戳。
- 不做流式增量出字（仍按段返回整段结果）。
- 不做显存精细控制（沿用 llama.cpp 自动选后端：有 Vulkan 用 Vulkan，否则 CPU）。
- 不改 Paraformer / SenseVoice / FunASR 三条链路。

## 3. 现状

- `model = "QwenCTC"` 时走 `util/qwen_ctc/engine.py`：ONNX encoder → ONNX CTC 头 → 字级 token + 时间戳；无 LLM，无标点（靠 sherpa 标点模型补）。
- `util/server/init_recognizer.py:77-88` 用 `create_qwen_ctc_engine(**QwenCTCArgs.__dict__)` 构造；`util/server/recognize_qwen_ctc.py` 负责按段合并 token/时间戳并输出 `Result.text` / `Result.text_accu`。
- `util/config.py:295-307` 的 `QwenCTCArgs` 目前只有 4 个路径 + 8 个 CTC 参数，**没有** `enable_ctc`，也**没有** LLM 相关参数。

## 4. 模型资产

### 4.1 1.7B（已有，均在 `models/qwen-ctc-aiinfra4/`）

| 文件 | 大小 | 说明 |
|---|---|---|
| `Qwen3-ASR-Encoder.q4.onnx` | — | IN `input_features[128,3000]` + `feature_length[1] int64` → OUT `enc_output[390,2048]` |
| `Qwen3-ASR-CTC.v1.fp16.onnx` | — | IN `enc_output['batch','time',2048]` → OUT `logits['batch','time',72468]` |
| `tokens.txt` | — | base64 原始字节词表 |
| `preprocessor_config.json` | — | Whisper 特征提取器配置 |
| `qwen3_asr_llm.q4_k.gguf` | 1,282,434,624 B | **本期新增**，arch `qwen3vl`、embd 2048、28 层、`rope.dimension_sections=[24,20,20,0]`、311 张量 |

### 4.2 0.6B（本期新增，在 `models/qwen-ctc-aiinfra4-06b/`）

| 文件 | 大小 | 说明 |
|---|---|---|
| `qwen3_asr_encoder_frontend.int4.onnx` | 20,343,991 B | IN `chunk_mel[1,128,100]` → OUT `chunk_out[1,13,896]` |
| `qwen3_asr_encoder_backend.int4.onnx` | 94,750,816 B | IN `hidden_states['batch','time',896]` + `attention_mask['batch',1,'time','time']` → OUT `last_hidden_state['batch','time',1024]` |
| `qwen3_asr_llm.q4_k.gguf` | 484,215,360 B | arch `qwen3vl`、embd **1024**、28 层、同样 M-RoPE sections |

0.6B 复用 1.7B 目录下的 `preprocessor_config.json`（两者 mel 前端相同）。

### 4.3 下载命令（写入 `models/模型下载方式.txt` 与 readme）

```bash
# 1.7B 解码器
curl -4 -L -C - -o models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf \
  "https://modelscope.cn/models/luciacx/Qwen3-ASR-GGUF-1.7B-mixed/resolve/master/qwen3_asr_llm.q4_k.gguf"

# 0.6B 全套
mkdir -p models/qwen-ctc-aiinfra4-06b
for f in qwen3_asr_encoder_frontend.int4.onnx qwen3_asr_encoder_backend.int4.onnx qwen3_asr_llm.q4_k.gguf; do
  curl -4 -L -C - -o "models/qwen-ctc-aiinfra4-06b/$f" \
    "https://modelscope.cn/models/luciacx/Qwen3-ASR-GGUF-0.6B-mixed/resolve/master/$f"
done
```

### 4.4 许可

- encoder / CTC 头 / tokens：见现有 `models/ATTRIBUTION.md` §6。
- 解码器 GGUF 来自 HaujetZhao 的 Qwen3-ASR 转换产物（ModelScope 镜像 `luciacx`），底层模型 Apache-2.0；在 `models/ATTRIBUTION.md` 增补一行并在 `docs/开源许可.md` 注明。

## 5. 架构

### 5.1 模块划分（全部在 `util/qwen_ctc/`）

| 文件 | 状态 | 职责 |
|---|---|---|
| `llama_cpp.py` | 新增 | 自有 ctypes 绑定（只绑用到的子集）。ABI 对齐仓库内 llama.cpp 版本。负责 `util/qwen_ctc/bin/` 下 DLL 的加载与路径注册。 |
| `encoder.py` | 新增 | `FusedEncoder`（1.7B）与 `SplitEncoder`（0.6B）；共用 mel 特征与 `valid_frames()`。 |
| `llm.py` | 新增 | `QwenLLMDecoder`：ChatML 提示、4 平面 M-RoPE 位置注入、prefill、贪心生成、复读熔断、KV 清理、预热。 |
| `gguf_embed.py` | 新增 | 用 pip `gguf` + `gguf.quants` 按需取 `token_embd.weight` 行并反量化（LRU + 可选 `.npy` 缓存）。 |
| `align.py` | 新增 | `align_ctc_to_llm(ctc_chars, ctc_starts, llm_text, duration)`：NW 对齐，返回与 LLM 文本等长的时间戳列表。 |
| `engine.py` | 改造 | `QwenCTCConfig` 扩字段；`QwenCTCEngine` 保留 CTC 逻辑并新增可选 LLM 编排；`decode()` 按模式产出结果；新增 `mode` / `has_timestamps` 属性。 |
| `tokens.py` / `schema.py` | 不动 | — |
| `bin/` | 新增（gitignore） | llama.cpp 二进制；文档写"把 `util/fun_asr_gguf/bin` 整个复制到 `util/qwen_ctc/bin`"。 |

### 5.2 依赖边界

- 允许：`numpy`、`loguru`、`tomlkit`（间接）、`onnxruntime`、`transformers`（仅 `WhisperFeatureExtractor`）、`gguf`（`pyproject.toml` 的 `server` 组已声明 `gguf>=0.19.0`）。
- **禁止**：`import util.fun_asr_gguf.*`（任何子模块）。
- `util/qwen_ctc/bin/` 与 `/models/qwen-ctc-aiinfra4*/` 下的大文件加入 `.gitignore`。

### 5.3 加载顺序（硬约束）

1. 模块顶部（任何 torch/transformers 导入前）设 `os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"`（LLVM OpenMP 与 Intel OpenMP 共存兜底）。
2. `llama_cpp` 载入 DLL → `llama_backend_init()`。
3. 载入解码器 GGUF → 建 `LlamaContext`。
4. 建 ONNX encoder / CTC 会话。
5. 最后才 `from transformers import WhisperFeatureExtractor`（此时才拉入 torch）。
6. `initialize()` 末尾做一次**预热**（见 §9.9）。

## 6. 配置面

### 6.1 新增键（10 个叶子键）

```toml
[model_paths]
qwen_llm_path = "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"
# Qwen3-ASR LLM 解码器路径，留空则退回纯 CTC 模式

qwen_ctc_encoder_frontend_path = ""
# 0.6B 编码器前端路径，留空则用上面的融合编码器（1.7B）

qwen_ctc_encoder_backend_path = ""
# 0.6B 编码器后端路径，留空则用上面的融合编码器（1.7B）

[qwen_ctc_args]
decoder_gguf_path = "${model_paths.qwen_llm_path}"
# LLM 解码器路径（只读派生键）

encoder_frontend_path = "${model_paths.qwen_ctc_encoder_frontend_path}"
# 0.6B 编码器前端路径（只读派生键）

encoder_backend_path = "${model_paths.qwen_ctc_encoder_backend_path}"
# 0.6B 编码器后端路径（只读派生键）

enable_ctc = true
# 是否启用 CTC 首遍：开启后 CTC 负责时间戳，LLM 负责文本

llm_n_ctx = 4096
# LLM 上下文长度

llm_n_threads = 6
# LLM 推理线程数（与 ONNX 的 num_threads 分开）

llm_n_predict = 256
# LLM 单段最大生成 token 数
```

### 6.2 语义

- `qwen_llm_path` 为空 ⇒ 解码器不存在 ⇒ **纯 CTC**（1.7B 融合 encoder + CTC 头），与今天一致。
- `qwen_ctc_encoder_frontend_path` 与 `qwen_ctc_encoder_backend_path` **都非空** ⇒ 走 0.6B 拆分 encoder；**都为空** ⇒ 走融合 encoder（1.7B）；**只配一端 ⇒ 硬错误**（拆分 encoder 必须成对，缺一不可）。
- `enable_ctc` 只在"有解码器"时有意义（见 §7）。

### 6.3 `util/config.py` 读取规则

`QwenCTCArgs` 新增字段全部用 `.get()` + 默认值，保证老配置不炸：

```python
decoder_gguf_path       = config["model_paths"].get("qwen_llm_path", "")
encoder_frontend_path   = config["model_paths"].get("qwen_ctc_encoder_frontend_path", "")
encoder_backend_path    = config["model_paths"].get("qwen_ctc_encoder_backend_path", "")
enable_ctc              = config["qwen_ctc_args"].get("enable_ctc", True)
llm_n_ctx               = config["qwen_ctc_args"].get("llm_n_ctx", 4096)
llm_n_threads           = config["qwen_ctc_args"].get("llm_n_threads", 6)
llm_n_predict           = config["qwen_ctc_args"].get("llm_n_predict", 256)
```

## 7. 模式判定与降级

### 7.1 判定顺序（`initialize()` 内）

1. 读 encoder：两个 0.6B 路径都非空 → `SplitEncoder`；都为空 → `FusedEncoder`；**只配一端 → 抛异常**。
2. 读 decoder：`decoder_gguf_path` 非空且文件存在 → 加载 LLM。
3. CTC 头是否可用：CTC 头文件存在 **且** 其 ONNX 输入的最后一维 == encoder 输出维度 → 可用。

### 7.2 模式矩阵

| encoder | 解码器 | `enable_ctc` | CTC 头可用 | 模式 | 输出 |
|---|---|---|---|---|---|
| 融合 1.7B | 有 | true | 是 | **两遍** | text=LLM 文本；tokens=LLM 逐字符；timestamps=NW 对齐 |
| 融合 1.7B | 有 | true | 否 | 纯 LLM + WARNING | text=LLM 文本；tokens/timestamps 为空 |
| 融合 1.7B | 有 | false | — | **纯 LLM** | text=LLM 文本；tokens/timestamps 为空 |
| 融合 1.7B | 空 | true | 是 | **纯 CTC**（现状） | text/tokens/timestamps=CTC |
| 拆分 0.6B | 有 | true | 否（无 0.6B 头） | 纯 LLM + WARNING | text=LLM 文本；tokens/timestamps 为空 |
| 拆分 0.6B | 有 | false | — | **纯 LLM** | 同上 |
| 任意 | 空 | false | — | ✗ 硬错误 | 「既未配置解码器又禁用了 CTC，无推理路径」 |
| 拆分 0.6B | 空 | true | — | ✗ 硬错误 | 「0.6B 无 CTC 头，必须配置解码器」 |
| 任意 | 有 | — | — | ✗ 硬错误（若不匹配） | 「解码器维度 X ≠ 编码器输出维度 Y」 |
| 任意 | 空/有 | — | — | ✗ 硬错误（0.6B 只配一端） | 「0.6B 编码器前后端必须成对配置」 |

### 7.3 CTC best-effort 规则

`enable_ctc=true` 是**请求**而非**门槛**：CTC 头缺失、或维度不匹配（0.6B）时，**跳过 CTC 并在日志里打一条 WARNING**，继续按纯 LLM 运行。将来出现 1024 维 CTC 头，只要把 `qwen_ctc_ctc_path` 指过去即自动启用，无需改代码。

### 7.4 硬错误清单（`check_model` 阶段就要拦，或 `initialize()` 抛异常）

1. 需要的 encoder 文件不存在。
2. `qwen_llm_path` 非空但文件不存在。
3. 纯 CTC 模式下 CTC 头 / tokens 不存在。
4. 解码器 `n_embd` ≠ encoder 输出维度。
5. 纯 CTC 模式却只配了 0.6B 拆分 encoder。

### 7.5 引擎对外的两个属性

`QwenCTCEngine` 新增（`recognize_qwen_ctc.py` 只依赖这两个）：

- `mode: str` ∈ `{"ctc", "two_pass", "llm"}` —— 实际生效的模式（不是用户期望的模式；降级后如实反映）。
- `has_timestamps: bool` —— `mode in {"ctc", "two_pass"}`。

`create_stream()` / `decode_stream()` / `transcribe()` / `cleanup()` 的签名与语义保持不变，因此 `init_recognizer.py` 无需改结构。

## 8. 数据流

### 8.1 两遍（默认，1.7B）

```
accept_waveform
  └─ 30 s 切块（现有 decode() 逻辑）
       ├─ encoder.encode(chunk) → enc[T,2048]
       ├─ CTC 首遍  → chars[], starts[]                     ~30 ms
       ├─ LLM 二遍  → prefix_embd(14) + enc + suffix_embd(6)
       │              4 平面位置 → prefill ~20 ms → 贪心 ~10 ms/token
       └─ align(chars, starts, llm_text) → 逐字符时间戳
结果：text = text_accu = llm_text；tokens = list(llm_text)；timestamps = 对齐结果
```

### 8.2 纯 CTC（解码器未配）

完全走现有逻辑：`_ctc_ids → _collapse → _decode_kept`，逐块拼接（`time_offset = i*30.0`）。

### 8.3 纯 LLM

跳首遍，直接 LLM。结果 `tokens=[]`、`timestamps=[]`，服务端退回 `merge_by_text` 文本级拼接。

### 8.4 切块与偏移

沿用 `SEGMENT_SEC=30.0`，`time_offset = 段序号 * 30.0`；LLM 与 CTC 使用**同一块**的 encoder 输出，保证两者文本可比对。

## 9. 关键实现细节

### 9.1 mel 特征（两条 encoder 共用）

```python
feat = self._fe(audio, sampling_rate=16000, padding=False, return_tensors="np").input_features[0]
# 1.7B: 补零到 3000 帧，同时传 feature_length=真实帧数
# 0.6B: 不补零，直接按 100 帧切块
```

### 9.2 `valid_frames` 与 0.6B 拆分 encoder

```python
def valid_frames(mel_len: int) -> int:
    full, leave = divmod(mel_len, 100)
    return full * 13 + (0 if leave == 0 else (leave - 1) // 8 + 1)
```

0.6B：mel 按 100 帧一块（末块补零到 100）→ 逐块跑 `frontend`（`chunk_mel[1,128,100]` → `chunk_out[1,13,896]`）→ 拼接 → 截断到 `valid_frames(mel_len)` → `backend(hidden_states, attention_mask=ones[1,1,T,T])` → `last_hidden_state[T,1024]`。

实测（zh.wav，mel 559 帧）：6 块 → 78 帧 → 截断 73 帧；frontend 88 ms + backend 75 ms。

### 9.3 LLM 提示构造

```
prefix_ids = [IM_START] + tok("system\nYou are a helpful assistant.") + [IM_END]
           + [IM_START] + tok("user\n") + [AUDIO_START]
音频段     = encoder 输出 enc[T,dim]（直接当作嵌入）
suffix_ids = [AUDIO_END, IM_END, IM_START] + tok("assistant\n") + [ASR_TEXT]
```

特殊 token 用 `tokenize(literal, parse_special=True)` 解析并要求结果长度为 1；失败时回退到已知 id 表：
`151643 <|endoftext|>`、`151644 <|im_start|>`、`151645 <|im_end|>`、`151669 <|audio_start|>`、`151670 <|audio_end|>`、`151676 <|audio_pad|>`、`151704 <asr_text|>`。

**停止符**：`{<|im_end|>, <|endoftext|>}`。**不得**使用 GGUF 里的 eos 元数据作为唯一依据（上游 JazerJu 导出的 GGUF 里 eos 被错设成 id 11 逗号；本期用的文件 eos 是 151645，但仍以显式解析为准）。

### 9.4 4 平面 M-RoPE 位置注入

解码器 arch 是 `qwen3vl`，llama.cpp 把它映射成 `LLAMA_ROPE_TYPE_IMROPE`（`rope_type=40`，已实测）。embedding 批的位置必须按**段优先（section-major）**排布：

```python
n = total_tokens
pos4 = np.concatenate([np.arange(n), np.arange(n), np.arange(n), np.zeros(n)]).astype(np.int32)
batch = LlamaBatch(max(n * 4, 8192), n_embd, 1)   # pos 缓冲需 4n 容量
batch.set_embd(full_embd)                          # 先写嵌入
batch.struct.token = NULL                          # 强制走 embd-only 路径
ctypes.memmove(batch.pos, pos4.ctypes.data, pos4.nbytes)   # 再覆写 4n 个位置
```

原因：`llama_batch_init(n_tokens, ...)` 只为 `pos` 分配 `n_tokens` 个槽位，而 M-RoPE 的 embedding 批要读 `pos[j*n + i]`（j=0..3），所以容量必须放大 4 倍、且布局必须是段优先。

### 9.5 token embedding 按需反量化

`token_embd.weight` 是 Q4_K、形状 `[2048,151936]`（0.6B 为 `[1024,151936]`）。整表反量化成 f32 要 1.24 GB，**不可接受**；只对提示里出现的 token id 取行：

```python
t = next(x for x in gguf.GGUFReader(path).tensors if x.name == "token_embd.weight")
rows = Q4_K.dequantize(t.data[ids])   # 只反量化命中的行
```

提示里的 token id 是固定的（特殊符 + 少量系统/用户/助手词），首轮算好即可；配一个 LRU 缓存，可选落盘 `<gguf>.embd.npy`。

### 9.6 生成循环

```python
batch = llama_batch_get_one([next_id], 1)   # pos 由 llama.cpp 自动续接
ctx.decode(batch)
logits = llama_get_logits_ith(ctx, -1)      # 本步输出行
next_id = int(np.argmax(logits))
```

绑定注意：`llama_batch_get_one` 以**值返回** `llama_batch` 结构体，必须设 `restype = llama_batch`；`llama_get_logits_ith` 必须设 `restype = POINTER(c_float)` 且 `argtypes = [c_void_p, c_int32]`（`-1` 表示最后一行）。

达到 `llm_n_predict` 或命中停止符即停；文本 = 逐 token `token_to_bytes` 拼接后 UTF-8 解码（不逐 token 解码，避免 CJK 被拆坏）。

### 9.7 复读熔断

生成过程中若"最近 30 个 token 的不同值 ≤ 3"，判定为复读：清 KV、升温 +0.3 重试，最多 4 次；仍复读则采用最后一次结果。

### 9.8 NW 对齐

`align_ctc_to_llm(ctc_chars, ctc_starts, llm_text, duration)`：

- DP：match +1.0 / mismatch −1.0 / gap −1.0，大小写与全半角归一后比较。
- 回溯得到 LLM 每个字符对应的 CTC 字符下标 → 取其 `start`。
- 连续未匹配段用两侧锚点线性插值；整段无锚点时按字符数均分 `duration`。
- 返回值长度 **必须** 等于 `len(llm_text)`，保证 `tokens` 与 `timestamps` 一一对应（客户端字幕依赖这个不变式）。

### 9.9 预热

首次 prefill 有 ~2 s 的一次性开销（llama 图 reserve），第二次起仅 ~20 ms。`initialize()` 末尾用 1 帧静音跑一次完整 prefill + 1 token 生成，把这段开销挪到启动阶段。

### 9.10 LLM 参数取值与上限保护

| 参数 | 来源 | 用途 |
|---|---|---|
| `n_ctx` | `llm_n_ctx` | 上下文窗口 |
| `n_batch` | `min(llm_n_ctx, 2048)` | 单次 decode 的最大 token 数（预填 ~410 足够） |
| `n_ubatch` | `512` | 微批大小 |
| `n_threads` / `n_threads_batch` | `llm_n_threads` | llama 推理线程，**与 ONNX 的 `num_threads` 独立** |
| `n_predict` | `llm_n_predict` | 单段最大生成 token 数 |

容量核算：`n_prefill = len(prefix_ids) + T + len(suffix_ids)`（T ≤ 390）。若 `n_prefill + n_predict > n_ctx`，**把本次生成上限收紧为 `n_ctx - n_prefill`** 并打一条 WARNING，而不是让 llama.cpp 在满载时报错。`n_ctx < 512` 直接视为配置错误。

## 10. 服务端集成

### 10.1 `util/server/recognize_qwen_ctc.py`

```python
if recognizer.has_timestamps:      # 两遍 / 纯 CTC：有 tokens
    ...现有 token 合并逻辑不变...
else:                              # 纯 LLM：没有 tokens
    new_text = stream.result.text
    result.text = merge_by_text(result.text, new_text, overlap_chars=..., ...)
    result.text_accu = result.text
```

- `format_text()`：两遍模式与纯 LLM 模式**跳过** `punc_model.add_punctuation`（LLM 自带标点；实测重跑会产出「。」「。」与「gold .。」），`adjust_space` / `chinese_to_num` 保留；纯 CTC 模式保持现状。
- 需要从 `util.server.recognize_funasr` 引入 `merge_by_text`（已核实该模块只依赖 `util.config` / `util.constants` / `util.server.*`，**不 import `util.fun_asr_gguf`**，因此不违反 §5.2 的边界）。
- **两遍模式的失败回退**：某一段 LLM 生成抛异常时，日志记 error，该段改用 CTC 首遍文本与时间戳（而不是整段返回空），保证识别不中断；纯 LLM 模式没有可回退的文本，仍走现有 except 分支返回空结果。

### 10.2 `util/server/check_model.py`

两处分支（`check_model` 与 `check_model_gui`）各加一组按模式计算的必需文件：

- **纯 CTC 模式**（`qwen_llm_path` 为空）：融合 encoder + CTC 头 + tokens + preprocessor。
- **有解码器模式**：preprocessor + encoder（拆分则 frontend+backend，否则融合）+ 解码器文件；CTC 头与 tokens **仅在**"融合 encoder 且 `enable_ctc=true` 且路径非空"时校验。
- 缺文件时的提示信息里附上对应的 curl 下载命令（1.7B / 0.6B 各一份）。

### 10.3 `util/server/init_recognizer.py`

无需结构性修改（`QwenCTCArgs.__dict__` 自动展开传入）。仅当新增字段命名与 `create_qwen_ctc_engine` 形参不一致时才需要补。

注意：`init_recognizer.py:33` 里已有的 `from util.fun_asr_gguf import llama, utils` 与 `llama.set_llama_logger(log)` **保持原样不动**（它只设置模块变量，不加载任何 DLL，不触发 llama.cpp 后端初始化），本期不新增对 `util.fun_asr_gguf` 的任何调用。

### 10.4 `.gitignore`

```
/models/qwen-ctc-aiinfra4/*.gguf
/models/qwen-ctc-aiinfra4-06b/*.onnx
/models/qwen-ctc-aiinfra4-06b/*.gguf
/util/qwen_ctc/bin
```

## 11. GUI 与断言连带改动

GUI 用 Rust+Tauri 写配置，schema 与测试**硬锁**配置键数量，任何新键必须同步以下位置，否则 `cargo test` 必红。

| 量 | 旧 | 新 | 落点 |
|---|---|---|---|
| 叶子键 | 178 | **188** | `edit_config_gui/src-tauri/tests/coverage.rs:102`、`src-tauri/src/config_doc.rs:342` |
| 派生只读键 | 13 | **16** | `tests/coverage.rs:117`（`all.len() - dynamic - placeholders` 也随之 163→170） |
| `schema_paths.json` 条数 | 163 | **170** | `tests/coverage.rs:88`（用 `scripts/gen-schema-paths.mjs` 重新生成） |
| probe 集 | 165 | **175** | `src-tauri/src/patch.rs:487` |
| 整行注释数 | 323 | **333** | `src-tauri/src/patch.rs:495,515,687,710,724`、`src-tauri/src/model_paths_resolve.rs:115` |
| 前端可编辑字段数 | 163 | **170** | `src/lib/schema/coverage.test.ts:58`、`:71` |
| `model_paths` 页键数注释 | 17 | **20** | `src/lib/schema/modelPaths.ts` 页头注释 |

新增字段的写法：

- `[model_paths]` 的 3 个新键：`fileField(...)`，后缀分别 `.gguf` / `.onnx` / `.onnx`；`warnOnly` 沿用；两个空默认值的键**必须**加 `allowEmpty: true`（`coverage.test.ts:151` 会校验「allowEmpty 只出现在注释明说留空的键上」）。
- `[qwen_ctc_args]`：3 个 `derived(...)` 只读键 + `enable_ctc`(bool) + `llm_n_ctx`/`llm_n_threads`/`llm_n_predict`(int)。
- `configs/default config.toml` 每加一个键，必须同时加一行 `#` 注释（现有约定：键 → 注释 → 空行）。
- 四个模板（`config.toml`、`configs/{default,debug,minimal} config.toml`）保持同构。
- 仓库根 `edit_config_gui.exe` 被 git 跟踪，需重建并一起提交。

## 12. 测试策略

### 12.1 纯逻辑单元（不需模型文件）

- `valid_frames`：包含 0 / 99 / 100 / 101 / 559 / 3000 等边界。
- 模式判定矩阵：§7.2 每一行都覆盖（含 best-effort 与硬错误）。
- `align_ctc_to_llm`：空 CTC、完全一致、少字、多字、全不匹配；**断言返回长度 == len(llm_text)**。
- 提示构造：token id 序列长度与顺序、特殊符解析失败时的回退。

### 12.2 引擎级（需模型文件，缺失则 skip）

- 融合 encoder → `enc.shape == (73, 2048)`（zh.wav）。
- 拆分 encoder → `last_hidden_state.shape == (73, 1024)`。
- GGUF 行读取：Q4_K 反量化后形状 `[len(ids), 2048]`、值有限。
- 预热不吞错、KV 清理后重复调用结果稳定。

### 12.3 端到端

- `tests/qwen_two_pass_test.py`（新增文件；`tests/qwen_ctc_test.py` 保持零改动以守住老回归）扩三种模式：纯 CTC（与今天结果一致）、两遍（文本==LLM 文本、tokens 长度==文本长度、timestamps 单调不减）、纯 LLM（tokens 为空）。
- `dev/e2e_qwen_ctc_test.py` 走真实 websocket，加两遍 / 纯 LLM 两个用例。

### 12.4 GUI 与配置

- `cargo test`（`edit_config_gui/src-tauri`）全绿。
- `npm test`（vitest，`edit_config_gui`）全绿。
- `scripts/gen-schema-paths.mjs` 重新生成后与断言一致。

### 12.5 回归

- 老配置（无新键）：`enable_ctc` 默认 true、解码器路径空 → 纯 CTC，输出与改动前逐字符一致（拿改动前的结果做基准对比）。

## 13. 文档

- `readme.md`：新增可选项表、三种模式说明、`[qwen_ctc_args]` 新键、1.7B/0.6B 下载命令、GUI 键数从 178 改 188。
- `models/模型下载方式.txt`：新增 1.7B 解码器与 0.6B 三件套的 curl。
- `models/ATTRIBUTION.md`：增补解码器来源与许可。
- `docs/开源许可.md`：同步。
- `util/fun_asr_gguf/bin/llama.cpp二进制下载到这里.txt` 旁新增 `util/qwen_ctc/bin/` 的说明文件。

## 14. 风险与缓解

| 风险 | 缓解 |
|---|---|
| llama.cpp ABI 不匹配导致崩溃 | 绑定层只暴露用到的子集；初始化后立刻做维度/rope_type 自检（`rope_type` 必须是 40，`n_embd` 必须 == encoder 维度）。 |
| OMP 双运行时冲突 | 模块顶部先设 `KMP_DUPLICATE_LIB_OK=TRUE`；加载顺序固定为 llama → ONNX → transformers。 |
| 首次请求卡 2 s | 预热（§9.9）。 |
| 1.7B 解码器内存 1.28 GB + 整表反量化 1.24 GB | 只按需反量化命中行（§9.5）。 |
| 0.6B 无时间戳导致字幕功能退化 | 文档明确；纯 CTC/1.7B 两遍仍可用；日志 WARNING 提示。 |
| 新键破坏老配置或 GUI 测试 | 全部 `.get()` 回退；一次性同步 7 处计数断言 + 重生 `schema_paths.json`。 |
| 复读 / 幻觉 | 复读熔断 + 两遍模式下失败回退 CTC 文本。 |

## 15. 验收标准

1. 老配置启动：`model = "QwenCTC"`，无新键 → 行为与今天一致（纯 CTC）。
2. 1.7B + 解码器 + `enable_ctc=true` → 两遍；`text` 与 CTC 文本相比明显更准（实测 zh/en 均修正了 CTC 的错字并自带标点）；`tokens` 与 `timestamps` 等长且逐字符对应。
3. 1.7B + 解码器 + `enable_ctc=false` → 纯 LLM，无时间戳，不报错。
4. 0.6B 三件套 + `enable_ctc=true` → **启动成功**，日志一条 WARNING，按纯 LLM 出文本。
5. `enable_ctc=false` 且解码器路径空 → 明确硬错误。
6. `cargo test` + `npm test` 全绿；`edit_config_gui.exe` 已重建。
7. 首次识别不出现 ~2 s 卡顿（预热生效）。
