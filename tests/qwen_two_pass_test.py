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

需要模型文件 models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf
（0.6B 用例需要 models/qwen-ctc-aiinfra4-06b/qwen3_asr_llm.q4_k.gguf，缺失则跳过）。
"""

import contextlib
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# 直接 `python tests/qwen_two_pass_test.py` 运行时，脚本目录才是 sys.path[0]
sys.path.append(str(ROOT))

DECODER_17B = ROOT / "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"
DECODER_06B = ROOT / "models/qwen-ctc-aiinfra4-06b/qwen3_asr_llm.q4_k.gguf"


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
