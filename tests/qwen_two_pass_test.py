# coding: utf-8
"""
Qwen 两遍引擎（LLM 二遍）测试

不依赖 pytest：直接 `python tests/qwen_two_pass_test.py` 运行。

Task 1 覆盖「自有 llama.cpp 绑定层」这一块地基：
1. 随包的 llama.dll 能加载 Qwen3-ASR 解码器 GGUF，且报告 IMROPE（rope_type=40）
   —— 这是 M-RoPE 4 平面位置注入能工作的前提；
2. 模型加载失败必须抛 `LlamaLoadError`，不能把 NULL 指针带进后续调用。

Task 2 覆盖 `util/qwen_ctc/gguf_embed.py`（按需反量化 token embedding 行）：
3. 真实解码器 GGUF（Q4_K）能按 token id 取出 float32 行，形状/有限性/一致性对；
4. 行的取值必须与 GGUF 里的 vocab 行严格对应（用自造的最小 GGUF 精确比对）；
5. 越界 id / close() 之后再取必须报错，空 ids 返回 [0, n_embd]；
6. LRU 上限 4096 条，淘汰之后取值仍然正确；
7. 整表缓存 `<gguf>.embd.npy` 写了能复用（mmap），形状不符的旧缓存必须被忽略；
8. 0.6B 解码器的维度是 n_embd=1024 / n_vocab=151936。

Task 3 覆盖 `util/qwen_ctc/encoder.py`（融合 / 拆分双形态 encoder）：
9.  `valid_frames` 的 13fps 边界值、provider 选择（cpu / dml 回退）；
10. 1.7B 融合形态：559 帧 mel → `[73, 2048]`，且与手工流水线逐值一致；
11. 0.6B 拆分形态：100 帧切块 + 末块补零 + 13 帧/块拼接 + 截断 + 4D 全 1 mask
    → `[73, 1024]`，且与手工流水线逐值一致；
12. `close()` 幂等、关闭后再 encode 报 RuntimeError；超过 30s 的音频喂融合
    encoder 必须显式 ValueError（不能静默截断）。

Task 4 覆盖 `util/qwen_ctc/align.py`（CTC 字级时间戳 → LLM 文本）：
13. 返回长度严格等于 `len(text)`（LLM 会改字、补标点，长度与 CTC 不同）；
14. 时间戳单调不减、落在 CTC 时间范围内，任何输入都不许抛异常；
15. 完全一致的两段文本必须原样保留 CTC 起始时间；空 CTC 按 `i*duration/len(text)`
    均分；LLM 多出来的标点在两侧锚点之间线性插值；大小写 / 全角半角不影响匹配。

Task 5 覆盖 `util/qwen_ctc/llm.py`（Qwen3-ASR LLM 二遍解码器）：
16. ChatML 提示形态与特殊 token：14 + T + 6，首尾落在 `<|audio_start|>` /
    `<|audio_end|>`，末位落在 `<asr_text>`(151704)，停止符是显式解析的
    `{<|im_end|>, <|endoftext|>}`；
17. 1.7B 解码器能直接吃融合 encoder 的输出，并转出期望内容（断言 `開放時間` 子串，
    而非只断非空——提示顺序 / 音频注入 / pos4 错位时模型仍可能吐出「像样」的乱码）；
18. `n_prefill + n_predict > n_ctx` 时把上限收紧到 `n_ctx - n_prefill` 并留 WARNING；
19. 0.6B 解码器（n_embd=1024）能直接吃拆分 encoder 的输出（只断非空，避开跨尺寸差异）；
20. `warmup()` 正常路径不抛异常，且同一段音频连续两次生成结果一致（KV 清理生效）；
21. `warmup()` 遇真实错误时先记 ERROR 日志再原样抛出，绝不吞错（规格 §12.2）。

Task 6 覆盖 `util/qwen_ctc/engine.py`（三模式编排）：
22. 模式判定矩阵（规格 §7.2 每一行）+ 非法组合必须抛 `ValueError`；且 0.6B 前端的
    「无 CTC 头」检查必须先于「纯 CTC」分支（否则 `(True, False, True, False)` 会被
    误判成纯 CTC）；
23. `QwenCTCConfig` 的 7 个新字段默认值，以及 `create_qwen_ctc_engine` 暴露的 7 个
    关键字参数（全部有默认值）；
24. 引擎端到端三模式：纯 CTC / 两遍 / 纯 LLM 的 `mode`、`has_timestamps` 与输出形态
    （两遍 tokens 逐字符、时间戳单调且与 tokens 等长；纯 LLM 的 tokens/timestamps 为空）；
25. 静音不崩、>30s 长音频切块偏移连续、同一引擎连续两次识别结果一致；
26. 0.6B 拆分 encoder 无 CTC 头时自动降级纯 LLM（能正常启动）；解码器维度不符、
    0.6B 只配一端、纯 CTC 缺 CTC 头都必须显式抛错；
27. 配了解码器路径但 GGUF 不存在 = 硬错误（§7.4(2)）；纯 CTC 不加载 llama.cpp
    运行时（`bin/` 缺 DLL 也能起，§7.2 / §10.2）；两遍文本必须 == 纯 LLM 文本
    且 != 纯 CTC 文本（§12.3）。

Task 7 覆盖「配置面」（`util/config.py` + 四个模板）：
28. 四个模板都必须有 10 个新键，且派生只读键严格写成 `${model_paths.*}` 占位符、
    顺序固定在既有派生键之后 / `verbose` 之前、每个键都带一行 `#` 注释（两个可为空
    的 encoder 键的注释必须出现「留空」），四者同构；
29. `configs/default config.toml` 的整行注释数 = 333（323 + 10）；
30. `ModelPaths` / `QwenCTCArgs` 的 10 个新字段全部用 `.get()`（老配置不能 KeyError），
    默认值与规格 §6.1 / §6.3 一致，且运行时真值取自 `model_paths`（不能把模板里
    未展开的 `${...}` 占位符当成路径）；
31. 拿「删掉 10 个新键」的老配置喂给 `util/config.py` 必须能正常加载，且回退成
    纯 CTC（`decoder_gguf_path` 空、`enable_ctc` 仍为 True）。

Task 8 覆盖启动体检（`util/server/check_model.py`）：
32. `required_qwen_files` 必须按模式给出必需文件：融合 encoder 的纯 CTC / 两遍 /
    纯 LLM、0.6B 拆分 encoder 四种组合逐条断言；空字符串与 None 一律视为
    「未配置」不进列表（`decoder=""` 是合法的纯 CTC）；
33. 模式层面的硬错误必须早于引擎暴露：「0.6B 前后端拆分 + 解码器为空」、
    「既未配置解码器又禁用 CTC」、「0.6B 前后端只配一端」与
    「纯 CTC 缺 CTC 头 / tokens」，且合法组合不许误报；同时命中的两条错误
    必须把 0.6B 拆分那条排在前面（与引擎 `resolve_mode` 顺序一致）；
34. 缺失文件提示里的 §4.3 下载命令（1.7B 一条 + 0.6B 循环三条）必须逐字保留；
35. `_qwen_plan()` 的必需文件只能来自 `QwenCTCArgs`（引擎真正收到的配置），
    不能因为 `ModelPaths.qwen_llm_path` 有默认值就去要求引擎不用的 GGUF。

Task 9 覆盖服务端拼接 / 标点分支（`util/server/recognize_qwen_ctc.py`）：
36. 纯 LLM 模式按 `merge_by_text` 拼文本、不造 token / 时间戳、也不调标点模型；
37. 纯 LLM 模式跨片段累积（第二段必须接在缓存文本后，不能被 `"".join(空 tokens)`
    抹成空串）；同一 task_id 从 text 模式切到 token 模式时缓存文本同样不能被抹；
38. 两遍模式跳过标点模型（LLM 文本自带标点，再过一遍会出 `。。`），token / 时间戳
    照旧；中间段（`is_final=False`）同样不调标点且 `text_accu == text`；
39. 纯 CTC 模式行为不变：`Config.format_punc` 打开时仍必须调用标点模型。

需要模型文件 models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf
（0.6B 用例需要 models/qwen-ctc-aiinfra4-06b/qwen3_asr_llm.q4_k.gguf，缺失则跳过）。
"""

import contextlib
import logging
import sys
import tempfile
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# 直接 `python tests/qwen_two_pass_test.py` 运行时，脚本目录才是 sys.path[0]
sys.path.append(str(ROOT))

# 四个模板必须完全同构：仓库根 + configs/ 下的三个
TEMPLATES = [ROOT / "config.toml"] + sorted((ROOT / "configs").glob("* config.toml"))

DECODER_17B = ROOT / "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"
DECODER_06B = ROOT / "models/qwen-ctc-aiinfra4-06b/qwen3_asr_llm.q4_k.gguf"

MODEL_DIR_17B = ROOT / "models/qwen-ctc-aiinfra4"
MODEL_DIR_06B = ROOT / "models/qwen-ctc-aiinfra4-06b"
# 只有 1.7B 目录带 preprocessor_config.json；0.6B 的拆分 encoder 也复用它
PREPROCESSOR_DIR = MODEL_DIR_17B
ENCODER_17B = MODEL_DIR_17B / "Qwen3-ASR-Encoder.q4.onnx"
ENCODER_06B_FRONTEND = MODEL_DIR_06B / "qwen3_asr_encoder_frontend.int4.onnx"
ENCODER_06B_BACKEND = MODEL_DIR_06B / "qwen3_asr_encoder_backend.int4.onnx"
AUDIO_ZH = (
    ROOT
    / "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs/zh.wav"
)
AUDIO_EN = (
    ROOT
    / "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs/en.wav"
)
CTC_17B = MODEL_DIR_17B / "Qwen3-ASR-CTC.fp16.onnx"
TOKENS_17B = MODEL_DIR_17B / "tokens.txt"


@contextlib.contextmanager
def _capture_logs(name):
    """临时抓住某个 logger 的日志，避免用例故意制造 WARNING 时把控制台刷乱"""
    logger = logging.getLogger(name)
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler()
    old_level, old_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def test_llama_cpp_loads_decoder_and_reports_mrope():
    """解码器 GGUF 必须能加载，报 IMROPE，并接受 4 平面 M-RoPE 的 embd 批次"""
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


def test_llama_cpp_raises_on_truncated_gguf(tmp_path=None):
    """损坏的 GGUF 必须抛 LlamaLoadError（而不是返回 NULL 指针）"""
    from util.qwen_ctc import llama_cpp

    # 裸函数 runner 不会注入 tmp_path fixture；pytest 下仍按 fixture 传入。
    if tmp_path is None:
        with tempfile.TemporaryDirectory() as td:
            _assert_truncated_gguf_rejected(llama_cpp, Path(td) / "bad.gguf")
        return
    _assert_truncated_gguf_rejected(llama_cpp, Path(tmp_path) / "bad.gguf")


def _assert_truncated_gguf_rejected(llama_cpp, bad: Path) -> None:
    bad.write_bytes(b"GGUF" + b"\0" * 64)
    try:
        llama_cpp.Model(bad)
    except llama_cpp.LlamaLoadError:
        return
    raise AssertionError("损坏的 GGUF 必须抛 LlamaLoadError")


# --------------------------------------------------------------------------
# Task 2: gguf_embed.py —— 按需反量化 token embedding
# --------------------------------------------------------------------------


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


def test_token_embedding_rows_match_gguf_vocab_rows():
    """行必须按 vocab 索引从 GGUF 里精确取出（自造最小 GGUF 做逐值比对）"""
    from util.qwen_ctc.gguf_embed import TokenEmbedding

    with tempfile.TemporaryDirectory() as td:
        path, ref = _write_tiny_decoder_gguf(Path(td), n_vocab=8, n_embd=16)
        te = TokenEmbedding(path)
        try:
            assert te.n_embd == 16 and te.n_vocab == 8

            r = te.rows([5, 0])
            assert r.shape == (2, 16) and r.dtype == np.float32
            assert np.array_equal(r, ref[[5, 0]]), "取出的行必须是 GGUF 里同一 vocab 行的反量化值"

            # 重复 id 必须原样重复出现，且顺序按请求顺序
            d = te.rows([3, 3, 1])
            assert np.array_equal(d[0], d[1]) and np.array_equal(d[0], ref[3])
            assert np.array_equal(d[2], ref[1])

            # 空请求返回 [0, n_embd]，而不是抛异常
            e = te.rows([])
            assert e.shape == (0, 16) and e.dtype == np.float32
        finally:
            te.close()


