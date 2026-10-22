# Qwen 两遍引擎 + CTC 开关 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `model = "QwenCTC"` 增加完整两遍识别（可选 CTC 首遍 + Qwen3-ASR LLM 二遍），支持 1.7B 与 0.6B 两种尺寸，并由新配置键 `enable_ctc` 控制。

**Architecture:** 所有新代码落在 `util/qwen_ctc/`：自有 ctypes llama.cpp 绑定（`llama_cpp.py`）、双形态 encoder（`encoder.py`）、GGUF 行反量化（`gguf_embed.py`）、LLM 解码器（`llm.py`）、NW 对齐（`align.py`），由改造后的 `engine.py` 编排成三种模式（纯 CTC / 两遍 / 纯 LLM）。服务端只按引擎暴露的 `mode` / `has_timestamps` 分支。

**Tech Stack:** Python 3.14.8、onnxruntime(+DirectML)、transformers(WhisperFeatureExtractor)、gguf 0.19（已在 `pyproject.toml` 的 `server` 组）、llama.cpp 二进制（复用仓库现成构建）、tomlkit、Rust+Tauri+Svelte（配置 GUI）。

**Spec:** `docs/superpowers/specs/2026-10-23-qwen-two-pass-ctc-toggle-design.md`

## Global Constraints

- Python 解释器固定 `./.venv/Scripts/python.exe`；`requires-python == "==3.14.8"`。
- **不得修改、也不得 import `util/fun_asr_gguf/` 下任何内容**（含 `llama.py`、`gguf/quants.py`）。允许用 pip 包 `import gguf` / `from gguf.quants import Q4_K`。
- 新代码只放 `util/qwen_ctc/`；服务端只改 `util/server/{check_model,recognize_qwen_ctc,init_recognizer}.py`。
- `os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"` 必须在任何 torch/transformers 导入之前设置。
- 四个配置模板（`config.toml`、`configs/{default,debug,minimal} config.toml`）必须同构；每加一个键必须紧跟一行 `#` 注释和一行空行。
- 新增配置键在 `util/config.py` 一律用 `.get(key, default)`，保证老配置不炸。
- GUI 计数（改动后必须同步）：叶子键 178→**188**、派生只读 13→**16**、`schema_paths.json` 163→**170**、probe 集 165→**175**、整行注释 323→**333**、前端可编辑字段 163→**170**。
- 仓库根 `edit_config_gui.exe` 被 git 跟踪，GUI schema 改完必须重建。
- 提交信息用 Conventional Commits，scope 取 `(server)` / `(gui)` / `(docs)` / `(tests)`。
- 所有新用例写进 `tests/qwen_two_pass_test.py`（裸函数 + `if __name__ == "__main__"` 里逐个调用、打印 `[OK]`/`[FAIL]` 的既有风格），**每加一个用例必须同时加进 `__main__` 清单**，否则等于没测。

## Review Focus

- **纯静音 / <0.5 s 音频**：CTC 首遍会产出空 chars；对齐必须返回与 LLM 文本等长的列表（而不是崩溃或返回空），LLM 也可能吐空串。
- **下载中断的 GGUF**（1.28 GB 只下一半）：`llama_model_load_from_file` 返回 NULL，必须抛清晰异常，绝不能段错误。
- **单段 >30 s**（客户端把 `seg_duration` 调大）：切块后 `time_offset` 必须连续，且 LLM 每块独立生成不得丢字或重复边界字。
- **中英混排 / 数字**：LLM 文本与 CTC 文本差异大时对齐会退化成大量 gap，时间戳必须仍然单调不减且长度相等。
- **极端 `llm_n_ctx` / `llm_n_threads`**（如 512 / 1 / 64）：必须按规格收紧生成长度并继续工作，不得让 llama.cpp 在满载时报错。

---

## Task 1: `llama_cpp.py` —— 自有 ctypes 绑定 + 二进制目录

**Files:**
- Create: `util/qwen_ctc/llama_cpp.py`
- Create: `util/qwen_ctc/bin/`（把 `util/fun_asr_gguf/bin/` 整个目录复制过来）+ `util/qwen_ctc/bin/llama.cpp二进制下载到这里.txt`
- Modify: `.gitignore`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Produces:
  - `init_lib() -> None`（幂等；加载 DLL 后调 `llama_backend_init()`）
  - `class Model: __init__(path: str | Path, n_gpu_layers: int = -1)`；属性 `.n_embd: int`、`.n_rope_type: int`（40 = IMROPE，别名属性 `.rope_type`）、`.n_vocab: int`；方法 `tokenize(text: str, add_special: bool = False, parse_special: bool = True) -> list[int]`、`token_to_bytes(token_id: int) -> bytes`、`detokenize(tokens: list[int]) -> str`、`free() -> None`
  - `class Context: __init__(model: Model, n_ctx: int, n_batch: int | None = None, n_ubatch: int = 512, n_threads: int = 6)`；方法 `decode_embd(rows: np.ndarray, pos: np.ndarray | None = None) -> int`、`decode_tokens(tokens: list[int]) -> int`、`logits_ith(i: int = -1) -> np.ndarray`、`clear_kv() -> None`、`free() -> None`
  - `class LlamaLoadError(RuntimeError)`

- [ ] **Step 1: 建目录与文件**

```bash
cp -r util/fun_asr_gguf/bin util/qwen_ctc/bin
```
新建 `util/qwen_ctc/bin/llama.cpp二进制下载到这里.txt`，内容一行说明：本目录放 llama.cpp 官方 release 的 `llama.dll`/`ggml*.dll`/`libomp.dll`，可直接从 `util/fun_asr_gguf/bin` 复制，或下同版本官方二进制。

`.gitignore` 追加：

