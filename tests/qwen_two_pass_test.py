# coding: utf-8
"""
Qwen 两遍引擎（LLM 二遍）测试

不依赖 pytest：直接 `python tests/qwen_two_pass_test.py` 运行。

Task 1 只覆盖「自有 llama.cpp 绑定层」这一块地基：
1. 随包的 llama.dll 能加载 Qwen3-ASR 解码器 GGUF，且报告 IMROPE（rope_type=40）
   —— 这是 M-RoPE 4 平面位置注入能工作的前提；
2. 模型加载失败必须抛 `LlamaLoadError`，不能把 NULL 指针带进后续调用。

需要模型文件 models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf。
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# 直接 `python tests/qwen_two_pass_test.py` 运行时，脚本目录才是 sys.path[0]
sys.path.append(str(ROOT))

DECODER_17B = ROOT / "models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf"


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