def test_token_embedding_rejects_bad_ids_and_use_after_close():
    from util.qwen_ctc.gguf_embed import TokenEmbedding

    with tempfile.TemporaryDirectory() as td:
        path, _ref = _write_tiny_decoder_gguf(Path(td), n_vocab=8, n_embd=16)
        te = TokenEmbedding(path)
        try:
            for bad in (-1, 8, 1_000_000):
                try:
                    te.rows([bad])
                except (IndexError, ValueError):
                    pass
                else:
                    raise AssertionError(f"id={bad} 越界必须报错，不能静默取到别的行")
        finally:
            te.close()

        te.close()  # 幂等：重复 close 不得抛异常
        try:
            te.rows([0])
        except RuntimeError:
            pass
        else:
            raise AssertionError("close() 之后 rows() 必须报 RuntimeError")


def test_token_embedding_lru_is_bounded():
    """LRU 上限 4096 条；被淘汰的 id 再次请求必须重新反量化且值不变"""
    from util.qwen_ctc.gguf_embed import TokenEmbedding

    with tempfile.TemporaryDirectory() as td:
        path, ref = _write_tiny_decoder_gguf(Path(td), n_vocab=4100, n_embd=8)
        te = TokenEmbedding(path)
        try:
            assert te.rows(list(range(4100))).shape == (4100, 8)
            assert te.cached_rows == 4096, f"LRU 上限应为 4096，实际 {te.cached_rows}"
            assert np.array_equal(te.rows([4099]), ref[[4099]])
            assert np.array_equal(te.rows([0]), ref[[0]])
        finally:
            te.close()


def test_token_embedding_cache_file_is_written_and_reused():
    """`<gguf>.embd.npy` 写了能 mmap 复用；形状不符的旧缓存必须被忽略而不是抛错"""
    from util.qwen_ctc.gguf_embed import TokenEmbedding

    with tempfile.TemporaryDirectory() as td:
        path, ref = _write_tiny_decoder_gguf(Path(td), n_vocab=8, n_embd=16)

        te = TokenEmbedding(path)
        try:
            assert te.using_cache_file is False, "还没写缓存文件时不能声称在用"
            cache_path = te.write_cache()
            assert cache_path == te.cache_path
            assert cache_path.name == "tiny_decoder.gguf.embd.npy"
            assert cache_path.is_file()
            assert te.using_cache_file is True, "写完缓存后应该直接切到 mmap 路径"
            assert np.array_equal(te.rows([1, 6]), ref[[1, 6]])
        finally:
            te.close()

        te2 = TokenEmbedding(path)
        try:
            assert te2.using_cache_file is True, "已存在的 .embd.npy 必须被直接 mmap 复用"
            assert np.array_equal(te2.rows([1, 6]), ref[[1, 6]])
        finally:
            te2.close()

        # cache=False 时不走缓存文件，但取值仍然正确
        te3 = TokenEmbedding(path, cache=False)
        try:
            assert te3.using_cache_file is False
            assert np.array_equal(te3.rows([2]), ref[[2]])
        finally:
            te3.close()

        # 形状/ dtype 不符的旧缓存（来自别的模型）必须被忽略，且要留下 WARNING
        np.save(te.cache_path, np.zeros((3, 4), np.float32))
        with _capture_logs("util.qwen_ctc.gguf_embed") as records:
            te4 = TokenEmbedding(path)
            try:
                assert te4.using_cache_file is False, "形状不符的缓存必须被忽略"
                assert np.array_equal(te4.rows([2]), ref[[2]])
            finally:
                te4.close()
        assert any(r.levelno >= logging.WARNING for r in records), "忽略缓存时必须留一条 WARNING"


def test_token_embedding_rejects_gguf_without_embedding():
    """缺文件 / GGUF 里没有 token_embd.weight 时必须给出可读错误，不能半初始化"""
    from util.qwen_ctc.gguf_embed import TokenEmbedding

    with tempfile.TemporaryDirectory() as td:
        try:
            TokenEmbedding(Path(td) / "nope.gguf")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("缺失的 GGUF 必须抛 FileNotFoundError")

        other = _write_gguf(Path(td), "other.gguf", "output_norm.weight", np.zeros(4, np.float32))
        try:
            TokenEmbedding(other)
        except KeyError as exc:
            assert "token_embd.weight" in str(exc), f"错误信息必须点名缺哪个张量：{exc}"
        else:
            raise AssertionError("没有 token_embd.weight 的 GGUF 必须抛 KeyError")


def test_token_embedding_06b_dimensions():
    from util.qwen_ctc.gguf_embed import TokenEmbedding

    if not DECODER_06B.is_file():
        print("  (跳过：缺少 0.6B 解码器 GGUF)", flush=True)
        return

    te = TokenEmbedding(DECODER_06B)
    try:
        assert te.n_embd == 1024 and te.n_vocab == 151936
        r = te.rows([151644, 151669])
        assert r.shape == (2, 1024) and r.dtype == np.float32
        assert np.isfinite(r).all()
        assert not np.allclose(r[0], r[1])
    finally:
        te.close()


# --------------------------------------------------------------------------
# Task 3: encoder.py —— 融合 / 拆分双形态 encoder
# --------------------------------------------------------------------------


def _models_available() -> bool:
    """1.7B 融合 encoder 与特征提取器配置是否齐全"""
    return ENCODER_17B.is_file() and (
        PREPROCESSOR_DIR / "preprocessor_config.json"
    ).is_file()


def _split_models_available() -> bool:
    """0.6B 前后端拆分 encoder 与特征提取器配置是否齐全"""
    return (
        ENCODER_06B_FRONTEND.is_file()
        and ENCODER_06B_BACKEND.is_file()
        and (PREPROCESSOR_DIR / "preprocessor_config.json").is_file()
    )


def _read_wav(path: Path) -> np.ndarray:
    """16kHz 单声道 int16 WAV -> [-1, 1) float32"""
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1, f"测试音频必须是单声道：{path}"
        assert w.getframerate() == 16000, f"测试音频必须是 16kHz：{path}"
        frames = w.getnframes()
        return (
            np.frombuffer(w.readframes(frames), dtype=np.int16).astype(np.float32)
            / 32768.0
        )


def _make_fused_encoder():
    from util.qwen_ctc.encoder import FusedEncoder

    return FusedEncoder(
        str(ENCODER_17B),
        str(PREPROCESSOR_DIR),
        num_threads=6,
        provider="cpu",
    )


def _make_split_encoder():
    from util.qwen_ctc.encoder import SplitEncoder

    # 0.6B 目录没有 preprocessor_config.json，特征提取器复用 1.7B 目录的配置
    return SplitEncoder(
        str(ENCODER_06B_FRONTEND),
        str(ENCODER_06B_BACKEND),
        str(PREPROCESSOR_DIR),
        num_threads=6,
        provider="cpu",
    )


def test_valid_frames_boundaries():
    """13fps 换算的边界值：每 100 帧 mel 出 13 帧，尾巴按 8 帧一组"""
    from util.qwen_ctc.encoder import valid_frames

    assert valid_frames(0) == 0
    assert valid_frames(99) == 13          # leave=99 → (98)//8+1 = 13
    assert valid_frames(100) == 13         # leave=0
    assert valid_frames(101) == 14
    assert valid_frames(559) == 73
    assert valid_frames(3000) == 390


def test_resolve_providers_selects_cpu_or_dml():
    import onnxruntime as ort

    from util.qwen_ctc.encoder import resolve_providers

    assert resolve_providers(ort, "cpu") == ["CPUExecutionProvider"]
    got = resolve_providers(ort, "dml")
    if "DmlExecutionProvider" in ort.get_available_providers():
        assert got == ["DmlExecutionProvider", "CPUExecutionProvider"]
    else:
        assert got == ["CPUExecutionProvider"], "DML 不可用时必须静默回退 CPU"


def test_fused_encoder_shape():
    """1.7B 融合 encoder：559 帧 mel -> [73, 2048]"""
    if not _models_available():
        print("  (跳过：缺少 1.7B 融合 encoder 模型)", flush=True)
        return

    enc = _make_fused_encoder()
    try:
        assert enc.output_dim == 2048
        out = enc.encode(_read_wav(AUDIO_ZH))
        assert out.shape == (73, 2048), f"实际 {out.shape}"
        assert out.dtype == np.float32
        assert np.isfinite(out).all()
    finally:
        enc.close()


def test_split_encoder_shape():
    """0.6B 拆分 encoder：559 帧 mel -> [73, 1024]"""
    if not _split_models_available():
        print("  (跳过：缺少 0.6B 拆分 encoder 模型)", flush=True)
        return

    enc = _make_split_encoder()
    try:
        assert enc.output_dim == 1024
        out = enc.encode(_read_wav(AUDIO_ZH))
        assert out.shape == (73, 1024), f"实际 {out.shape}"
        assert out.dtype == np.float32
        assert np.isfinite(out).all()
    finally:
        enc.close()


def test_fused_encoder_matches_manual_pipeline():
    """encode 必须等价于「真实长度 + 补零 3000 + feature_length + 截断」"""
    if not _models_available():
        print("  (跳过：缺少 1.7B 融合 encoder 模型)", flush=True)
        return

    import onnxruntime as ort
    from transformers import WhisperFeatureExtractor

    from util.qwen_ctc.encoder import valid_frames

    audio = _read_wav(AUDIO_ZH)
    enc = _make_fused_encoder()
    try:
        fe = WhisperFeatureExtractor.from_pretrained(str(PREPROCESSOR_DIR))
        mel = fe(
            audio, sampling_rate=16000, padding=False, return_tensors="np"
        ).input_features[0]
        t = mel.shape[1]
        assert t == 559, f"zh.wav 应取到 559 帧 mel，实际 {t}"

        padded = np.zeros((mel.shape[0], 3000), dtype=np.float32)
        padded[:, :t] = mel
        so = ort.SessionOptions()
        so.intra_op_num_threads = 0
        sess = ort.InferenceSession(
            str(ENCODER_17B), sess_options=so, providers=["CPUExecutionProvider"]
        )
        ref = sess.run(
            None,
            {
                "input_features": padded,
                "feature_length": np.array([t], np.int64),
            },
        )[0]
        ref = ref[: valid_frames(t)].astype(np.float32)

        got = enc.encode(audio)
        assert got.shape == ref.shape == (73, 2048)
        diff = float(np.max(np.abs(got - ref)))
        assert np.allclose(
            got, ref, rtol=1e-4, atol=1e-4
        ), f"与手工流水线不一致，max|diff|={diff}"
    finally:
        enc.close()


def test_split_encoder_matches_manual_pipeline():
    """encode 必须等价于「100 帧切块 + 末块补零 + 拼接 + 截断 + 4D 全 1 mask」"""
    if not _split_models_available():
        print("  (跳过：缺少 0.6B 拆分 encoder 模型)", flush=True)
        return

    import onnxruntime as ort
    from transformers import WhisperFeatureExtractor

    from util.qwen_ctc.encoder import valid_frames

    audio = _read_wav(AUDIO_ZH)
    enc = _make_split_encoder()
    try:
        fe = WhisperFeatureExtractor.from_pretrained(str(PREPROCESSOR_DIR))
        mel = fe(
            audio, sampling_rate=16000, padding=False, return_tensors="np"
        ).input_features[0]
        t = mel.shape[1]
        n_chunks = (t + 99) // 100
        padded = np.zeros((mel.shape[0], n_chunks * 100), dtype=np.float32)
        padded[:, :t] = mel

        so = ort.SessionOptions()
        so.intra_op_num_threads = 0
        front = ort.InferenceSession(
            str(ENCODER_06B_FRONTEND), sess_options=so, providers=["CPUExecutionProvider"]
        )
        back = ort.InferenceSession(
            str(ENCODER_06B_BACKEND), sess_options=so, providers=["CPUExecutionProvider"]
        )
        hidden = np.concatenate(
            [
                front.run(
                    None,
                    {"chunk_mel": padded[:, i * 100 : (i + 1) * 100][None]},
                )[0][0]
                for i in range(n_chunks)
            ],
            axis=0,
        )
        n = valid_frames(t)
        assert hidden.shape == (n_chunks * 13, 896), f"实际 {hidden.shape}"
        hidden = hidden[:n]
        mask = np.ones((1, 1, n, n), dtype=np.float32)
        ref = back.run(
            None, {"hidden_states": hidden[None], "attention_mask": mask}
        )[0][0].astype(np.float32)

        got = enc.encode(audio)
        assert got.shape == ref.shape == (73, 1024)
        diff = float(np.max(np.abs(got - ref)))
        assert np.allclose(
            got, ref, rtol=1e-4, atol=1e-4
        ), f"与手工流水线不一致，max|diff|={diff}"
    finally:
        enc.close()


def test_encoder_close_is_idempotent():
    if not _models_available():
        print("  (跳过：缺少 1.7B 融合 encoder 模型)", flush=True)
        return

    enc = _make_fused_encoder()
    enc.close()
    enc.close()  # 幂等：重复 close 不得抛异常
    try:
        enc.encode(np.zeros(1600, dtype=np.float32))
    except RuntimeError:
        pass
    else:
        raise AssertionError("close() 之后 encode() 必须报 RuntimeError")