```
/models/qwen-ctc-aiinfra4/*.gguf
/models/qwen-ctc-aiinfra4-06b/*.onnx
/models/qwen-ctc-aiinfra4-06b/*.gguf
/util/qwen_ctc/bin
```

- [ ] **Step 2: 写失败测试**（`tests/qwen_two_pass_test.py`，沿用 `tests/qwen_ctc_test.py` 的裸函数 + `__main__` 清单风格）

```python
DECODER_17B = ROOT / "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"

def test_llama_cpp_loads_decoder_and_reports_mrope():
    from util.qwen_ctc import llama_cpp
    llama_cpp.init_lib()
    m = llama_cpp.Model(DECODER_17B)
    try:
        assert m.n_embd == 2048
        assert m.n_rope_type == 40, f"期望 IMROPE(40)，实际 {m.n_rope_type}"
        assert m.n_vocab == 151936
        c = llama_cpp.Context(m, n_ctx=512, n_threads=4)
        try:
            rc = c.decode_embd(np.zeros((8, 2048), np.float32))
            assert rc == 0
            assert c.logits_ith(-1).shape == (151936,)
            assert np.isfinite(c.logits_ith(-1)).all()
        finally:
            c.free()
    finally:
        m.free()

def test_llama_cpp_raises_on_truncated_gguf(tmp_path):
    from util.qwen_ctc import llama_cpp
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"GGUF" + b"\0" * 64)
    try:
        llama_cpp.Model(bad)
    except llama_cpp.LlamaLoadError:
        return
    raise AssertionError("损坏的 GGUF 必须抛 LlamaLoadError")
```

（属性名以 `n_rope_type` 为准 —— 规格 §9.4 的自检项就是它；`Model` 上同时提供只读别名 `rope_type`。）

- [ ] **Step 3: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'util.qwen_ctc.llama_cpp'`

- [ ] **Step 4: 实现 `util/qwen_ctc/llama_cpp.py`**

模块顶部第一行就设 `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")`，再 import 别的。要点：

- ctypes 结构体对照仓库内 llama.cpp 版本：`llama_model_params`（`n_gpu_layers, split_mode, main_gpu, tensor_split, progress_callback, progress_callback_user_data, kv_overrides, vocab_only, use_mmap, use_mlock, check_tensors, use_extra_bufts, no_host, no_alloc`）、`llama_context_params`、`llama_batch`、`llama_sampler_chain_params`。
- 只绑需要的符号：`llama_backend_init/free`、`llama_model_default_params`、`llama_model_load_from_file`、`llama_model_free`、`llama_model_n_embd`、`llama_model_rope_type`、`llama_model_get_vocab`、`llama_vocab_n_tokens`、`llama_tokenize`、`llama_token_to_piece`、`llama_batch_init/free`、`llama_batch_get_one`、`llama_context_default_params`、`llama_init_from_model`、`llama_free`、`llama_decode`、`llama_get_logits_ith`、`llama_get_memory`、`llama_memory_clear`。
- `llama_get_logits_ith.restype = ctypes.POINTER(ctypes.c_float)`、`argtypes = [ctypes.c_void_p, ctypes.c_int32]`。
- `llama_batch_get_one.restype = llama_batch`（结构体按值返回）、`argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.c_int32]`。
- `Model.__init__`：`load_from_file` 返回 NULL ⇒ `raise LlamaLoadError(f"llama.cpp 无法加载模型: {path}")`。
- `decode_embd(rows, pos=None)`：`n = rows.shape[0]`；`n_tokens_max = max(n * 4, 8192)`；`batch = llama_batch_init(n_tokens_max, n_embd, 1)`；写 embd；把 `struct.token` 置 NULL 强制走 embd-only；`pos` 为 None 时合成 `pos4 = np.concatenate([arange(n)] * 3 + [zeros(n)])`，否则按调用方给的 4n 数组；`ctypes.memmove(struct.pos, pos4.ctypes.data, pos4.nbytes)`。
- `decode_tokens(tokens)`：`llama_batch_get_one` 后直接 `llama_decode`，注意调用后不要 `llama_batch_free`（不拥有内存）。
- `clear_kv()`：`llama_memory_clear(llama_get_memory(ctx), True)`。

- [ ] **Step 5: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: 两个用例打印 `[OK]`

- [ ] **Step 6: 提交**

```bash
git add util/qwen_ctc/llama_cpp.py util/qwen_ctc/bin/llama.cpp二进制下载到这里.txt .gitignore tests/qwen_two_pass_test.py
git commit -m "feat(server): add self-contained llama.cpp ctypes bindings for Qwen decoder"
```

---

## Task 2: `gguf_embed.py` —— 按需反量化 token embedding

**Files:**
- Create: `util/qwen_ctc/gguf_embed.py`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Produces: `class TokenEmbedding: __init__(gguf_path: str | Path, cache: bool = True)`；属性 `.n_embd: int`、`.n_vocab: int`；方法 `rows(ids: Sequence[int]) -> np.ndarray`（dtype float32，形状 `[len(ids), n_embd]`）、`close() -> None`

- [ ] **Step 1: 写失败测试**

```python
def test_token_embedding_rows_are_dequantized():
    from util.qwen_ctc.gguf_embed import TokenEmbedding
    te = TokenEmbedding(DECODER_17B)
    try:
        assert te.n_embd == 2048 and te.n_vocab == 151936
        r = te.rows([151644, 151645, 151669])
        assert r.shape == (3, 2048) and r.dtype == np.float32
        assert np.isfinite(r).all()
        assert not np.allclose(r[0], r[1]), "不同 token 的行不应相同"
        assert np.allclose(te.rows([151644]), r[:1]), "同一 token 两次取值必须一致"
    finally:
        te.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ModuleNotFoundError: ... gguf_embed`

- [ ] **Step 3: 实现 `util/qwen_ctc/gguf_embed.py`**

