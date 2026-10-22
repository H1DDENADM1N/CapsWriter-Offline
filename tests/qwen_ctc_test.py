# coding: utf-8
"""
Qwen3-ASR + CTC 头 引擎测试

不依赖 pytest：直接 `python tests/qwen_ctc_test.py` 运行。

覆盖三件事：
1. **纯逻辑**：字节流解码（一个中文字符横跨多个 token 时不能出乱码）、
   13 帧率换算、30 秒切段。
2. **引擎**：拿真实音频跑一遍，断言文本非空（空文本 = 特征归一化或帧率
   写错的典型症状）、token 与时间戳一一对应、时间戳单调。
3. **拼接**：多段带重叠的音频拼起来，重复段不能被输出两遍。

需要模型文件（默认 models/qwen-ctc-aiinfra4/）。没有模型时前两组用例会
自动跳过，只跑纯逻辑那一组。
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.append(".")

from util.qwen_ctc import QwenCTCEngine, QwenCTCConfig  # noqa: E402
from util.qwen_ctc.tokens import decode_bytes, load_tokens  # noqa: E402

MODEL_DIR = Path("models/qwen-ctc-aiinfra4")
SAMPLE_RATE = 16000

# 引擎用例需要一段真实语音。仓库自带的 SenseVoice 测试音频最方便，
# 也可以自己放一个 30s 左右的音频到 dev/test_asset_30s.wav。
AUDIO_CANDIDATES = [
    Path("dev/test_asset_30s.wav"),
    Path("models/qwen-ctc-aiinfra4/test.wav"),
    Path(
        "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs/zh.wav"
    ),
]


def _find_audio() -> Path | None:
    for p in AUDIO_CANDIDATES:
        if p.exists():
            return p
    return None


# ── 1. 纯逻辑 ──────────────────────────────────────────────────────────
def test_decode_bytes_crosses_token_boundary():
    """一个中文字符由多个字节基元拼成时，整体解码才正确"""
    # "你" = e4 bda0  -> 三个字节基元
    id2bytes = {0: b"\xe4", 1: b"\xbd", 2: b"\xa0"}
    assert decode_bytes(id2bytes, [0, 1, 2]) == "你"
    # 逐 token 解码会得到 3 个替换字符，整体解码只有 1 个
    assert decode_bytes(id2bytes, [0, 1, 2]).count("\ufffd") == 0


def test_load_tokens_reads_base64():
    """tokens.txt 形如 `<base64 字节>\\t<id>`"""
    import base64
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tokens.txt"
        p.write_text(
            f"{base64.b64encode(b'A').decode()}\t0\n"
            f"{base64.b64encode('你'.encode('utf-8')).decode()}\t1\n",
            encoding="utf-8",
        )
        id2bytes = load_tokens(p)
    assert id2bytes[0] == b"A", f"id 0 解出来是 {id2bytes[0]!r}"
    assert id2bytes[1] == "你".encode("utf-8"), f"id 1 解出来是 {id2bytes[1]!r}"


def test_valid_frames_is_13fps():
    """Qwen3 是 13 帧/秒：每 100 帧 mel 出 13 帧，尾巴按 8 帧一组"""
    engine = QwenCTCEngine.__new__(QwenCTCEngine)
    assert engine._valid_frames(100) == 13
    assert engine._valid_frames(200) == 26
    assert engine._valid_frames(0) == 0
    # 剩 1..8 帧 -> 1 帧输出
    assert engine._valid_frames(101) == 14
    assert engine._valid_frames(108) == 14
    # 剩 9 帧 -> 2 帧输出
    assert engine._valid_frames(109) == 15


def test_segment_split():
    """超过 30 秒的音频必须切段，否则特征会被截断"""
    from util.qwen_ctc.engine import SEGMENT_SEC

    assert SEGMENT_SEC == 30.0
    seg_len = int(SEGMENT_SEC * SAMPLE_RATE)
    audio = np.zeros(seg_len * 2 + 100, dtype=np.float32)
    chunks = [
        audio[s : s + seg_len] for s in range(0, len(audio), seg_len)
    ]
    assert len(chunks) == 3
    assert len(chunks[0]) == seg_len


# ── 2. 引擎（需要模型文件） ────────────────────────────────────────────
def _model_available() -> bool:
    return (MODEL_DIR / "Qwen3-ASR-Encoder.q4.onnx").exists() and (
        MODEL_DIR / "Qwen3-ASR-CTC.fp16.onnx"
    ).exists()


def _make_engine() -> QwenCTCEngine:
    return QwenCTCEngine(
        QwenCTCConfig(
            encoder_onnx_path=str(MODEL_DIR / "Qwen3-ASR-Encoder.q4.onnx"),
            ctc_onnx_path=str(MODEL_DIR / "Qwen3-ASR-CTC.fp16.onnx"),
            tokens_path=str(MODEL_DIR / "tokens.txt"),
            preprocessor_path=str(MODEL_DIR),
            num_threads=6,
            provider="cpu",
        )
    )


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == SAMPLE_RATE
        frames = w.getnframes()
        return (
            np.frombuffer(w.readframes(frames), dtype=np.int16).astype(np.float32)
            / 32768.0
        )


def test_engine_on_synthetic_speech():
    """引擎能识别出非空文本（空文本 = 特征归一化/帧率写错）"""
    if not _model_available():
        print("  [跳过] 没有模型文件")
        return

    wav = _find_audio()
    if wav is None:
        print("  [跳过] 没有测试音频（dev/test_asset_30s.wav 等）")
        return

    engine = _make_engine()
    engine.initialize()
    audio = _read_wav(wav)
    result = engine.decode(audio)

    assert result.text.strip(), "文本为空 —— 特征归一化或帧率算错了"
    assert len(result.tokens) == len(result.timestamps)
    assert "".join(result.tokens) == result.text
    assert result.timestamps == sorted(result.timestamps)
    assert result.timestamps[0] >= 0
    assert result.timestamps[-1] <= len(audio) / SAMPLE_RATE + 1.0
    print(f"  文本: {result.text[:60]}")


def test_engine_splits_long_audio():
    """超过 30 秒的音频切段后，时间戳要连续累加"""
    if not _model_available():
        print("  [跳过] 没有模型文件")
        return

    wav = _find_audio()
    if wav is None:
        print("  [跳过] 没有测试音频")
        return

    engine = _make_engine()
    engine.initialize()
    audio = _read_wav(wav)
    # 拼到 60 秒，保证一定跨过 30 秒的分段边界
    seg_len = int(30.0 * SAMPLE_RATE)
    doubled = np.concatenate([audio] * (2 * seg_len // len(audio) + 1))[: 2 * seg_len]
    result = engine.decode(doubled)
    assert result.text.strip()
    # 第二段的时间戳应该大于 30 秒
    assert result.timestamps[-1] > 30.0, "切段后的时间戳没有累加段偏移"
    print(f"  60s 文本长度: {len(result.text)}")


# ── 3. 拼接 ────────────────────────────────────────────────────────────
def test_token_merge_does_not_duplicate():
    """带重叠的两段拼起来，重叠部分不能被输出两遍"""
    from util.server.recognize_funasr import merge_tokens_by_sequence_matcher

    prev = list("今天天气很好我们出去散步")
    prev_ts = [0.1 * i for i in range(len(prev))]
    # 第二段与第一段重叠 "很好我们"
    new = list("很好我们出去玩耍")
    new_ts = [0.1 * i for i in range(len(new))]

    merged, merged_ts = merge_tokens_by_sequence_matcher(
        prev_tokens=prev,
        prev_timestamps=prev_ts,
        new_tokens=new,
        new_timestamps=new_ts,
        offset=len(prev) * 0.1,
        overlap=2.0,
        is_first_segment=False,
    )
    text = "".join(merged)
    assert text.count("很好我们") == 1, f"重叠部分重复了：{text}"
    assert len(merged) == len(merged_ts)
    print(f"  合并结果: {text}")


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
        test_decode_bytes_crosses_token_boundary,
        test_load_tokens_reads_base64,
        test_valid_frames_is_13fps,
        test_segment_split,
        test_engine_on_synthetic_speech,
        test_engine_splits_long_audio,
        test_token_merge_does_not_duplicate,
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
        sys.exit(1)
    print("全部通过")