def test_fused_encoder_rejects_audio_beyond_bucket():
    """超过 30s 必须显式报错：融合 encoder 是按 3000 帧桶导出的，静默截断会丢字"""
    if not _models_available():
        print("  (跳过：缺少 1.7B 融合 encoder 模型)", flush=True)
        return

    enc = _make_fused_encoder()
    try:
        try:
            enc.encode(np.zeros(16000 * 31, dtype=np.float32))
        except ValueError as exc:
            assert "30" in str(exc) or "3000" in str(exc), (
                f"错误信息要说明 30 秒桶：{exc}"
            )
        else:
            raise AssertionError("超过 30s 的音频必须抛 ValueError")
    finally:
        enc.close()


def test_split_encoder_rejects_audio_beyond_bucket():
    """超过 30s 必须显式报错：拆分 encoder 复用 1.7B 的 30 秒预处理器配置"""
    if not _split_models_available():
        print("  (跳过：缺少 0.6B 拆分 encoder 模型)", flush=True)
        return

    enc = _make_split_encoder()
    try:
        try:
            enc.encode(np.zeros(16000 * 31, dtype=np.float32))
        except ValueError as exc:
            assert "30" in str(exc), f"错误信息要说明 30 秒桶：{exc}"
        else:
            raise AssertionError("超过 30s 的音频必须抛 ValueError")
    finally:
        enc.close()


# --------------------------------------------------------------------------
# Task 4: align.py —— CTC 字级时间戳对齐到 LLM 文本
# --------------------------------------------------------------------------


def test_align_length_always_matches_llm_text():
    from util.qwen_ctc.align import align_ctc_to_llm

    ts = align_ctc_to_llm(
        list("開放時間早上九點"), [0.1 * i for i in range(8)], "開放時間：早上九點。", 4.0
    )
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

    ts = align_ctc_to_llm(
        list("一二三四五"), [0.2, 0.4, 0.6, 0.8, 1.0], "ABCDE12345", 6.0
    )
    assert len(ts) == 10 and all(ts[i] <= ts[i + 1] for i in range(9))


def test_align_empty_text_returns_empty():
    """空 LLM 文本必须返回空列表（长度严格等于 len(text)），不能抛异常"""
    from util.qwen_ctc.align import align_ctc_to_llm

    assert align_ctc_to_llm(list("abc"), [0.0, 1.0, 2.0], "", 3.0) == []
    assert align_ctc_to_llm([], [], "", 0.0) == []


def test_align_interpolates_missing_punctuation():
    """LLM 多出来的标点没有 CTC 锚点，必须在两侧锚点之间线性插值"""
    from util.qwen_ctc.align import align_ctc_to_llm

    ts = align_ctc_to_llm(list("ab"), [1.0, 3.0], "a：b", 4.0)
    assert len(ts) == 3
    assert abs(ts[0] - 1.0) < 1e-6 and abs(ts[2] - 3.0) < 1e-6
    assert abs(ts[1] - 2.0) < 1e-6, f"标点应插值到 2.0，实际 {ts[1]}"


def test_align_is_case_insensitive_and_fullwidth_normalized():
    """比较前做 casefold + 全角转半角归一，不能因为大小写/全角就丢掉锚点"""
    from util.qwen_ctc.align import align_ctc_to_llm

    assert align_ctc_to_llm(list("AB"), [0.5, 2.5], "ab", 3.0) == [0.5, 2.5]
    assert align_ctc_to_llm(list("ab"), [0.5, 2.5], "ａｂ", 3.0) == [0.5, 2.5]


def test_align_mixed_cjk_latin_and_length_mismatch():
    """中英混排 + 长度悬殊：长度正确、单调不减、落在 CTC 时间范围内"""
    from util.qwen_ctc.align import align_ctc_to_llm

    ctc = list("你好世界")
    starts = [0.4, 0.9, 1.6, 2.4]
    ts = align_ctc_to_llm(ctc, starts, "你好, world! 世界。", 3.0)
    assert len(ts) == len("你好, world! 世界。")
    assert all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1))
    assert ts[0] >= 0.0 and ts[-1] <= max(starts) + 1e-6, f"越界：{ts}"

    # LLM 把整段都改写成完全不同的字（全不匹配）也必须给出等长单调结果
    ts2 = align_ctc_to_llm(ctc, starts, "x" * 40, 3.0)
    assert len(ts2) == 40
    assert all(ts2[i] <= ts2[i + 1] for i in range(39))
    assert ts2[0] >= 0.0 and ts2[-1] <= max(starts) + 1e-6


def test_align_prefix_is_not_flattened_to_zero():
    """LLM 前面多出一串 CTC 覆盖不到的字时要在 [0, 首锚点] 内均分，不能全挤到 0.0"""
    from util.qwen_ctc.align import align_ctc_to_llm

    ts = align_ctc_to_llm(list("一二三四五"), [0.2, 0.4, 0.6, 0.8, 1.0], "ABCDE12345", 6.0)
    assert ts[0] == 0.0
    assert 0.0 < ts[1] < ts[2] < ts[3] < ts[4] <= 0.2 + 1e-9, f"前缀被压平了：{ts}"


# --------------------------------------------------------------------------
# Task 5: llm.py —— Qwen3-ASR LLM 二遍解码器
# --------------------------------------------------------------------------


def _llm_models_available() -> bool:
    """1.7B 解码器 + 融合 encoder 是否齐全（LLM 生成用例需要两者）"""
    return DECODER_17B.is_file() and _models_available() and AUDIO_ZH.is_file()


def _make_llm_decoder(gguf=DECODER_17B, **kwargs):
    from util.qwen_ctc.llm import QwenLLMDecoder

    return QwenLLMDecoder(str(gguf), **kwargs)


def test_llm_prompt_special_tokens():
    """ChatML 提示必须按实测形态拼：14 + T + 6，且首尾落在 audio 分隔符上"""
    dec = _make_llm_decoder()
    try:
        assert dec.n_embd == 2048
        assert dec.prefix_ids[-1] == 151669, "prefix 必须落在 <|audio_start|>"
        assert dec.suffix_ids[0] == 151670, "suffix 必须以 <|audio_end|> 开始"
        assert dec.stop_ids == {151645, 151643}
        assert len(dec.prefix_ids) == 14 and len(dec.suffix_ids) == 6
        # suffix 必须收在 <asr_text>：提示顺序错（suffix 只留 audio_end/im_end/im_start）
        # 时模型依旧能吐出「像样」的文本，只有这个断言能钉住 pos4 布局里的 asr_text 位
        assert dec.suffix_ids[-1] == 151704, "suffix 必须收在 <asr_text>(151704)"
        # 停止符不能拿 GGUF 的 eos 元数据凑数：两个都要显式解析出来
        assert 151645 in dec.stop_ids and 151643 in dec.stop_ids
    finally:
        dec.close()


def test_llm_generates_transcript_from_encoder_output():
    """1.7B 必须真的转出这段中文音频的内容（只断非空会放过提示顺序/音频注入错位）"""
    if not _llm_models_available():
        print("  (跳过：缺少 1.7B 解码器 / encoder / 测试音频)", flush=True)
        return

    dec = _make_llm_decoder()
    enc = _make_fused_encoder()
    try:
        text = dec.generate(enc.encode(_read_wav(AUDIO_ZH)))
        assert text, "生成结果不得为空"
        assert "<|im_end|>" not in text and "<|im_start|>" not in text
        # 本机实测（T=0 贪心，可复现）： '開放時間：早上九點至下午五點。'
        # 只钉稳定核心子串：完全相等对 llama.cpp 版本/量化后端的数值差异太脆
        assert "開放時間" in text, f"1.7B 转写缺失期望内容，实际 {text!r}"
        print(f"  LLM 文本: {text!r}", flush=True)
    finally:
        dec.close()
        enc.close()


def test_llm_predict_is_clamped_to_context():
    """n_prefill + n_predict 超过 n_ctx 时必须收紧上限并留 WARNING，而非让 llama 报错"""
    with _capture_logs("util.qwen_ctc.llm") as records:
        dec = _make_llm_decoder(n_ctx=512, n_predict=100000)
        try:
            assert dec.effective_n_predict(410) == 512 - 410
        finally:
            dec.close()
    assert any(r.levelno >= logging.WARNING for r in records), "收紧上限时必须留一条 WARNING"


def test_llm_generates_transcript_06b():
    """0.6B 解码器（n_embd=1024）也必须能直接吃 0.6B 拆分 encoder 的输出"""
    if not (DECODER_06B.is_file() and _split_models_available() and AUDIO_ZH.is_file()):
        print("  (跳过：缺少 0.6B 解码器 / 拆分 encoder)", flush=True)
        return

    dec = _make_llm_decoder(DECODER_06B)
    enc = _make_split_encoder()
    try:
        assert dec.n_embd == 1024
        text = dec.generate(enc.encode(_read_wav(AUDIO_ZH)))
        assert text, "0.6B 生成结果不得为空"
        assert "<|im_end|>" not in text
        print(f"  LLM 文本(0.6B): {text!r}", flush=True)
    finally:
        dec.close()
        enc.close()


def test_llm_warmup_and_repeat_generate_are_stable():
    """正常路径下 warmup 不得抛异常；两次生成必须一致（KV 清理生效）"""
    if not _llm_models_available():
        print("  (跳过：缺少 1.7B 解码器 / encoder / 测试音频)", flush=True)
        return

    dec = _make_llm_decoder()
    enc = _make_fused_encoder()
    try:
        dec.warmup()  # 吞掉首次 prefill 的图 reserve 开销
        audio = enc.encode(_read_wav(AUDIO_ZH))
        first = dec.generate(audio)
        second = dec.generate(audio)
        assert first and first == second, "同一段音频两次生成结果必须一致"
    finally:
        dec.close()
        enc.close()


def test_llm_warmup_propagates_real_errors():
    """预热是启动调用：遇真实错误必须「先记日志、再抛出」，不能吞（规格 §12.2）"""
    if not _llm_models_available():
        print("  (跳过：缺少 1.7B 解码器 / encoder / 测试音频)", flush=True)
        return

    dec = _make_llm_decoder()
    try:
        def _boom(_full):
            raise RuntimeError("模拟预热失败")

        # 实例属性遮蔽绑定的方法：self._prefill(full) 会按 _boom(full) 调用
        dec._prefill = _boom
        with _capture_logs("util.qwen_ctc.llm") as records:
            try:
                dec.warmup()
            except RuntimeError as exc:
                assert "模拟预热失败" in str(exc), f"抛出的不是原始错误：{exc}"
            else:
                raise AssertionError("warmup 必须把真实错误抛出，不能吞")
        assert any(r.levelno >= logging.ERROR for r in records), "抛错前必须先记一条 ERROR 日志"
    finally:
        dec.close()


# --------------------------------------------------------------------------
# Task 6: engine.py —— 三模式编排（纯 CTC / 两遍 / 纯 LLM）
# --------------------------------------------------------------------------

_NEW_CONFIG_FIELDS = (
    "decoder_gguf_path",
    "encoder_frontend_path",
    "encoder_backend_path",
    "enable_ctc",
    "llm_n_ctx",
    "llm_n_threads",
    "llm_n_predict",
)


def _engine_models_available() -> bool:
    """纯 CTC / 两遍都能跑：融合 encoder + CTC 头 + tokens + 测试音频"""
    return _models_available() and CTC_17B.is_file() and TOKENS_17B.is_file()


def _long_audio(min_sec: float = 31.0) -> np.ndarray:
    """把 zh.wav 重复拼到 > min_sec 秒，只为跨过 30 s 切段边界"""
    audio = _read_wav(AUDIO_ZH)
    reps = max(1, int(np.ceil(min_sec * 16000.0 / max(len(audio), 1))))
    return np.concatenate([audio] * reps).astype(np.float32)


def _make_engine(
    decoder=DECODER_17B,
    enable_ctc: bool = True,
    encoder=ENCODER_17B,
    ctc=CTC_17B,
    frontend="",
    backend="",
    **kwargs,
):
    """按 create_qwen_ctc_engine 的真实关键字建引擎（decoder 传空串 = 纯 CTC）"""
    from util.qwen_ctc.engine import create_qwen_ctc_engine

    return create_qwen_ctc_engine(
        encoder_onnx_path=str(encoder),
        ctc_onnx_path=str(ctc) if ctc else "",
        tokens_path=str(TOKENS_17B),
        preprocessor_path=str(PREPROCESSOR_DIR),
        decoder_gguf_path=str(decoder) if decoder else "",
        encoder_frontend_path=str(frontend) if frontend else "",
        encoder_backend_path=str(backend) if backend else "",
        enable_ctc=enable_ctc,
        num_threads=6,
        **kwargs,
    )