要点：`import gguf` + `from gguf.quants import dequantize`；`reader = gguf.GGUFReader(str(path))`；**`reader.tensors` 是 list**，用 `next(t for t in reader.tensors if t.name == "token_embd.weight")`（该版本 `get_tensor()` 只接受整数索引）；只对请求的行切片反量化：`raw = np.asarray(t.data)[ids]` → `dequantize(raw, t.tensor_type)` → `np.asarray(..., np.float32)`；结果按 id 存 LRU（`collections.OrderedDict`，上限 4096 条）；`cache=True` 时把整表缓存写到 `<gguf>.embd.npy` 若已存在则直接 mmap 读（写入不强制，读优先）。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: `[OK]`

- [ ] **Step 5: 提交**

```bash
git add util/qwen_ctc/gguf_embed.py tests/qwen_two_pass_test.py
git commit -m "feat(server): add per-row Q4_K token embedding reader for Qwen GGUF"
```

---

## Task 3: `encoder.py` —— 融合 / 拆分双形态 encoder

**Files:**
- Create: `util/qwen_ctc/encoder.py`
- Modify: `util/qwen_ctc/engine.py`（把 `_features` / `_valid_frames` / `_resolve_providers` 迁走，引擎改为调用新模块）
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Produces:
  - `FRAME_RATE_HZ = 13.0`
  - `valid_frames(mel_len: int) -> int` —— `full, leave = divmod(mel_len, 100); return full * 13 + (0 if leave == 0 else (leave - 1) // 8 + 1)`
  - `resolve_providers(ort, provider: str) -> list[str]`（`"dml"` 且可用 ⇒ `["DmlExecutionProvider", "CPUExecutionProvider"]`，否则 CPU）
  - `class FusedEncoder: __init__(encoder_path, preprocessor_path, num_threads=6, provider="cpu", mel_frames=3000, logger=None)`；属性 `.output_dim: int`；方法 `encode(audio: np.ndarray) -> np.ndarray`、`close()`
  - `class SplitEncoder: __init__(frontend_path, backend_path, preprocessor_path, num_threads=6, provider="cpu", logger=None)`；属性 `.output_dim: int`；方法 `encode(audio) -> np.ndarray`、`close()`

- [ ] **Step 1: 写失败测试**

```python
def test_valid_frames_boundaries():
    from util.qwen_ctc.encoder import valid_frames
    assert valid_frames(0) == 0
    assert valid_frames(99) == 13          # leave=99 → (98)//8+1 = 13
    assert valid_frames(100) == 13         # leave=0
    assert valid_frames(101) == 14
    assert valid_frames(559) == 73
    assert valid_frames(3000) == 390

def test_fused_encoder_shape():
    enc = _make_fused_encoder()
    audio = _read_wav(AUDIO_ZH)
    out = enc.encode(audio)
    assert out.shape == (73, 2048) and out.dtype == np.float32
    assert np.isfinite(out).all()

def test_split_encoder_shape():
    enc = _make_split_encoder()
    out = enc.encode(_read_wav(AUDIO_ZH))
    assert out.shape == (73, 1024) and out.dtype == np.float32
```

（`_make_fused_encoder` / `_make_split_encoder` / `_read_wav` 是本文件里的辅助函数；模型缺失时用 `if not _models_available(): print("skip"); return` 显式跳过，与 `tests/qwen_ctc_test.py` 的 `_model_available()` 风格一致。）

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ModuleNotFoundError: ... encoder`

- [ ] **Step 3: 实现 `util/qwen_ctc/encoder.py`**

- 共用：`WhisperFeatureExtractor.from_pretrained(preprocessor_path)`（**在函数内 import** transformers，保证 llama 先初始化）；`SessionOptions(intra_op_num_threads=num_threads or 0, graph_optimization_level=ORT_ENABLE_ALL)`。
- `FusedEncoder.encode`：`feats = self._fe(audio, sampling_rate=16000, padding=False, return_tensors="np").input_features[0]`；`t = feats.shape[1]`；补零到 `mel_frames` 列；跑 `{"input_features": padded[None], "feature_length": np.array([t], np.int64)}`；取 `enc_output[0][:valid_frames(t)]`，`astype(np.float32)`。
- `SplitEncoder.encode`：不补零；按 `100` 帧切块（末块补零到 100）；每块跑 frontend（`{"chunk_mel": blk[None]}` → `chunk_out[0]`）拼成 `[13*chunks, 896]`；截断到 `valid_frames(t)`；`attention_mask = np.ones((1, 1, T, T), np.float32)`；跑 backend（`hidden_states` + `attention_mask`）→ `last_hidden_state[0]`。
- 两者的 `output_dim` 从 ONNX 元数据读（`session.get_outputs()[0].shape[-1]`；拆分取 backend 的 `last_hidden_state` 最后一维）。
- `engine.py` 里删掉 `_features`/`_valid_frames`/`_resolve_providers`，改为 `from util.qwen_ctc.encoder import FusedEncoder, valid_frames` 并调用；`FRAME_RATE_HZ` 改从 encoder 导入再 re-export（`util/qwen_ctc/__init__.py` 的导出名不变）。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py && ./.venv/Scripts/python.exe tests/qwen_ctc_test.py`
Expected: 两个文件全绿（`qwen_ctc_test.py` 是纯 CTC 回归，必须仍然通过）

- [ ] **Step 5: 提交**

```bash
git add util/qwen_ctc/encoder.py util/qwen_ctc/engine.py util/qwen_ctc/__init__.py tests/qwen_two_pass_test.py
git commit -m "refactor(server): extract fused/split Qwen3-ASR encoders into encoder.py"
```

---

## Task 4: `align.py` —— CTC 字符时间戳对齐到 LLM 文本

**Files:**
- Create: `util/qwen_ctc/align.py`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Produces: `align_ctc_to_llm(ctc_chars: Sequence[str], ctc_starts: Sequence[float], llm_text: str, duration: float) -> list[float]`

- [ ] **Step 1: 写失败测试**

```python
def test_align_length_always_matches_llm_text():
    from util.qwen_ctc.align import align_ctc_to_llm
    ts = align_ctc_to_llm(list("開放時間早上九點"), [0.1 * i for i in range(8)], "開放時間：早上九點。", 4.0)
    assert len(ts) == len("開放時間：早上九點。")
    assert all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1)), "时间戳必须单调不减"

def test_align_empty_ctc_distributes_evenly():
    from util.qwen_ctc.align import align_ctc_to_llm
    ts = align_ctc_to_llm([], [], "abcd", 4.0)
    assert ts == [0.0, 1.0, 2.0, 3.0]

def test_align_identical_text_keeps_starts():
    from util.qwen_ctc.align import align_ctc_to_llm
    ts = align_ctc_to_llm(list("abcd"), [0.5, 1.5, 2.5, 3.5], "abcd", 4.0)
    assert ts == [0.5, 1.5, 2.5, 3.5]

def test_align_heavy_mismatch_stays_monotonic():
    from util.qwen_ctc.align import align_ctc_to_llm
    ts = align_ctc_to_llm(list("一二三四五"), [0.2, 0.4, 0.6, 0.8, 1.0], "ABCDE12345", 6.0)
    assert len(ts) == 10 and all(ts[i] <= ts[i + 1] for i in range(9))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ModuleNotFoundError: ... align`

- [ ] **Step 3: 实现 `util/qwen_ctc/align.py`**

NW DP：`prev` 为 CTC 字符序列（带 starts），`cur` 为 LLM 字符序列。打分 match +1.0 / mismatch −1.0 / gap −1.0；比较前做 `casefold()` + 全角转半角归一。回溯得到每个 LLM 字符对应的 CTC 下标；未匹配的在两侧锚点之间线性插值；整段无锚点时按 `i * duration / len(llm_text)` 均分；`len(llm_text) == 0` 返回 `[]`。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: `[OK]`

- [ ] **Step 5: 提交**

```bash
git add util/qwen_ctc/align.py tests/qwen_two_pass_test.py
git commit -m "feat(server): align CTC char timestamps onto LLM transcript via NW"
```

---

## Task 5: `llm.py` —— Qwen3-ASR LLM 解码器

**Files:**
- Create: `util/qwen_ctc/llm.py`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Consumes: Task 1 的 `llama_cpp.Model` / `Context` / `decode_embd` / `decode_tokens` / `logits_ith`；Task 2 的 `TokenEmbedding.rows`；Task 4 的 `align_ctc_to_llm`
- Produces: `class QwenLLMDecoder: __init__(gguf_path, n_ctx=4096, n_threads=6, n_predict=256, verbose=False, logger=None)`；属性 `.n_embd: int`、`.prefix_ids: list[int]`、`.suffix_ids: list[int]`、`.stop_ids: set[int]`；方法 `effective_n_predict(n_prefill: int) -> int`、`generate(audio_embd: np.ndarray) -> str`、`warmup() -> None`、`close() -> None`

- [ ] **Step 1: 写失败测试**

```python
def test_llm_prompt_special_tokens():
    dec = _make_llm_decoder()
    try:
        assert dec.n_embd == 2048
        assert dec.prefix_ids[-1] == 151669, "prefix 必须落在 <|audio_start|>"
        assert dec.suffix_ids[0] == 151670, "suffix 必须以 <|audio_end|> 开始"
        assert dec.stop_ids == {151645, 151643}
        assert len(dec.prefix_ids) == 14 and len(dec.suffix_ids) == 6
    finally:
        dec.close()

def test_llm_generates_transcript_from_encoder_output():
    dec = _make_llm_decoder()
    enc = _make_fused_encoder()
    try:
        text = dec.generate(enc.encode(_read_wav(AUDIO_ZH)))
        assert text, "生成结果不得为空"
        assert "<|im_end|>" not in text and "<|im_start|>" not in text
    finally:
        dec.close()

def test_llm_predict_is_clamped_to_context():
    dec = _make_llm_decoder(n_ctx=512, n_predict=100000)
    try:
        assert dec.effective_n_predict(410) == 512 - 410
    finally:
        dec.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ModuleNotFoundError: ... llm`

- [ ] **Step 3: 实现 `util/qwen_ctc/llm.py`**

- 特殊 token：`_resolve_special(name, fallback)` = `model.tokenize(name, add_special=False, parse_special=True)`，长度必须为 1，否则用 fallback（`<|im_start|>`=151644、`<|im_end|>`=151645、`<|endoftext|>`=151643、`<|audio_start|>`=151669、`<|audio_end|>`=151670、`<asr_text|>`=151704）。
- prompt 构造（规格 §9.3）：`prefix_ids = [IM_START] + tok("system\nYou are a helpful assistant.") + [IM_END] + [IM_START] + tok("user\n") + [AUDIO_START]`；`suffix_ids = [AUDIO_END, IM_END, IM_START] + tok("assistant\n") + [ASR_TEXT]`。
- `generate(audio_embd)`：`full = concat([prefix_embd, audio_embd.astype(np.float32), suffix_embd])`；`pos4 = concat([arange(n)]*3 + [zeros(n)]).astype(np.int32)`；`ctx.clear_kv()`；`ctx.decode_embd(full, pos4)`；贪心循环 `ctx.logits_ith(-1).argmax()` → `ctx.decode_tokens([tid])`，命中 `stop_ids` 或达上限即停；最后把收集到的 token 逐个 `token_to_bytes` 拼接再整体 `decode("utf-8", errors="replace")`（不逐 token 解码）。
- `effective_n_predict(n_prefill)`：`min(self._n_predict, max(self._n_ctx - n_prefill, 0))`，被收紧时打 WARNING。
- 复读熔断：最近 30 个 token 的去重值 ≤3 时，`ctx.clear_kv()` 后以温度 0.3 递增重试，最多 4 次（温度 >0 时用 `np.random.choice` 按 softmax 采样）。
- `warmup()`：1 帧静音 → `np.zeros((1, n_embd), np.float32)` 走一遍 `generate`，吞掉"图 reserve"开销；异常只记日志不抛。
- `close()`：`ctx.free()` → `model.free()` → `embed.close()`。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: `[OK]`（LLM 生成用例可能耗时数秒）