def test_engine_config_exposes_new_fields_and_factory_kwargs():
    """7 个新配置字段要有默认值，create_qwen_ctc_engine 要原样暴露这 7 个关键字"""
    import inspect

    from util.qwen_ctc.engine import QwenCTCConfig, create_qwen_ctc_engine

    cfg = QwenCTCConfig(
        encoder_onnx_path="e.onnx",
        ctc_onnx_path="c.onnx",
        tokens_path="tokens.txt",
        preprocessor_path="pp",
    )
    assert cfg.decoder_gguf_path == ""
    assert cfg.encoder_frontend_path == ""
    assert cfg.encoder_backend_path == ""
    assert cfg.enable_ctc is True
    assert cfg.llm_n_ctx == 4096
    assert cfg.llm_n_threads == 6
    assert cfg.llm_n_predict == 256

    params = inspect.signature(create_qwen_ctc_engine).parameters
    for name in _NEW_CONFIG_FIELDS:
        assert name in params, f"create_qwen_ctc_engine 缺少关键字参数 {name}"
        assert params[name].default is not inspect.Parameter.empty, f"{name} 必须有默认值"


def test_engine_resolve_mode_matrix():
    """规格 §7.2 的模式矩阵逐行断言，顺序（split 检查先行）必须错不开"""
    from util.qwen_ctc.engine import resolve_mode

    assert resolve_mode(False, True, True, True) == "two_pass"
    assert resolve_mode(False, True, True, False) == "llm", "CTC 头不可用时降级纯 LLM"
    assert resolve_mode(False, True, False, False) == "llm"
    assert resolve_mode(False, True, False, True) == "llm", "enable_ctc=False 时 CTC 头不该被用"
    assert resolve_mode(False, False, True, True) == "ctc"
    assert resolve_mode(True, True, True, False) == "llm"
    assert resolve_mode(True, True, False, True) == "llm"
    assert resolve_mode(True, True, True, True) == "llm", "0.6B 拆分 encoder 没有 CTC 头，必须降级"


def test_engine_resolve_mode_rejects_impossible_combos():
    """没有任何推理路径的组合必须抛 ValueError，且信息带可操作的提示"""
    from util.qwen_ctc.engine import resolve_mode

    try:
        resolve_mode(True, False, True, False)
    except ValueError as exc:
        msg = str(exc)
        assert "0.6B" in msg and "CTC" in msg, f"0.6B 缺解码器应提示没有 CTC 头：{msg}"
    else:
        raise AssertionError("0.6B 拆分 encoder 没配解码器时必须抛错")

    try:
        resolve_mode(False, False, False, False)
    except ValueError as exc:
        assert "未配置解码器" in str(exc), f"应提示未配置解码器：{exc}"
    else:
        raise AssertionError("既没有解码器又禁用 CTC 时必须抛错")


def test_engine_rejects_missing_decoder_file():
    """配了解码器路径但文件不存在 = 硬错误（规格 §7.4(2)），不许静默降级成纯 CTC

    `_llm=None` 会让「想要两遍」的用户拿到无标点的 CTC 文本，`has_timestamps`
    还是 True，只有一条 WARNING —— 所以必须在 initialize() 里就抛。
    """
    missing = MODEL_DIR_17B / "nope.gguf"
    assert not missing.is_file(), f"这条用例要求该路径确实不存在：{missing}"

    try:
        _make_engine(decoder=missing, enable_ctc=True)
    except ValueError as exc:
        msg = str(exc)
        assert str(missing) in msg, f"硬错误信息必须带缺失路径：{msg}"
        assert "qwen_llm_path" in msg, f"应告诉用户是哪个配置键：{msg}"
        assert "纯 CTC" in msg, f"应给出「留空即纯 CTC」的出路：{msg}"
        print(f"  [硬错误] {msg}", flush=True)
    else:
        raise AssertionError("解码器 GGUF 不存在时必须抛 ValueError，不能静默降级")


def test_engine_pure_ctc_needs_no_llama_runtime():
    """纯 CTC 不需要 llama.cpp：bin/ 缺 DLL 也必须能起（规格 §7.2 / §10.2）

    纯 CTC 只需要 encoder + CTC 头 + tokens + preprocessor；无条件 `init_lib()`
    会让一个完全没有 LLM 的部署直接起不来。
    """
    if not _engine_models_available():
        print("  (跳过：缺少 CTC 头 / tokens / 融合 encoder / 测试音频)", flush=True)
        return

    from util.qwen_ctc import llama_cpp

    orig_bin, orig_init = llama_cpp._BIN_DIR, llama_cpp.init_lib
    # init_lib() 成功加载后是幂等的（前面的用例已经把 DLL 载进来了），单改
    # `_BIN_DIR` 在进程内观察不到；再把它换成「真的会失败」的桩，这条用例才
    # 真能抓住「纯 CTC 又去加载 llama.cpp」的回归。
    llama_cpp._BIN_DIR = Path("no-such-llama-bin-dir")

    def _boom():
        raise RuntimeError(f"找不到 llama.cpp 二进制目录: {llama_cpp._BIN_DIR}")

    llama_cpp.init_lib = _boom
    try:
        eng = _make_engine(decoder="", enable_ctc=True)
        try:
            assert eng.mode == "ctc", f"纯 CTC 模式判定错了：{eng.mode}"
            res = eng.transcribe(_read_wav(AUDIO_ZH))
            assert res.text, "纯 CTC 必须出文本"
            assert len(res.tokens) == len(res.timestamps)
        finally:
            eng.cleanup()
    finally:
        llama_cpp._BIN_DIR = orig_bin
        llama_cpp.init_lib = orig_init


def test_engine_modes_end_to_end():
    """纯 CTC / 两遍 / 纯 LLM 的 mode、has_timestamps 与输出形态"""
    if not _engine_models_available() or not DECODER_17B.is_file():
        print("  (跳过：缺少 CTC 头 / 解码器 / tokens / 测试音频)", flush=True)
        return

    audio = _read_wav(AUDIO_ZH)
    ctc_text = ""
    two_pass_text = ""
    llm_text = ""

    started = time.perf_counter()
    eng = _make_engine(decoder="", enable_ctc=True)
    try:
        assert eng.mode == "ctc", f"纯 CTC 模式判定错了：{eng.mode}"
        assert eng.has_timestamps is True
        res = eng.transcribe(audio)
        ctc_text = res.text
        assert res.text, "纯 CTC 必须出文本"
        assert len(res.tokens) == len(res.timestamps)
        assert "".join(res.tokens) == res.text
        print(f"  [ctc] {time.perf_counter() - started:.2f}s 文本: {res.text!r}", flush=True)
    finally:
        eng.cleanup()

    started = time.perf_counter()
    eng = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        assert eng.mode == "two_pass", f"两遍模式判定错了：{eng.mode}"
        assert eng.has_timestamps is True
        res = eng.transcribe(audio)
        two_pass_text = res.text
        assert res.text, "两遍模式必须出文本"
        assert len(res.tokens) == len(res.text), "两遍模式 tokens 必须是逐字符拆分"
        assert "".join(res.tokens) == res.text
        assert len(res.timestamps) == len(res.tokens)
        assert all(
            res.timestamps[i] <= res.timestamps[i + 1]
            for i in range(len(res.timestamps) - 1)
        ), "两遍模式时间戳必须单调不减"
        print(f"  [two_pass] {time.perf_counter() - started:.2f}s 文本: {res.text!r}", flush=True)
    finally:
        eng.cleanup()

    started = time.perf_counter()
    eng = _make_engine(decoder=DECODER_17B, enable_ctc=False)
    try:
        assert eng.mode == "llm", f"纯 LLM 模式判定错了：{eng.mode}"
        assert eng.has_timestamps is False
        res = eng.transcribe(audio)
        llm_text = res.text
        assert res.text, "纯 LLM 必须出文本"
        assert res.tokens == [] and res.timestamps == [], "纯 LLM 不带时间戳"
        print(f"  [llm] {time.perf_counter() - started:.2f}s 文本: {res.text!r}", flush=True)
    finally:
        eng.cleanup()

    # 规格 §12.3：两遍文本必须与纯 LLM 文本逐字符一致。少了这条，`_decode_two_pass`
    # 的「LLM 抛异常 → 回退该段 CTC 文本」会让「每段都回退」也通过上面全部形态断言
    # （tokens 逐字符、时间戳等长又单调，纯 CTC 文本同样满足）。
    assert two_pass_text == llm_text, (
        "两遍文本必须与纯 LLM 文本一致（§12.3）：\n"
        f"  two_pass={two_pass_text!r}\n  llm     ={llm_text!r}\n"
        "  不一致说明两遍里 LLM 二遍没真正生效（可能每段都回退了 CTC 首遍）"
    )
    assert two_pass_text != ctc_text, (
        "两遍文本不应等于纯 CTC 文本，否则分辨不出「跑了 LLM 二遍」还是「回退 CTC」："
        f"{two_pass_text!r}"
    )


def test_engine_silence_does_not_crash():
    """静音段没有 CTC 锚点，两遍模式也不能崩（时间戳退化由 align 兜底）"""
    if not _engine_models_available() or not DECODER_17B.is_file():
        print("  (跳过：缺少 CTC 头 / 解码器 / tokens)", flush=True)
        return

    eng = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        assert eng.mode == "two_pass"
        res = eng.transcribe(np.zeros(16000, np.float32))
        assert isinstance(res.text, str)
        assert len(res.tokens) == len(res.timestamps)
        assert "".join(res.tokens) == res.text
    finally:
        eng.cleanup()


def test_engine_long_audio_offsets_are_continuous():
    """>30 s 音频的第二段必须整体后移 30 s（两遍模式的 offset 也要加对）"""
    if not _engine_models_available() or not DECODER_17B.is_file():
        print("  (跳过：缺少 CTC 头 / 解码器 / tokens / 测试音频)", flush=True)
        return

    audio = _long_audio(31.0)
    assert len(audio) / 16000.0 > 30.0
    duration = len(audio) / 16000.0
    eng = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        res = eng.transcribe(audio)
        assert res.text, "两遍模式长音频必须出文本"
        assert len(res.tokens) == len(res.timestamps)
        assert max(res.timestamps) > 30.0, f"第二段起始时间没加上偏移：max={max(res.timestamps)}"
        assert max(res.timestamps) <= duration + 0.5, (
            f"时间戳不得超过音频时长太多：max={max(res.timestamps)}, duration={duration}"
        )
        assert all(
            res.timestamps[i] <= res.timestamps[i + 1]
            for i in range(len(res.timestamps) - 1)
        ), "跨段拼起来的时间戳也必须单调不减"
    finally:
        eng.cleanup()


def test_engine_repeat_calls_are_stable():
    """同一个引擎连着识别两次必须一致（两遍模式的 KV 缓存要清干净）"""
    if not _engine_models_available() or not DECODER_17B.is_file():
        print("  (跳过：缺少 CTC 头 / 解码器 / tokens / 测试音频)", flush=True)
        return

    audio = _read_wav(AUDIO_ZH)
    eng = _make_engine(decoder=DECODER_17B, enable_ctc=True)
    try:
        first = eng.transcribe(audio)
        second = eng.transcribe(audio)
        assert first.text == second.text, f"连续两次识别不一致：\n{first.text!r}\n{second.text!r}"
        assert first.timestamps == second.timestamps
    finally:
        eng.cleanup()


def test_engine_06b_without_ctc_head_degrades_to_llm():
    """0.6B 的 encoder 输出 1024 维、没有匹配的 CTC 头 → 必须降级纯 LLM 而不是启动失败"""
    if not (
        DECODER_06B.is_file()
        and _split_models_available()
        and AUDIO_ZH.is_file()
    ):
        print("  (跳过：缺少 0.6B 解码器 / 拆分 encoder / 测试音频)", flush=True)
        return

    eng = _make_engine(
        decoder=DECODER_06B,
        encoder=ENCODER_17B,
        frontend=ENCODER_06B_FRONTEND,
        backend=ENCODER_06B_BACKEND,
        ctc=CTC_17B,
        enable_ctc=True,
    )
    try:
        assert eng.mode == "llm", f"0.6B 缺 CTC 头必须降级纯 LLM，实际 {eng.mode}"
        assert eng.has_timestamps is False
        res = eng.transcribe(_read_wav(AUDIO_ZH))
        assert res.text, "降级后的纯 LLM 仍必须出文本"
        assert res.tokens == [] and res.timestamps == []
        print(f"  [0.6B→llm] 文本: {res.text!r}", flush=True)
    finally:
        eng.cleanup()