- [ ] **Step 5: 提交**

```bash
git add util/qwen_ctc/llm.py tests/qwen_two_pass_test.py
git commit -m "feat(server): add Qwen3-ASR LLM second-pass decoder with M-RoPE embedding injection"
```

---

## Task 6: `engine.py` —— 三模式编排

**Files:**
- Modify: `util/qwen_ctc/engine.py`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Consumes: `FusedEncoder`/`SplitEncoder`/`valid_frames`（Task 3）、`align_ctc_to_llm`（Task 4）、`QwenLLMDecoder`（Task 5）
- Produces:
  - `QwenCTCConfig` 新增字段：`decoder_gguf_path: str = ""`、`encoder_frontend_path: str = ""`、`encoder_backend_path: str = ""`、`enable_ctc: bool = True`、`llm_n_ctx: int = 4096`、`llm_n_threads: int = 6`、`llm_n_predict: int = 256`
  - `resolve_mode(split_encoder: bool, has_decoder: bool, enable_ctc: bool, ctc_usable: bool) -> str`（返回 `"ctc"` / `"two_pass"` / `"llm"`，非法组合抛 `ValueError`，消息与规格 §7.2 一致）
  - `QwenCTCEngine.mode`、`QwenCTCEngine.has_timestamps`
  - `create_qwen_ctc_engine(...)` 增加上述 7 个关键字参数（全部有默认值）

- [ ] **Step 1: 写失败测试**（覆盖规格 §7.2 全部行）

```python
def test_resolve_mode_matrix():
    from util.qwen_ctc.engine import resolve_mode
    assert resolve_mode(False, True, True, True) == "two_pass"
    assert resolve_mode(False, True, True, False) == "llm"
    assert resolve_mode(False, True, False, False) == "llm"
    assert resolve_mode(False, False, True, True) == "ctc"
    assert resolve_mode(True, True, True, False) == "llm"
    assert resolve_mode(True, True, False, True) == "llm"

def test_resolve_mode_rejects_impossible_combos():
    from util.qwen_ctc.engine import resolve_mode
    for args, needle in (
        ((False, False, False, True), "未配置解码器"),
        ((True, False, True, False), "0.6B"),
    ):
        try:
            resolve_mode(*args)
        except ValueError as e:
            assert needle in str(e)
        else:
            raise AssertionError(f"{args} 必须报错")

def test_engine_modes_end_to_end():
    # 纯 CTC
    e = _make_engine(decoder="", enable_ctc=True); assert e.mode == "ctc" and e.has_timestamps
    r = e.transcribe(_read_wav(AUDIO_ZH)); assert r.text and len(r.tokens) == len(r.timestamps)
    e.cleanup()
    # 两遍
    e = _make_engine(decoder=DECODER_17B, enable_ctc=True); assert e.mode == "two_pass"
    r = e.transcribe(_read_wav(AUDIO_ZH))
    assert r.text and len(r.tokens) == len(r.text) and len(r.timestamps) == len(r.tokens)
    assert all(r.timestamps[i] <= r.timestamps[i+1] for i in range(len(r.timestamps)-1))
    e.cleanup()
    # 纯 LLM
    e = _make_engine(decoder=DECODER_17B, enable_ctc=False); assert e.mode == "llm" and not e.has_timestamps
    r = e.transcribe(_read_wav(AUDIO_ZH)); assert r.text and r.tokens == [] and r.timestamps == []
    e.cleanup()

def test_engine_silence_does_not_crash():
    e = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        r = e.transcribe(np.zeros(16000, np.float32))   # 1 秒静音
        assert isinstance(r.text, str)
        assert len(r.tokens) == len(r.text) or r.tokens == []
    finally:
        e.cleanup()

def test_engine_long_audio_offsets_are_continuous():
    e = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        r = e.transcribe(_read_wav(AUDIO_31S))          # >30 s，触发切块
        assert r.timestamps and max(r.timestamps) > 30.0
        assert all(r.timestamps[i] <= r.timestamps[i+1] for i in range(len(r.timestamps)-1))
    finally:
        e.cleanup()
def test_engine_repeat_calls_are_stable():
    e = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        audio = _read_wav(AUDIO_ZH)
        a, b = e.transcribe(audio).text, e.transcribe(audio).text
        assert a and a == b, "同一引擎连续两次识别结果必须一致（预热 + KV 清理生效）"
    finally:
        e.cleanup()
```

（`_make_engine(...)` 是测试内的工厂，转发到 `create_qwen_ctc_engine`；`AUDIO_31S` 用 `np.concatenate([audio] * 6)` 近似拼接，不足 31 s 则继续重复。）

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ImportError: cannot import name 'resolve_mode'`

- [ ] **Step 3: 改造 `util/qwen_ctc/engine.py`**

- `QwenCTCConfig` 加 7 个字段。
- `resolve_mode(...)` 按规格 §7.2 实现：`has_decoder and enable_ctc and ctc_usable → "two_pass"`；`has_decoder → "llm"`；`not has_decoder and enable_ctc → "ctc"`；其余抛 `ValueError`；`split_encoder and not has_decoder` 抛「0.6B 无 CTC 头，必须配置解码器」；`split_encoder and ctc_usable` 视为不可用（0.6B 没有 CTC 头）。
- `initialize()` **必须按规格 §5.3 的顺序**：① `llama_cpp.init_lib()` → ② 若 `decoder_gguf_path` 非空且文件存在则 `QwenLLMDecoder(...)`（此时才加载 GGUF/建 context）→ ③ 建 encoder（**这一步才会 import transformers**）→ ④ 建 CTC session → ⑤ 校验 `llm.n_embd == encoder.output_dim`（不等则 `ValueError`），并把「CTC 头可用性」定为 `文件存在 且 ctc_session.get_inputs()[0].shape[-1] == encoder.output_dim` → ⑥ `self.mode = resolve_mode(...)`、`self.has_timestamps = mode in ("ctc", "two_pass")` → ⑦ `llm.warmup()`。encoder 只在两端都配时用 `SplitEncoder`，只配一端抛 `ValueError`。
- `decode(audio)`：逐 30 s 块，`enc = encoder.encode(chunk)`；`mode == "two_pass"` ⇒ CTC 首遍出 chars/starts、LLM 出文本、`align_ctc_to_llm`；LLM 抛异常 ⇒ 记 error 并回退该块的 CTC 文本/时间戳。`mode == "ctc"` ⇒ 沿用现有逻辑。`mode == "llm"` ⇒ 只出文本。
- `cleanup()` 依次释放 llm / encoder / ctc session。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py && ./.venv/Scripts/python.exe tests/qwen_ctc_test.py`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add util/qwen_ctc/engine.py tests/qwen_two_pass_test.py
git commit -m "feat(server): orchestrate CTC/two-pass/LLM modes in Qwen engine"
```

---

## Task 7: 配置面 —— `util/config.py` + 四个模板

**Files:**
- Modify: `util/config.py:236-243`（ModelPaths）、`util/config.py:295-307`（QwenCTCArgs）
- Modify: `config.toml`、`configs/default config.toml`、`configs/debug config.toml`、`configs/minimal config.toml`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Consumes: Task 6 的 `create_qwen_ctc_engine` 新参数名
- Produces: `QwenCTCArgs.decoder_gguf_path` / `.encoder_frontend_path` / `.encoder_backend_path` / `.enable_ctc` / `.llm_n_ctx` / `.llm_n_threads` / `.llm_n_predict`；`ModelPaths.qwen_llm_path` / `.qwen_ctc_encoder_frontend_path` / `.qwen_ctc_encoder_backend_path`

- [ ] **Step 1: 写失败测试**

```python
TEMPLATES = [ROOT / "config.toml"] + sorted((ROOT / "configs").glob("* config.toml"))

def test_templates_have_new_qwen_keys():
    import tomlkit
    for p in TEMPLATES:
        doc = tomlkit.parse(p.read_text(encoding="utf-8"))
        mp, qa = doc["model_paths"], doc["qwen_ctc_args"]
        assert "qwen_llm_path" in mp, f"{p} 缺 qwen_llm_path"
        assert "qwen_ctc_encoder_frontend_path" in mp
        assert "qwen_ctc_encoder_backend_path" in mp
        assert qa["decoder_gguf_path"] == "${model_paths.qwen_llm_path}"
        assert qa["enable_ctc"] is True
        assert qa["llm_n_ctx"] == 4096 and qa["llm_n_threads"] == 6 and qa["llm_n_predict"] == 256

def test_default_template_comment_count_is_333():
    p = ROOT / "configs/default config.toml"
    n = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip().startswith("#"))
    assert n == 333, f"整行注释数应为 333，实际 {n}"

def test_qwen_ctc_args_reads_new_keys_with_get_fallback():
    src = (ROOT / "util/config.py").read_text(encoding="utf-8")
    for key in ("qwen_llm_path", "qwen_ctc_encoder_frontend_path", "qwen_ctc_encoder_backend_path"):
        assert f'.get("{key}"' in src, f"ModelPaths 必须用 .get 读 {key}"
    for key in ("enable_ctc", "llm_n_ctx", "llm_n_threads", "llm_n_predict",
                "decoder_gguf_path", "encoder_frontend_path", "encoder_backend_path"):
        assert f'.get("{key}"' in src, f"QwenCTCArgs 必须用 .get 读 {key}"
    from util.config import QwenCTCArgs
    assert QwenCTCArgs.enable_ctc is True
    assert (QwenCTCArgs.llm_n_ctx, QwenCTCArgs.llm_n_threads, QwenCTCArgs.llm_n_predict) == (4096, 6, 256)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `AssertionError: 缺 qwen_llm_path`

- [ ] **Step 3: 改配置与代码**

- `ModelPaths` 新增三个字段，全部 `.get`：`qwen_llm_path`（默认 `"models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"`）、`qwen_ctc_encoder_frontend_path`（默认 `""`）、`qwen_ctc_encoder_backend_path`（默认 `""`）。
- `QwenCTCArgs` 新增 7 个字段（`.get` + 规格 §6.3 的默认值）。
- 四个模板在 `[model_paths]` 的 `qwen_ctc_preprocessor_path` 之后追加 3 个键（各带一行 `#` 注释 + 空行），在 `[qwen_ctc_args]` 的 4 个路径键之后追加 3 个派生键，在 `verbose` 之前追加 4 个新键。注释文案必须让两个空路径键出现「留空」二字（GUI 测试要求）。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: `[OK]`

- [ ] **Step 5: 提交**

```bash
git add util/config.py config.toml "configs/default config.toml" "configs/debug config.toml" "configs/minimal config.toml" tests/qwen_two_pass_test.py
git commit -m "feat(server): expose enable_ctc and LLM params in QwenCTC config"
```

---

## Task 8: `check_model.py` —— 按模式校验必需文件