def test_engine_rejects_decoder_encoder_dim_mismatch():
    """0.6B(1024) encoder 配 1.7B(2048) 解码器必须硬失败，信息要带两侧维度"""
    if not (DECODER_17B.is_file() and _split_models_available()):
        print("  (跳过：缺少 0.6B 拆分 encoder / 1.7B 解码器)", flush=True)
        return

    try:
        _make_engine(
            decoder=DECODER_17B,
            enable_ctc=False,
            frontend=ENCODER_06B_FRONTEND,
            backend=ENCODER_06B_BACKEND,
        )
    except ValueError as exc:
        msg = str(exc)
        assert "2048" in msg and "1024" in msg, f"维度冲突信息要带两侧数值：{msg}"
    else:
        raise AssertionError("解码器 n_embd ≠ encoder 输出维度时必须抛 ValueError")


def test_engine_rejects_half_split_encoder():
    """0.6B 前后端只配一端 = 无法装配 encoder，必须硬失败"""
    if not _split_models_available():
        print("  (跳过：缺少 0.6B 拆分 encoder)", flush=True)
        return

    try:
        _make_engine(
            decoder="",
            enable_ctc=True,
            frontend=ENCODER_06B_FRONTEND,
            backend="",
        )
    except ValueError as exc:
        assert "成对" in str(exc) or "前后端" in str(exc), f"应提示前后端要成对配置：{exc}"
    else:
        raise AssertionError("只配一半 0.6B encoder 时必须抛 ValueError")


def test_engine_pure_ctc_requires_ctc_head():
    """纯 CTC 模式没有 CTC 头就没有推理路径，必须启动时硬失败"""
    if not _models_available():
        print("  (跳过：缺少融合 encoder / 测试音频)", flush=True)
        return

    try:
        _make_engine(decoder="", enable_ctc=True, ctc="")
    except ValueError as exc:
        assert "CTC" in str(exc), f"应提示纯 CTC 模式缺少 CTC 头：{exc}"
    else:
        raise AssertionError("纯 CTC 模式缺 CTC 头时必须抛 ValueError")


# --------------------------------------------------------------------------
# Task 7: 配置面 —— util/config.py + 四个模板
# --------------------------------------------------------------------------

# 四个模板里新增的 10 个叶子键（规格 §6.1）
_NEW_MODEL_PATH_KEYS = (
    "qwen_llm_path",
    "qwen_ctc_encoder_frontend_path",
    "qwen_ctc_encoder_backend_path",
)
# 派生只读键 -> 它必须指向的同名 model_paths 键（GUI 一致性断言依赖这个映射）
_NEW_DERIVED_KEYS = {
    "decoder_gguf_path": "qwen_llm_path",
    "encoder_frontend_path": "qwen_ctc_encoder_frontend_path",
    "encoder_backend_path": "qwen_ctc_encoder_backend_path",
}
_NEW_CTX_KEYS = ("enable_ctc", "llm_n_ctx", "llm_n_threads", "llm_n_predict")


def _template_comment_after(text: str, key: str, header: str = "") -> str:
    """取模板里 `key = ...` 下一行的整行注释，并断言它确实存在（键 → 注释 → 空行）

    传了 header 就只在那一节里找 —— `[funasr_args]` 里也有同名的 `decoder_gguf_path`
    和 `enable_ctc`，全文搜索会错取到别人的注释。
    """
    if header:
        lines = _section_lines(text, header)
    else:
        lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith(f"{key} =") or line.startswith(f"{key}="):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            assert nxt.startswith("#"), f"键 {key} 后面必须紧跟一行 # 注释，实际 {nxt!r}"
            return nxt
    raise AssertionError(f"模板里找不到键 {key}" + (f"（节 {header}）" if header else ""))


def _section_lines(text: str, header: str) -> list:
    """某一节（到下一个 `[...]` 之前）里的非空行，保持原顺序"""
    out, inside = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            inside = s == header
            continue
        if inside and s:
            out.append(s)
    return out


def _qwen_model_paths_tail(text: str) -> list:
    """`[model_paths]` 里从第一个 qwen_ctc 键到节尾的原文片段（比较同构用）"""
    lines = _section_lines(text, "[model_paths]")
    for i, s in enumerate(lines):
        if s.startswith("qwen_ctc_encoder_path ="):
            return lines[i:]
    raise AssertionError("[model_paths] 里找不到 qwen_ctc_encoder_path")


def _blank_line_after_key(text: str, key: str) -> bool:
    """`key = ...` → 一行 # 注释 → 空行；同名键有多处时每一处都要满足"""
    lines = text.splitlines()
    hits = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not (s.startswith(f"{key} =") or s.startswith(f"{key}=")):
            continue
        hits += 1
        comment = lines[i + 1].strip() if i + 1 < len(lines) else ""
        blank = lines[i + 2].strip() if i + 2 < len(lines) else ""
        if not comment.startswith("#") or blank != "":
            return False
    assert hits, f"模板里找不到键 {key}"
    return True


def test_templates_have_new_qwen_keys():
    """四个模板都要有 10 个新键、正确的占位符 / 默认值 / 顺序 / 注释"""
    import tomlkit

    assert len(TEMPLATES) == 4, f"模板数应为 4，实际 {[p.name for p in TEMPLATES]}"
    for p in TEMPLATES:
        text = p.read_text(encoding="utf-8")
        doc = tomlkit.parse(text)
        mp, qa = doc["model_paths"], doc["qwen_ctc_args"]

        for key in _NEW_MODEL_PATH_KEYS:
            assert key in mp, f"{p} 缺 model_paths.{key}"
        assert str(mp["qwen_llm_path"]) == (
            "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"
        ), f"{p} 的 qwen_llm_path 默认值不对：{mp['qwen_llm_path']}"
        assert str(mp["qwen_ctc_encoder_frontend_path"]) == ""
        assert str(mp["qwen_ctc_encoder_backend_path"]) == ""

        # 派生只读键必须严格是 `${model_paths.同名键}`
        for name, target in _NEW_DERIVED_KEYS.items():
            assert name in qa, f"{p} 缺 qwen_ctc_args.{name}"
            assert str(qa[name]) == f"${{model_paths.{target}}}", (
                f"{p} 的 {name} 必须是 ${{model_paths.{target}}}，实际 {qa[name]!r}"
            )

        assert qa["enable_ctc"] is True, f"{p} 的 enable_ctc 必须是 true"
        assert int(qa["llm_n_ctx"]) == 4096
        assert int(qa["llm_n_threads"]) == 6
        assert int(qa["llm_n_predict"]) == 256

        # 顺序：既有 4 个派生键 → 3 个新派生键 → blank_id → ... → 4 个新键 → verbose
        keys = list(qa.keys())
        assert keys.index("preprocessor_path") < keys.index("decoder_gguf_path")
        assert keys.index("decoder_gguf_path") < keys.index("blank_id"), (
            "3 个新派生键应紧跟既有派生键、在 blank_id 之前"
        )
        for name in _NEW_DERIVED_KEYS:
            assert keys.index(name) < keys.index("blank_id"), f"{name} 必须在 blank_id 之前"
        for key in _NEW_CTX_KEYS:
            assert keys.index(key) < keys.index("verbose"), f"{key} 必须在 verbose 之前"

        # `[model_paths]` 的 3 个新键紧跟 qwen_ctc_preprocessor_path
        mp_keys = list(mp.keys())
        assert mp_keys.index("qwen_ctc_preprocessor_path") < mp_keys.index("qwen_llm_path")
        assert mp_keys.index("qwen_llm_path") < mp_keys.index("qwen_ctc_encoder_frontend_path")
        assert mp_keys.index("qwen_ctc_encoder_frontend_path") < mp_keys.index(
            "qwen_ctc_encoder_backend_path"
        )
        idx = mp_keys.index("qwen_ctc_preprocessor_path")
        assert mp_keys[idx + 1 : idx + 4] == list(_NEW_MODEL_PATH_KEYS), (
            f"{p} 的 3 个新路径键必须紧跟在 qwen_ctc_preprocessor_path 之后"
        )

        # 每个新键都要有一行注释，且两个可为空的键必须明说「留空」（GUI 会校验）
        for key in _NEW_MODEL_PATH_KEYS:
            _template_comment_after(text, key, "[model_paths]")
        for key in tuple(_NEW_DERIVED_KEYS) + _NEW_CTX_KEYS:
            _template_comment_after(text, key, "[qwen_ctc_args]")
        for key in ("qwen_ctc_encoder_frontend_path", "qwen_ctc_encoder_backend_path"):
            assert "留空" in _template_comment_after(text, key, "[model_paths]"), (
                f"{p} 的 {key} 注释必须出现「留空」二字"
            )

        # 注释之后必须跟一个空行（沿用该节现有的 键 / 注释 / 空行 风格）
        for key in _NEW_MODEL_PATH_KEYS + tuple(_NEW_DERIVED_KEYS) + _NEW_CTX_KEYS:
            assert _blank_line_after_key(text, key), f"{p} 的 {key} 注释后缺空行"


def test_default_template_comment_count_is_333():
    """默认模板的整行注释数从 323 变成 333（10 个新键各带一行注释）"""
    p = ROOT / "configs/default config.toml"
    n = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip().startswith("#"))
    assert n == 333, f"整行注释数应为 333，实际 {n}"


def test_templates_are_isomorphic():
    """四个模板在改动区域内必须同构：同样的键、同样的顺序、同样的注释文案"""
    ref_text = TEMPLATES[0].read_text(encoding="utf-8")
    ref_qa = _section_lines(ref_text, "[qwen_ctc_args]")
    ref_mp = _qwen_model_paths_tail(ref_text)
    for p in TEMPLATES[1:]:
        text = p.read_text(encoding="utf-8")
        assert _section_lines(text, "[qwen_ctc_args]") == ref_qa, (
            f"{p} 的 [qwen_ctc_args] 与 {TEMPLATES[0]} 不同构"
        )
        assert _qwen_model_paths_tail(text) == ref_mp, (
            f"{p} 的 [model_paths] qwen 段与 {TEMPLATES[0]} 不同构"
        )


def test_qwen_ctc_args_reads_new_keys_with_get_fallback():
    """10 个新字段必须全走 .get()，运行时真值取自 model_paths（不是未展开的占位符）"""
    src = (ROOT / "util/config.py").read_text(encoding="utf-8")

    for key in _NEW_MODEL_PATH_KEYS:
        assert f'config["model_paths"].get("{key}"' in src, (
            f"ModelPaths 必须用 .get 读 {key}"
        )
        assert f'config["model_paths"]["{key}"]' not in src, (
            f"{key} 不能直接下标（老配置会 KeyError）"
        )
    for key in _NEW_CTX_KEYS:
        assert f'config["qwen_ctc_args"].get("{key}"' in src, (
            f"QwenCTCArgs 必须用 .get 读 {key}"
        )
        assert f'config["qwen_ctc_args"]["{key}"]' not in src, (
            f"{key} 不能直接下标（老配置会 KeyError）"
        )
    # 3 个派生属性在 config.py 里没有同名 TOML 键可读，真值一律来自 model_paths
    for name, target in _NEW_DERIVED_KEYS.items():
        assert f'{name}: str = config["model_paths"].get("{target}"' in src, (
            f"QwenCTCArgs.{name} 必须从 model_paths.{target} 用 .get() 取值"
        )

    from util.config import ModelPaths, QwenCTCArgs

    assert QwenCTCArgs.enable_ctc is True
    assert (QwenCTCArgs.llm_n_ctx, QwenCTCArgs.llm_n_threads, QwenCTCArgs.llm_n_predict) == (
        4096,
        6,
        256,
    )
    assert Path(QwenCTCArgs.decoder_gguf_path) == ModelPaths.qwen_llm_path
    # 两个 0.6B 路径模板默认留空 ⇒ ModelPaths 侧必须是 None（不是 Path('.')）
    assert ModelPaths.qwen_ctc_encoder_frontend_path is None
    assert ModelPaths.qwen_ctc_encoder_backend_path is None
    assert QwenCTCArgs.encoder_frontend_path == ""
    assert QwenCTCArgs.encoder_backend_path == ""
    # 模板里的 `${model_paths.*}` 只是给 GUI 看的占位符，绝不能漏进运行时路径
    for name in _NEW_DERIVED_KEYS:
        assert "${" not in getattr(QwenCTCArgs, name), (
            f"QwenCTCArgs.{name} 取到了未展开的占位符：{getattr(QwenCTCArgs, name)!r}"
        )