**Files:**
- Modify: `util/server/check_model.py:44-51`、`:139-146`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Produces: `required_qwen_files(split_encoder: bool, has_decoder: bool, enable_ctc: bool, paths: dict) -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
def test_required_files_pure_ctc():
    from util.server.check_model import required_qwen_files
    p = dict(encoder="e.onnx", frontend="", backend="", ctc="c.onnx", tokens="t.txt", preprocessor="pp", decoder="")
    assert sorted(required_qwen_files(False, False, True, p)) == sorted(["e.onnx", "c.onnx", "t.txt", "pp"])

def test_required_files_two_pass_needs_no_ctc_head_when_optional():
    from util.server.check_model import required_qwen_files
    p = dict(encoder="e.onnx", frontend="", backend="", ctc="c.onnx", tokens="t.txt", preprocessor="pp", decoder="d.gguf")
    files = required_qwen_files(False, True, True, p)
    assert "d.gguf" in files and "e.onnx" in files

def test_required_files_split_encoder_skips_ctc():
    from util.server.check_model import required_qwen_files
    p = dict(encoder="e.onnx", frontend="f.onnx", backend="b.onnx", ctc="", tokens="", preprocessor="pp", decoder="d.gguf")
    files = required_qwen_files(True, True, True, p)
    assert sorted(files) == sorted(["f.onnx", "b.onnx", "pp", "d.gguf"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — `ImportError: cannot import name 'required_qwen_files'`

- [ ] **Step 3: 实现**

把两处分支的 QwenCTC 文件列表统一改为调用 `required_qwen_files(...)`（从 `Config`/`QwenCTCArgs`/`ModelPaths` 取路径）；缺失时的提示信息追加 1.7B 与 0.6B 的 curl 命令（规格 §4.3）。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: `[OK]`

- [ ] **Step 5: 提交**

```bash
git add util/server/check_model.py tests/qwen_two_pass_test.py
git commit -m "feat(server): validate QwenCTC model files per resolved mode"
```

---

## Task 9: `recognize_qwen_ctc.py` —— 按模式拼接与标点策略

**Files:**
- Modify: `util/server/recognize_qwen_ctc.py`
- Test: `tests/qwen_two_pass_test.py`

**Interfaces:**
- Consumes: 引擎的 `mode` / `has_timestamps`
- Produces: 行为（无新公开 API）

- [ ] **Step 1: 写失败测试**（用假 recognizer / 假 punc_model）

```python
class _FakeStream:
    def __init__(self, result): self.result = result
    def accept_waveform(self, sr, audio): pass

class _FakeRecognizer:
    def __init__(self, mode, text="", tokens=None, timestamps=None):
        self.mode = mode
        self.has_timestamps = mode in ("ctc", "two_pass")
        self._r = SimpleNamespace(text=text, tokens=tokens or [], timestamps=timestamps or [])
    def create_stream(self): return _FakeStream(self._r)
    def decode_stream(self, s): pass

class _CountingPunc:
    def __init__(self): self.calls = 0
    def add_punctuation(self, t): self.calls += 1; return t + "。"

def test_llm_mode_merges_by_text():
    import util.server.recognize_qwen_ctc as m
    task = SimpleNamespace(task_id="t1", socket_id="s1", source="mic", data=np.zeros(16000, np.float32),
                           offset=0.0, overlap=0.0, is_final=True, time_start=0.0, time_submit=0.0,
                           samplerate=16000)
    r = m.recognize(_FakeRecognizer("llm", text="你好世界"), punc_model=None, task=task)
    assert r.text == "你好世界" and r.tokens == []

def test_two_pass_skips_punctuation_model():
    import util.server.recognize_qwen_ctc as m
    punc = _CountingPunc()
    task = ...  # 同上
    r = m.recognize(_FakeRecognizer("two_pass", text="你好。", tokens=list("你好。"), timestamps=[0.0, 0.4, 0.8]),
                    punc_model=punc, task=task)
    assert punc.calls == 0, "两遍模式的 LLM 文本已自带标点，不得再过标点模型"
    assert r.text == "你好。"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: FAIL — 断言失败（当前实现无论模式都会拼 token / 调标点）

- [ ] **Step 3: 实现**

- `recognize()` 里按 `recognizer.has_timestamps` 分支：有 ⇒ 现有 token 合并；无 ⇒ `result.text = merge_by_text(result.text, stream.result.text, logger=_logger)`，`result.text_accu = result.text`。
- `format_text(text, punc_model)` 增加 `use_punc: bool` 形参；两遍与纯 LLM 模式传 `False`（跳过 `add_punctuation`，保留 `adjust_space` / `chinese_to_num`），纯 CTC 模式保持现状（`Config.format_punc` 决定）。
- 仍保留 `except Exception` 兜底返回空 `Result`。

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe tests/qwen_two_pass_test.py`
Expected: `[OK]`

- [ ] **Step 5: 提交**

```bash
git add util/server/recognize_qwen_ctc.py tests/qwen_two_pass_test.py
git commit -m "feat(server): branch QwenCTC merging and punctuation on engine mode"
```

---

## Task 10: 配置 GUI（schema + 计数断言 + schema_paths.json + exe 重建）

**Files:**
- Modify: `edit_config_gui/src/lib/schema/modelPaths.ts`（`qwenCtcFields`，约 158-189 行；页头注释「5 个目录 + 12 个文件（共 17 个键）」→ 20）
- Modify: `edit_config_gui/src/lib/schema/modelArgs.ts`（`qwenCtcFields`，约 305-352 行）
- Modify: `edit_config_gui/src/lib/schema/coverage.test.ts:58,71,151`
- Modify: `edit_config_gui/src-tauri/tests/coverage.rs:88,102,117,119`
- Modify: `edit_config_gui/src-tauri/src/config_doc.rs:342`
- Modify: `edit_config_gui/src-tauri/src/patch.rs:487`
- Modify: `edit_config_gui/src-tauri/src/patch.rs:495,515,687,710,724`、`src/model_paths_resolve.rs:115`（323→333）
- Regenerate: `edit_config_gui/src-tauri/tests/schema_paths.json`
- Rebuild: `edit_config_gui.exe`
- Test: 上述 Rust/前端测试自身

**Interfaces:**
- Consumes: Task 7 的键名与默认值

- [ ] **Step 1: 改前端 schema**

`modelPaths.ts` 加 3 个 `fileField`：`qwen_llm_path`（后缀 `.gguf`，默认 `models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf`，alias `llm`）、`qwen_ctc_encoder_frontend_path`（`.onnx`，默认 `""`，`allowEmpty: true`，注释含「留空」）、`qwen_ctc_encoder_backend_path`（同上）。
`modelArgs.ts` 的 `qwenCtcFields` 加 3 个 `derived(...)`（对应三个新派生键）+ `enable_ctc`(bool，默认 true) + `llm_n_ctx`/`llm_n_threads`/`llm_n_predict`(int)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd edit_config_gui && npm test -- --run`
Expected: FAIL — `editableFields().length` 期望 163 实际 170