def test_old_config_without_new_keys_still_loads():
    """老配置（没有 10 个新键）必须能加载，并回退成纯 CTC（规格 §15.1）"""
    import importlib.util
    import shutil

    text = (ROOT / "config.toml").read_text(encoding="utf-8")
    new_keys = _NEW_MODEL_PATH_KEYS + tuple(_NEW_DERIVED_KEYS) + _NEW_CTX_KEYS

    # 只在 [model_paths] / [qwen_ctc_args] 里删键 —— [funasr_args] 也有 enable_ctc
    # 之类的同名键，那些是本来就存在的，删了就不是「老配置」了。
    src_lines = text.splitlines()
    kept, inside, i = [], False, 0
    while i < len(src_lines):
        s = src_lines[i].strip()
        if s.startswith("[") and s.endswith("]"):
            inside = s in ("[model_paths]", "[qwen_ctc_args]")
        if inside and any(s.startswith(f"{key} =") for key in new_keys):
            i += 1
            while i < len(src_lines):
                t = src_lines[i].strip()
                if t and not t.startswith("#"):
                    break
                i += 1
            continue
        kept.append(src_lines[i])
        i += 1
    old_text = "\n".join(kept) + "\n"
    import tomlkit

    old_doc = tomlkit.parse(old_text)
    for key in _NEW_MODEL_PATH_KEYS:
        assert key not in old_doc["model_paths"], f"构造老配置时没删掉 model_paths.{key}"
    for key in tuple(_NEW_DERIVED_KEYS) + _NEW_CTX_KEYS:
        assert key not in old_doc["qwen_ctc_args"], f"构造老配置时没删掉 qwen_ctc_args.{key}"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "util").mkdir()
        shutil.copy(ROOT / "util" / "config.py", root / "util" / "config.py")
        (root / "config.toml").write_text(old_text, encoding="utf-8")

        spec = importlib.util.spec_from_file_location(
            "old_config_under_test", root / "util" / "config.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # 缺键时抛 KeyError 就在这里炸

    assert mod.QwenCTCArgs.decoder_gguf_path == "", "老配置没有解码器 → 必须是纯 CTC"
    assert mod.QwenCTCArgs.enable_ctc is True
    assert (mod.QwenCTCArgs.llm_n_ctx, mod.QwenCTCArgs.llm_n_threads,
            mod.QwenCTCArgs.llm_n_predict) == (4096, 6, 256)
    assert mod.QwenCTCArgs.encoder_frontend_path == ""
    assert mod.QwenCTCArgs.encoder_backend_path == ""
    # ModelPaths 的 3 个新字段也必须用回退值填充，而不是炸掉
    assert mod.ModelPaths.qwen_llm_path == Path(
        "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"
    )
    assert mod.ModelPaths.qwen_ctc_encoder_frontend_path is None, (
        "空路径必须是 None 而不是 Path('.')，否则 if ModelPaths.xxx 会误判成已配置"
    )
    assert mod.ModelPaths.qwen_ctc_encoder_backend_path is None


def _write_gguf(path_dir: Path, name: str, tensor_name: str, tensor: np.ndarray):
    """写一个只含单个张量的最小 GGUF（用于构造「没有 token_embd.weight」的情形）"""
    import gguf

    path = path_dir / name
    writer = gguf.GGUFWriter(str(path), "qwen3asr")
    writer.add_tensor(tensor_name, tensor, raw_dtype=gguf.GGMLQuantizationType.F32)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    return path


def _write_tiny_decoder_gguf(path_dir: Path, n_vocab: int, n_embd: int):
    """
    写一个只含 `token_embd.weight`(F32) 的最小 GGUF，用来精确断言「行 ↔ vocab」映射。

    真模型里 `token_embd.weight` 的 tensor shape 是 ``[n_embd, n_vocab]``，
    数据行是 vocab；GGUFWriter 的 ``raw_shape`` 与读回来 ``tensor.shape`` 顺序相反，
    所以这里传 ``(n_vocab, n_embd)`` 才能复现真文件的布局。

    Returns:
        (gguf 路径, 参考 embedding 表 [n_vocab, n_embd] float32)
    """
    import gguf

    ref = (np.arange(n_vocab * n_embd, dtype=np.float32) / 1000.0).reshape(n_vocab, n_embd)
    path = path_dir / "tiny_decoder.gguf"
    writer = gguf.GGUFWriter(str(path), "qwen3asr")
    writer.add_tensor(
        "token_embd.weight",
        ref,
        raw_shape=(n_vocab, n_embd),
        raw_dtype=gguf.GGMLQuantizationType.F32,
    )
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    return path, ref


def test_required_qwen_files_fused_pure_ctc():
    """融合 encoder + 无解码器 + enable_ctc=True ⇒ encoder/ctc/tokens/preprocessor"""
    from util.server.check_model import required_qwen_files

    p = dict(
        encoder="e.onnx",
        frontend="",
        backend="",
        ctc="c.onnx",
        tokens="t.txt",
        preprocessor="pp",
        decoder="",
    )
    assert required_qwen_files(False, False, True, p) == [
        "e.onnx",
        "c.onnx",
        "t.txt",
        "pp",
    ]


def test_required_qwen_files_fused_two_pass_includes_decoder():
    """融合 encoder + 有解码器 + enable_ctc=True ⇒ encoder/ctc/tokens/preprocessor/decoder"""
    from util.server.check_model import required_qwen_files

    p = dict(
        encoder="e.onnx",
        frontend="",
        backend="",
        ctc="c.onnx",
        tokens="t.txt",
        preprocessor="pp",
        decoder="d.gguf",
    )
    assert required_qwen_files(False, True, True, p) == [
        "e.onnx",
        "c.onnx",
        "t.txt",
        "pp",
        "d.gguf",
    ]


def test_required_qwen_files_fused_llm_only_skips_ctc_head():
    """融合 encoder + 有解码器 + enable_ctc=False ⇒ encoder/preprocessor/decoder，不要 ctc/tokens"""
    from util.server.check_model import required_qwen_files

    p = dict(
        encoder="e.onnx",
        frontend="",
        backend="",
        ctc="c.onnx",
        tokens="t.txt",
        preprocessor="pp",
        decoder="d.gguf",
    )
    assert required_qwen_files(False, True, False, p) == ["e.onnx", "pp", "d.gguf"]


def test_required_qwen_files_split_encoder_skips_ctc_and_tokens():
    """0.6B 拆分 encoder ⇒ 前后端 + preprocessor + 解码器，0.6B 没有 CTC 头 / tokens"""
    from util.server.check_model import required_qwen_files

    p = dict(
        encoder="e.onnx",
        frontend="f.onnx",
        backend="b.onnx",
        ctc="c.onnx",
        tokens="t.txt",
        preprocessor="pp",
        decoder="d.gguf",
    )
    files = required_qwen_files(True, True, True, p)
    assert files == ["f.onnx", "b.onnx", "pp", "d.gguf"]
    # 即使调用方误传了 ctc/tokens，拆分形态也绝不能要求它们
    assert "c.onnx" not in files
    assert "t.txt" not in files


def test_required_qwen_files_empty_string_and_none_are_unconfigured():
    """空字符串 / None 一律视为「未配置」；decoder="" 是合法的纯 CTC"""
    from util.server.check_model import required_qwen_files

    p = dict(
        encoder="e.onnx",
        frontend="",
        backend=None,
        ctc="",
        tokens=None,
        preprocessor="pp",
        decoder="",
    )
    assert required_qwen_files(False, False, True, p) == ["e.onnx", "pp"]
    # has_decoder=True 但 decoder 路径为空：空串不能进必需列表
    assert required_qwen_files(False, True, False, p) == ["e.onnx", "pp"]


def test_qwen_mode_errors_reject_no_decoder_and_ctc_disabled():
    """解码器为空 + enable_ctc=False ⇒ 模式层面硬错误（§7.2 唯一一行）"""
    from util.server.check_model import qwen_mode_errors

    errors = qwen_mode_errors(
        has_frontend=False, has_backend=False, has_decoder=False, enable_ctc=False
    )
    assert any("既未配置解码器又禁用了 CTC，无推理路径" in e for e in errors), errors


def test_qwen_mode_errors_reject_half_split_encoder():
    """0.6B 前后端只配一端 ⇒ 模式层面硬错误，两个方向都要拦"""
    from util.server.check_model import qwen_mode_errors

    for has_frontend, has_backend in ((True, False), (False, True)):
        errors = qwen_mode_errors(has_frontend, has_backend, True, True)
        assert any("0.6B 编码器前后端必须成对配置" in e for e in errors), (
            has_frontend,
            has_backend,
            errors,
        )


def test_qwen_mode_errors_accepts_every_valid_mode():
    """合法的模式组合一个都不许误报（否则启动体检会拦住能跑的模式）"""
    from util.server.check_model import qwen_mode_errors

    valid = [
        (False, False, False, True),   # 融合 + 纯 CTC（现状）
        (False, False, True, True),    # 融合 + 两遍
        (False, False, True, False),   # 融合 + 纯 LLM
        (True, True, True, True),      # 0.6B + 请求两遍（无 CTC 头，降级纯 LLM）
        (True, True, True, False),     # 0.6B + 纯 LLM
    ]
    for args in valid:
        assert qwen_mode_errors(*args) == [], (args, qwen_mode_errors(*args))


def test_qwen_mode_errors_reject_split_encoder_without_decoder():
    """0.6B 前后端拆分 + 解码器为空：必须报错（引擎 resolve_mode 必抛 ValueError）

    这条组合不看 `enable_ctc`：0.6B 那条路径上 CTC 头必然不可用，开不开 CTC
    都没有推理路径，体检不能放行。
    """
    from util.server.check_model import qwen_mode_errors

    errors = qwen_mode_errors(True, True, False, True)
    assert errors, "0.6B 拆分 + 空解码器必须报模式错误（否则体检放行、引擎必炸）"
    assert any("0.6B" in e for e in errors), errors
    # 文案要点名可执行的出路：填 qwen_llm_path，或改用 1.7B 融合编码器
    assert any("qwen_llm_path" in e for e in errors), errors
    assert any("1.7B" in e for e in errors), errors


def test_qwen_mode_errors_split_missing_decoder_precedes_ctc_disabled():
    """同一组合同时命中两条错误时，0.6B 拆分那条必须在前（与引擎判定顺序一致）"""
    from util.server.check_model import qwen_mode_errors

    errors = qwen_mode_errors(True, True, False, False)
    assert len(errors) >= 2, f"应同时命中「0.6B 缺解码器」与「既无解码器又禁 CTC」：{errors}"
    assert "0.6B" in errors[0], f"拆分文案更具体，必须排在前面：{errors}"
    assert any("既未配置解码器又禁用了 CTC" in e for e in errors), errors


def test_qwen_mode_errors_reject_pure_ctc_without_ctc_head():
    """纯 CTC 但 ctc / tokens 没配 = 无推理路径（引擎初始化时硬失败）"""
    from util.server.check_model import qwen_mode_errors

    for kwargs in (
        dict(ctc_configured=False, tokens_configured=True),
        dict(ctc_configured=True, tokens_configured=False),
        dict(ctc_configured=False, tokens_configured=False),
    ):
        errors = qwen_mode_errors(False, False, False, True, **kwargs)
        assert any("纯 CTC" in e and "ctc_onnx_path 与 tokens_path" in e for e in errors), (
            kwargs,
            errors,
        )
    # 有解码器时缺 CTC 头是合法的（引擎 WARNING 降级为纯 LLM），绝不能误报
    assert (
        qwen_mode_errors(
            False,
            False,
            True,
            True,
            ctc_configured=False,
            tokens_configured=False,
        )
        == []
    )


def test_qwen_mode_errors_split_skips_pure_ctc_head_error():
    """0.6B 拆分 + 缺解码器 + 缺 CTC 头：只报 0.6B 那条，别让用户去配不存在的 CTC 头"""
    from util.server.check_model import qwen_mode_errors

    errors = qwen_mode_errors(
        True, True, False, True, ctc_configured=False, tokens_configured=False
    )
    assert any("0.6B" in e for e in errors), errors
    assert not any("纯 CTC" in e for e in errors), (
        f"0.6B 路径上根本没有 CTC 头可选，不该再要求配 ctc_onnx_path：{errors}"
    )


def test_qwen_mode_errors_reject_two_pass_without_tokens():
    """解码器 + CTC 头都配了就是两遍模式，词表留空会让引擎 load_tokens("") 抛异常

    `required_qwen_files` 对未配置项是跳过的，所以这条只能由模式错误兜住；
    引擎侧 `util/qwen_ctc/engine.py` 只在 ctc/two_pass 时载入词表。
    """
    from util.server.check_model import qwen_mode_errors

    errors = qwen_mode_errors(
        False, False, True, True, ctc_configured=True, tokens_configured=False
    )
    assert any("tokens_path" in e for e in errors), errors
    assert any("两遍" in e for e in errors), errors


def test_qwen_mode_errors_accepts_two_pass_without_ctc_head():
    """两遍模式缺 CTC 头是合法的：引擎 WARNING 降级为纯 LLM，此时不需要词表"""
    from util.server.check_model import qwen_mode_errors

    assert (
        qwen_mode_errors(
            False, False, True, True, ctc_configured=False, tokens_configured=False
        )
        == []
    ), "CTC 头没配 = 引擎降级纯 LLM，不该要求词表，也不该报错"


def _stub_qwen_ctc_args(**overrides):
    """QwenCTCArgs 替身：默认是「老配置形态」的纯 CTC，可任意覆盖字段"""
    fields = dict(
        encoder_onnx_path=str(ENCODER_17B),
        ctc_onnx_path=str(CTC_17B),
        tokens_path=str(TOKENS_17B),
        preprocessor_path=str(PREPROCESSOR_DIR),
        decoder_gguf_path="",
        encoder_frontend_path="",
        encoder_backend_path="",
        enable_ctc=True,
    )
    fields.update(overrides)
    return type("_StubQwenCTCArgs", (), fields)


def test_qwen_plan_paths_come_from_qwen_ctc_args():
    """老配置形态：`_qwen_plan()` 不能去要求 `ModelPaths.qwen_llm_path` 默认的 GGUF

    引擎侧 `decoder_gguf_path` 空串 = 纯 CTC，根本不读那个文件；体检若照
    `ModelPaths` 的 1.7B 默认值去查，就会把一个能跑的纯 CTC 判成缺文件。
    """
    import util.server.check_model as cm

    with patch.object(cm, "QwenCTCArgs", _stub_qwen_ctc_args()):
        plan, errors = cm._qwen_plan()

    files = plan["Qwen3-ASR 模型文件（按当前配置解析）"]
    assert errors == [], errors
    assert files, "纯 CTC 至少要检查 encoder / ctc / tokens / preprocessor"
    assert not any(str(f).endswith(".gguf") for f in files), f"不该要求任何 GGUF：{files}"
    assert not any("qwen3_asr_llm" in str(f) for f in files), files


def test_qwen_plan_reports_pure_ctc_without_ctc_head():
    """`_qwen_plan()` 必须把 ctc 为空传给模式校验，否则「无推理路径」又漏一轮"""
    import util.server.check_model as cm

    with patch.object(cm, "QwenCTCArgs", _stub_qwen_ctc_args(ctc_onnx_path="")):
        _plan, errors = cm._qwen_plan()

    assert errors, "纯 CTC + 没有 CTC 头必须报模式错误"
    assert any("纯 CTC" in e for e in errors), errors


def test_qwen_download_commands_are_verbatim_from_spec():
    """缺失提示里的 §4.3 下载命令必须逐字保留，不能改写命令本身"""
    from util.server.check_model import QWEN_DOWNLOAD_COMMANDS as cmds

    text = cmds.replace("\r\n", "\n")
    # 1.7B：一条 curl（含续行反斜杠）
    assert "-o models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf \\\n" in text
    assert (
        "https://modelscope.cn/models/luciacx/Qwen3-ASR-GGUF-1.7B-mixed/resolve/master/"
        "qwen3_asr_llm.q4_k.gguf"
    ) in text
    # 0.6B：mkdir + for 循环里的三条 curl
    assert "mkdir -p models/qwen-ctc-aiinfra4-06b" in text
    assert (
        "for f in qwen3_asr_encoder_frontend.int4.onnx "
        "qwen3_asr_encoder_backend.int4.onnx qwen3_asr_llm.q4_k.gguf; do"
    ) in text
    assert 'curl -4 -L -C - -o "models/qwen-ctc-aiinfra4-06b/$f" \\\n' in text
    assert (
        "https://modelscope.cn/models/luciacx/Qwen3-ASR-GGUF-0.6B-mixed/resolve/master/$f"
    ) in text
    assert text.rstrip().endswith("done")


# --------------------------------------------------------------------------
# Task 9: recognize_qwen_ctc.py —— 服务端拼接 / 标点分支
# --------------------------------------------------------------------------


class _FakeStream:
    """sherpa-onnx 流接口的最小替身"""

    def __init__(self, result):
        self.result = result

    def accept_waveform(self, samplerate, samples):
        pass


class _FakeRecognizer:
    """引擎替身：`recognize()` 只依赖 mode / has_timestamps 两个属性

    两遍 / 纯 CTC 的 tokens 与 timestamps 长度天然相等（T6/T7 已由 NW 对齐
    保证）；纯 LLM 的 tokens / timestamps 为空。
    """

    def __init__(self, mode, text="", tokens=None, timestamps=None):
        self.mode = mode
        self.has_timestamps = mode in ("ctc", "two_pass")
        self._result = SimpleNamespace(
            text=text,
            tokens=list(tokens or []),
            timestamps=list(timestamps or []),
        )

    def create_stream(self):
        return _FakeStream(self._result)

    def decode_stream(self, stream):
        pass


class _CountingPunc:
    """记录 `add_punctuation` 被调用几次、吃进来的原文"""

    def __init__(self):
        self.calls = 0
        self.inputs = []

    def add_punctuation(self, text):
        self.calls += 1
        self.inputs.append(text)
        return text + "。"


def _qwen_task(task_id, socket_id=None, is_final=True):
    return SimpleNamespace(
        task_id=task_id,
        socket_id=socket_id or f"sock-{task_id}",
        source="mic",
        data=np.zeros(16000, np.float32),
        offset=0.0,
        overlap=0.0,
        is_final=is_final,
        time_start=0.0,
        time_submit=0.0,
        samplerate=16000,
    )


def test_recognize_llm_mode_merges_by_text():
    """纯 LLM 模式：text 走 merge_by_text，不造 token / 时间戳，也不过标点模型"""
    import util.server.recognize_qwen_ctc as m

    punc = _CountingPunc()
    r = m.recognize(
        _FakeRecognizer("llm", text="你好世界"),
        punc_model=punc,
        task=_qwen_task("task9-llm-merge"),
    )

    assert r.text == "你好世界", f"纯 LLM 的 text 必须来自 merge_by_text：{r.text!r}"
    assert r.text_accu == "你好世界", r.text_accu
    assert r.tokens == [] and r.timestamps == [], "纯 LLM 不许伪造 token / 时间戳"
    assert r.is_final is True
    assert punc.calls == 0, "纯 LLM 的文本已自带标点，不得再过标点模型"


def test_recognize_llm_mode_accumulates_across_segments():
    """纯 LLM 第二段必须接在缓存文本后面，不能被 `"".join(空 tokens)` 抹成空串"""
    import util.server.recognize_qwen_ctc as m

    sock_id = "task9-llm-accum"
    m.clear_results_by_socket_id(sock_id)

    first = m.recognize(
        _FakeRecognizer("llm", text="你好世界"),
        punc_model=None,
        task=_qwen_task(sock_id, socket_id=sock_id, is_final=False),
    )
    assert first.text == "你好世界", f"首段纯 LLM 文本不对：{first.text!r}"
    assert first.tokens == [] and first.timestamps == []

    last = m.recognize(
        _FakeRecognizer("llm", text="世界再见"),
        punc_model=None,
        task=_qwen_task(sock_id, socket_id=sock_id, is_final=True),
    )
    assert last.text == "你好世界再见", f"重叠段没按 merge_by_text 拼：{last.text!r}"
    assert last.text_accu == "你好世界再见", last.text_accu
    assert last.tokens == [] and last.timestamps == [], "纯 LLM 结束后仍不许有 token"


def test_recognize_token_mode_keeps_text_mode_cache():
    """同一 task_id 由 text 模式切到 token 模式：缓存文本不能被空 tokens 抹掉"""
    import util.server.recognize_qwen_ctc as m

    sock_id = "task9-mode-switch"
    m.clear_results_by_socket_id(sock_id)

    first = m.recognize(
        _FakeRecognizer("llm", text="你好世界"),
        punc_model=None,
        task=_qwen_task(sock_id, socket_id=sock_id, is_final=False),
    )
    assert first.text == "你好世界"

    # 切到 token 模式，本段是静音（tokens 空）—— `"".join([])` 不能覆盖已有文本
    last = m.recognize(
        _FakeRecognizer("two_pass", text="", tokens=[], timestamps=[]),
        punc_model=None,
        task=_qwen_task(sock_id, socket_id=sock_id, is_final=True),
    )
    assert last.text == "你好世界", f"text 模式的缓存文本被空 tokens 抹掉了：{last.text!r}"
    assert last.text_accu == "你好世界", last.text_accu
    assert last.tokens == [] and last.timestamps == []


def test_recognize_two_pass_skips_punctuation_model():
    """两遍模式：LLM 文本已自带标点，format_text 必须 use_punc=False"""
    import util.server.recognize_qwen_ctc as m

    punc = _CountingPunc()
    r = m.recognize(
        _FakeRecognizer(
            "two_pass",
            text="你好。",
            tokens=list("你好。"),
            timestamps=[0.0, 0.4, 0.8],
        ),
        punc_model=punc,
        task=_qwen_task("task9-two-pass"),
    )

    assert punc.calls == 0, "两遍模式的 LLM 文本已自带标点，不得再过标点模型"
    assert r.text == "你好。", r.text
    assert r.tokens == list("你好。"), r.tokens
    assert r.timestamps == [0.0, 0.4, 0.8], r.timestamps
    assert len(r.tokens) == len(r.timestamps)


def test_recognize_two_pass_mid_segment_skips_punctuation():
    """两遍模式中间段：不调标点、text_accu 与 text 一致、结果留在缓存里"""
    import util.server.recognize_qwen_ctc as m

    sock_id = "task9-two-pass-mid"
    m.clear_results_by_socket_id(sock_id)

    punc = _CountingPunc()
    r = m.recognize(
        _FakeRecognizer(
            "two_pass",
            text="你好。",
            tokens=list("你好。"),
            timestamps=[0.0, 0.4, 0.8],
        ),
        punc_model=punc,
        task=_qwen_task(sock_id, socket_id=sock_id, is_final=False),
    )

    assert punc.calls == 0, "中间段不得调标点模型"
    assert r.text == "你好。", r.text
    assert r.text_accu == r.text, f"中间段 text_accu 与 text 必须一致：{r.text_accu!r}"
    assert r.tokens == list("你好。"), r.tokens
    assert m.clear_results_by_socket_id(sock_id) == 1, "中间段必须留在缓存里等下一段拼接"


def test_recognize_pure_ctc_still_calls_punctuation_model():
    """纯 CTC 行为不变：Config.format_punc 打开时照旧补标点（回归保护）"""
    import util.server.recognize_qwen_ctc as m
    from util.config import ServerConfig as Config

    # 本用例验的是「纯 CTC 时仍会调标点模型」，与环境里 format_punc 的取值无关；
    # 临时钉住再还原，免得用户关掉 format_punc 后这条回归凭空变红。
    _saved_format_punc = Config.format_punc
    Config.format_punc = True
    try:
        punc = _CountingPunc()
        r = m.recognize(
            _FakeRecognizer(
                "ctc",
                text="你好世界",
                tokens=list("你好世界"),
                timestamps=[0.0, 0.1, 0.2, 0.3],
            ),
            punc_model=punc,
            task=_qwen_task("task9-pure-ctc"),
        )
    finally:
        Config.format_punc = _saved_format_punc

    # 现有实现里 text / text_accu 各过一遍 format_text，所以是两次调用
    assert punc.calls == 2, "纯 CTC 必须照旧调用标点模型（text / text_accu 各一次）"
    assert punc.inputs == ["你好世界", "你好世界"], punc.inputs
    assert r.text == "你好世界。", r.text
    assert r.text_accu == "你好世界。", r.text_accu
    assert r.tokens == list("你好世界"), r.tokens


def test_format_text_skipping_punc_keeps_spacing_and_numbers():
    """spec §10.2 第 2 点：use_punc=False 只跳标点，adjust_space 与 chinese_to_num 照做

    Task 9 评审 I3：把 `chinese_to_num` 或两个 `adjust_space` 删掉，原有 74 条用例
    全绿 —— 这个「最易写错处」原先零覆盖。
    """
    import util.server.recognize_qwen_ctc as m

    punc = _CountingPunc()
    out = m.format_text("二零二五年hello世界", punc, use_punc=False)

    assert out == "2025年 hello 世界", f"跳标点不得跳过空格与数字转换：{out!r}"
    assert punc.calls == 0, f"use_punc=False 不得调用标点模型：{punc.calls}"

    # 反向保护：use_punc=True 时标点确实参与
    punc2 = _CountingPunc()
    assert m.format_text("你好世界", punc2, use_punc=True) == "你好世界。"
    assert punc2.calls == 1


def test_recognize_llm_mode_english_overlap_merges_once():
    """纯 LLM 的英文跨段拼接：≤16 字符重叠必须只出现一次

    merge_by_text 的窗口是 5 字符，长重叠会退化（见 recognize_qwen_ctc.py 里
    的「已知限制」注释）；这条用例钉住**没有退化**的那一侧，中文侧见
    `test_recognize_llm_mode_accumulates_across_segments`。
    """
    import util.server.recognize_qwen_ctc as m

    # 同一个 task_id：`_results` 按 task_id 缓存，换 id 就是另一段独立录音。
    task_id = "task9-en-overlap"

    r1 = m.recognize(
        _FakeRecognizer("llm", text="we also looked at the"),
        punc_model=_CountingPunc(),
        task=_qwen_task(task_id, is_final=False),
    )
    assert r1.text == "we also looked at the", r1.text

    r2 = m.recognize(
        _FakeRecognizer("llm", text="looked at the audio quality"),
        punc_model=_CountingPunc(),
        task=_qwen_task(task_id),
    )
    assert r2.text == "we also looked at the audio quality", r2.text


def test_recognize_use_punc_follows_mode_constant():
    """三模式的加标点策略由 MODE_CTC 常量决定（不硬编码字符串）"""
    import util.server.recognize_qwen_ctc as m
    from util.qwen_ctc.engine import MODE_CTC, MODE_LLM, MODE_TWO_PASS

    assert (MODE_CTC, MODE_TWO_PASS, MODE_LLM) == ("ctc", "two_pass", "llm")

    for mode, expect_calls in ((MODE_CTC, 2), (MODE_TWO_PASS, 0), (MODE_LLM, 0)):
        punc = _CountingPunc()
        kwargs = (
            dict(tokens=list("你好世界"), timestamps=[0.0, 0.1, 0.2, 0.3])
            if mode != MODE_LLM
            else dict(tokens=[], timestamps=[])
        )
        r = m.recognize(
            _FakeRecognizer(mode, text="你好世界", **kwargs),
            punc_model=punc,
            task=_qwen_task(f"task9-punc-{mode}"),
        )
        assert punc.calls == expect_calls, f"{mode}: {punc.calls} != {expect_calls}"
        assert ("。" in r.text) is (expect_calls > 0), f"{mode}: {r.text!r}"


def test_recognize_llm_mode_clears_stale_tokens_from_cache():
    """切到纯 LLM 时必须清空缓存里的 tokens / 时间戳

    评审 M-3：删掉 `result.tokens = []` / `result.timestamps = []` 两行，原有
    用例全绿 —— 而后果是把上一段 CTC 的 tokens 与时间戳泄漏进纯 LLM 结果，
    违反 spec §7.2「纯 LLM 不产时间戳」。模式在生产里不会中途切换（engine
    启动时固化），但缓存是按 task_id 跨请求存活的，这条护栏必须被钉住。
    """
    import util.server.recognize_qwen_ctc as m

    task_id = "task9-stale-tokens"
    r1 = m.recognize(
        _FakeRecognizer(
            "ctc", text="今天天气", tokens=list("今天天气"), timestamps=[0, 1, 2, 3]
        ),
        punc_model=None,
        task=_qwen_task(task_id, is_final=False),
    )
    assert r1.tokens == list("今天天气"), r1.tokens

    r2 = m.recognize(
        _FakeRecognizer("llm", text="不错"),
        punc_model=None,
        task=_qwen_task(task_id),
    )
    assert r2.tokens == [], f"纯 LLM 不得残留 CTC tokens：{r2.tokens}"
    assert r2.timestamps == [], f"纯 LLM 不得残留时间戳：{r2.timestamps}"
    assert r2.text == "今天天气不错", r2.text


def test_recognize_two_pass_empty_llm_segment_keeps_previous_text():
    """两遍模式某一段 LLM 返回空（生产可达）：不得把已累积的文本抹掉"""
    import util.server.recognize_qwen_ctc as m

    task_id = "task9-two-pass-empty"
    r1 = m.recognize(
        _FakeRecognizer(
            "two_pass",
            text="你好，世界。",
            tokens=list("你好世界"),
            timestamps=[0.0, 0.1, 0.2, 0.3],
        ),
        punc_model=None,
        task=_qwen_task(task_id, is_final=False),
    )
    assert r1.text == "你好世界", r1.text

    r2 = m.recognize(
        _FakeRecognizer("two_pass", text="", tokens=[], timestamps=[]),
        punc_model=None,
        task=_qwen_task(task_id),
    )
    assert r2.text, "空 LLM 段不得把已累积文本抹成空串"
    assert len(r2.tokens) == len(r2.timestamps) > 0, (r2.tokens, r2.timestamps)


def test_save_results_without_tokens_skips_srt():
    """纯 LLM 模式没有 tokens：文件转录必须跳过 SRT 而不是崩掉整个文件

    最终评审的 Critical：`save_results` 用 `zip(timestamps, tokens)` 造 words，
    纯 LLM 两个列表都为空 → words=[] → `srt_from_txt.generate_srt_file` 在
    `min(last_word_idx + 1, len(words) - 1)` 得到 -1 → `words[-1]["start"]`
    抛 IndexError，被 core_client 外层 except 吞成「处理文件 xx 时出错」，
    用户拿不到 srt 也不知道原因。
    """
    import pathlib
    import tempfile

    from util.client.transcribe.result_handler import ResultHandler
    from util.config import ClientConfig as CC

    saved = (
        CC.file_save_srt,
        CC.file_save_json,
        CC.file_save_txt,
        CC.file_save_merge,
        CC.use_hot_sub_when_transcribe_file,
    )
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="qwen-srt-"))
    media = tmp_dir / "pure_llm.wav"
    try:
        CC.file_save_srt = True
        CC.file_save_json = False
        CC.file_save_txt = True
        CC.file_save_merge = False
        CC.use_hot_sub_when_transcribe_file = False
        message = {
            "text": "你好世界，这是纯 LLM 模式。",
            "text_accu": "你好世界，这是纯 LLM 模式。",
            "timestamps": [],
            "tokens": [],
        }
        ResultHandler.save_results(media, message)  # 不得抛异常
        assert not media.with_suffix(".srt").exists(), "无时间戳时不应生成 srt"
        assert media.with_suffix(".txt").exists(), "txt 仍应照常落盘"
    finally:
        CC.file_save_srt, CC.file_save_json, CC.file_save_txt = saved[0], saved[1], saved[2]
        CC.file_save_merge, CC.use_hot_sub_when_transcribe_file = saved[3], saved[4]
        for leftover in tmp_dir.iterdir():
            leftover.unlink()
        tmp_dir.rmdir()


def test_qwen_mode_errors_ignores_missing_tokens_when_ctc_file_absent():
    """CTC 头**文件缺失**时不该报「两遍模式缺 tokens_path」

    最终评审的 Important-2：check_model 的 ctc_configured 看「路径非空」，
    引擎看「文件存在且能加载」。CTC 头路径非空但文件没下载、tokens 又留空时，
    引擎会 WARNING 后按纯 LLM 正常跑，而体检却用一条指向 tokens_path 的错误
    把服务端拦下来。加了 ctc_file_exists 之后，这种情况交给缺失文件检查去报
    「CTC 头文件不存在」，文案才是准确的。
    """
    from util.server.check_model import qwen_mode_errors

    # CTC 头路径非空但文件不存在 + 有解码器 + 启用 CTC + tokens 留空
    errors = qwen_mode_errors(
        False,
        False,
        True,
        True,
        ctc_configured=True,
        tokens_configured=False,
        ctc_file_exists=False,
    )
    assert errors == [], f"不该报模式错误（交给缺失文件检查）：{errors}"

    # 文件确实存在时，缺 tokens 仍然是硬错误
    errors = qwen_mode_errors(
        False,
        False,
        True,
        True,
        ctc_configured=True,
        tokens_configured=False,
        ctc_file_exists=True,
    )
    assert len(errors) == 1 and "tokens_path" in errors[0], errors