- [ ] **Step 3: 改断言到新基准**

`coverage.test.ts`：163→170（两处）。`coverage.rs`：`schema.len()` 163→170、`all.len()` 178→188、`placeholders` 13→16、`all.len()-dynamic-placeholders` 163→170。`config_doc.rs`：178→188。`patch.rs`：`probes.len()` 165→175、`comment_line_count` 323→333（5 处）。`model_paths_resolve.rs:115`：323→333。

- [ ] **Step 4: 重新生成 `schema_paths.json` 并跑全部测试**

```bash
cd edit_config_gui && node scripts/gen-schema-paths.mjs
npm test -- --run
cd src-tauri && cargo test
```
Expected: 全部 PASS；`schema_paths.json` 有 170 条 `[[string]]` 条目

- [ ] **Step 5: 重建 `edit_config_gui.exe`**

按 `edit_config_gui/README.md` 的发布步骤构建，产物覆盖仓库根的 `edit_config_gui.exe`。

- [ ] **Step 6: 提交**

```bash
git add edit_config_gui/ edit_config_gui.exe
git commit -m "feat(gui): expose QwenCTC enable_ctc and LLM params"
```

---

## Task 11: 文档

**Files:**
- Modify: `readme.md`（QwenCTC 相关段落：新增可选项、三种模式表、`[qwen_ctc_args]` 新键、下载命令、GUI 键数 178→188）
- Modify: `models/模型下载方式.txt`（1.7B 解码器 + 0.6B 三件套 curl）
- Modify: `models/ATTRIBUTION.md`（解码器来源与许可）
- Modify: `docs/开源许可.md`

- [ ] **Step 1: 改文档**

按规格 §4.3 / §6 / §13 写入；readme 里凡出现 `178` 的位置改成 `188`（并同步 `163`→`170`、`13`→`16` 的说明文字）。

- [ ] **Step 2: 校验**

```bash
grep -n "178" readme.md edit_config_gui/README.md | grep -v 188 || echo "(无残留 178)"
grep -c "qwen_llm_path\|enable_ctc\|llm_n_ctx" readme.md
```
Expected: 无残留旧数字；新键至少在 readme 出现 1 次

- [ ] **Step 3: 提交**

```bash
git add readme.md models/模型下载方式.txt models/ATTRIBUTION.md docs/开源许可.md
git commit -m "docs: document Qwen two-pass engine, CTC toggle and decoder downloads"
```

---

## Task 12: 端到端脚本与全量回归

**Files:**
- Modify: `dev/e2e_qwen_ctc_test.py`（加两遍 / 纯 LLM 两个用例）
- Test: 全部

- [ ] **Step 1: 扩 e2e 脚本**

按现有 websocket 流程（base64 float32 16 kHz 单声道、`SEG_DURATION=15.0`、`SEG_OVERLAP=2.0`）加：
- 两遍用例：断言 `text` 非空、`len(tokens) == len(timestamps) == len(text)`、时间戳单调；
- 纯 LLM 用例：断言 `text` 非空、`tokens == []`、`timestamps == []`。

- [ ] **Step 2: 跑全部测试**

```bash
./.venv/Scripts/python.exe tests/qwen_ctc_test.py
./.venv/Scripts/python.exe tests/qwen_two_pass_test.py
./.venv/Scripts/python.exe dev/e2e_qwen_ctc_test.py
cd edit_config_gui && npm test -- --run && cd src-tauri && cargo test
```
Expected: 全绿

- [ ] **Step 3: 手工回归三模式**（改 `config.toml` 跑服务端，各说一句中文）

1. 解码器路径留空 + `enable_ctc=true` → 与改动前一致（纯 CTC，有字级时间戳）；
2. 1.7B 解码器 + `enable_ctc=true` → 两遍，文本更准且自带标点，字幕时间轴正常；
3. 1.7B 解码器 + `enable_ctc=false` → 纯 LLM，无时间戳，不报错；
4. 0.6B 三件套 + `enable_ctc=true` → 启动成功、日志一条 WARNING、按纯 LLM 出文本。

- [ ] **Step 4: 提交**

```bash
git add dev/e2e_qwen_ctc_test.py
git commit -m "test: cover Qwen two-pass and pure-LLM modes end to end"
```

---

## 依赖关系

```
Task 1 ──> Task 2 ──┐
Task 3 ──> Task 4 ──┼─> Task 5 ──> Task 6 ──> Task 7 ──> Task 8 ──> Task 9 ──> Task 12
                    │                          └──────> Task 10
                    └──────────────────────────────────> Task 11（文档可并行）
```
Task 1/3/4 可并行起步；Task 10 依赖 Task 7 的键名；Task 12 最后跑。