if __name__ == "__main__":
    # Windows 控制台默认 GBK，输出中文/符号前先切到 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 让 loguru 的日志不要插到 print 的输出中间
    try:
        from loguru import logger as _loguru_logger

        _loguru_logger.remove()
    except Exception:
        pass

    tests = [
        test_llama_cpp_loads_decoder_and_reports_mrope,
        test_llama_cpp_raises_on_truncated_gguf,
        test_token_embedding_rows_are_dequantized,
        test_token_embedding_rows_match_gguf_vocab_rows,
        test_token_embedding_rejects_bad_ids_and_use_after_close,
        test_token_embedding_lru_is_bounded,
        test_token_embedding_cache_file_is_written_and_reused,
        test_token_embedding_rejects_gguf_without_embedding,
        test_token_embedding_06b_dimensions,
        test_valid_frames_boundaries,
        test_resolve_providers_selects_cpu_or_dml,
        test_fused_encoder_shape,
        test_split_encoder_shape,
        test_fused_encoder_matches_manual_pipeline,
        test_split_encoder_matches_manual_pipeline,
        test_encoder_close_is_idempotent,
        test_fused_encoder_rejects_audio_beyond_bucket,
        test_split_encoder_rejects_audio_beyond_bucket,
        test_align_length_always_matches_llm_text,
        test_align_empty_ctc_distributes_evenly,
        test_align_identical_text_keeps_starts,
        test_align_heavy_mismatch_stays_monotonic,
        test_align_empty_text_returns_empty,
        test_align_interpolates_missing_punctuation,
        test_align_is_case_insensitive_and_fullwidth_normalized,
        test_align_mixed_cjk_latin_and_length_mismatch,
        test_align_prefix_is_not_flattened_to_zero,
        test_llm_prompt_special_tokens,
        test_llm_generates_transcript_from_encoder_output,
        test_llm_predict_is_clamped_to_context,
        test_llm_generates_transcript_06b,
        test_llm_warmup_and_repeat_generate_are_stable,
        test_llm_warmup_propagates_real_errors,
        test_engine_config_exposes_new_fields_and_factory_kwargs,
        test_engine_resolve_mode_matrix,
        test_engine_resolve_mode_rejects_impossible_combos,
        test_engine_rejects_missing_decoder_file,
        test_engine_pure_ctc_needs_no_llama_runtime,
        test_engine_modes_end_to_end,
        test_engine_silence_does_not_crash,
        test_engine_long_audio_offsets_are_continuous,
        test_engine_repeat_calls_are_stable,
        test_engine_06b_without_ctc_head_degrades_to_llm,
        test_engine_rejects_decoder_encoder_dim_mismatch,
        test_engine_rejects_half_split_encoder,
        test_engine_pure_ctc_requires_ctc_head,
        test_templates_have_new_qwen_keys,
        test_templates_are_isomorphic,
        test_default_template_comment_count_is_333,
        test_qwen_ctc_args_reads_new_keys_with_get_fallback,
        test_old_config_without_new_keys_still_loads,
        test_required_qwen_files_fused_pure_ctc,
        test_required_qwen_files_fused_two_pass_includes_decoder,
        test_required_qwen_files_fused_llm_only_skips_ctc_head,
        test_required_qwen_files_split_encoder_skips_ctc_and_tokens,
        test_required_qwen_files_empty_string_and_none_are_unconfigured,
        test_qwen_mode_errors_reject_no_decoder_and_ctc_disabled,
        test_qwen_mode_errors_reject_half_split_encoder,
        test_qwen_mode_errors_accepts_every_valid_mode,
        test_qwen_mode_errors_reject_split_encoder_without_decoder,
        test_qwen_mode_errors_split_missing_decoder_precedes_ctc_disabled,
        test_qwen_mode_errors_reject_pure_ctc_without_ctc_head,
        test_qwen_mode_errors_split_skips_pure_ctc_head_error,
        test_qwen_mode_errors_reject_two_pass_without_tokens,
        test_qwen_mode_errors_accepts_two_pass_without_ctc_head,
        test_qwen_plan_paths_come_from_qwen_ctc_args,
        test_qwen_plan_reports_pure_ctc_without_ctc_head,
        test_qwen_download_commands_are_verbatim_from_spec,
        test_recognize_llm_mode_merges_by_text,
        test_recognize_llm_mode_accumulates_across_segments,
        test_recognize_token_mode_keeps_text_mode_cache,
        test_recognize_two_pass_skips_punctuation_model,
        test_recognize_two_pass_mid_segment_skips_punctuation,
        test_recognize_pure_ctc_still_calls_punctuation_model,
        test_format_text_skipping_punc_keeps_spacing_and_numbers,
        test_recognize_llm_mode_english_overlap_merges_once,
        test_recognize_use_punc_follows_mode_constant,
        test_recognize_llm_mode_clears_stale_tokens_from_cache,
        test_recognize_two_pass_empty_llm_segment_keeps_previous_text,
        test_save_results_without_tokens_skips_srt,
        test_qwen_mode_errors_ignores_missing_tokens_when_ctc_file_absent,
    ]
    failed = 0
    for t in tests:
        print(f"> {t.__name__}", flush=True)
        try:
            t()
            print("  [OK]\n", flush=True)
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {e}\n", flush=True)
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {e}\n", flush=True)
    if failed:
        print(f"{failed} 个用例失败")
        raise SystemExit(1)
    print("全部通过")
