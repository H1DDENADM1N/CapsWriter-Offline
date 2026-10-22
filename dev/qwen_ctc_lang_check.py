# coding: utf-8
"""
Qwen3-CTC 头的「语言串味」诊断工具

用途：排查 Qwen3-ASR + CTC 头在某些音频上把外文转写成中文（译文）的问题。

背景（2026-10 排查结论）：
    `models/qwen-ctc-aiinfra4/` 的 CTC 头（v2，global_step 339707）是在
    「AI-infra 中英混读语料」上续训的，语料为中英对照字幕，于是 CTC 头学到
    了「英文语音 -> 中文字幕」这层映射。遇到 AI 技术领域的英文内容时，
    会把英文单词替换成对应的中文词（we -> 我们，or -> 或，intro to -> intro 到）。
    这不是解码 bug：换一个 CTC 头（v1）就完全消失。

用法：
    # 1) 抽音频（任意格式 -> 16k 单声道 wav）
    ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 out.wav

    # 2) 扫描整段音频，统计每个 30s 片段的中文占比
    .venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav

    # 3) 对比两个 CTC 头（验证是否与头有关）
    .venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav \
        --heads v1 v2

    # 4) 用独立引擎（SenseVoice）交叉验证音频里到底有没有中文人声
    .venv/Scripts/python.exe dev/qwen_ctc_lang_check.py out.wav --cross-check

输出：
    - 每个 30s 片段的汉字数 / 总字符数
    - 含有中文的片段占比
    - 出现「英文里夹中文」的具体位置（前后文）
"""

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL_DIR = ROOT / "models" / "qwen-ctc-aiinfra4"

# 可选的 CTC 头：名字 -> 文件名
HEADS = {
    "v1": "Qwen3-ASR-CTC.v1.fp16.onnx",
    "v2": "Qwen3-ASR-CTC.fp16.onnx",
    "v2-q4": "Qwen3-ASR-CTC.q4.onnx",
    "v2-q4f16": "Qwen3-ASR-CTC.q4f16.onnx",
}

SEGMENT_SEC = 30.0  # 编码器的 30 秒桶


def read_wav(path):
    """读 16k 单声道 wav -> float32"""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1:
            raise SystemExit(f"只支持单声道 wav，当前 {w.getnchannels()} 声道")
        if w.getframerate() != 16000:
            raise SystemExit(f"只支持 16kHz wav，当前 {w.getframerate()}Hz")
        n = w.getnframes()
        return np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0


def han_count(text):
    """汉字数量"""
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def is_han(ch):
    return "\u4e00" <= ch <= "\u9fff"


def find_mixed_spots(text, window=24):
    """找出「英文里夹中文」的位置，返回 (前后文, 中文片段) 列表"""
    spots = []
    i = 0
    while i < len(text):
        if is_han(text[i]):
            j = i
            while j < len(text) and is_han(text[j]):
                j += 1
            left = text[max(0, i - window) : i]
            right = text[j : j + window]
            spots.append((left, text[i:j], right))
            i = j
        else:
            i += 1
    return spots


def make_engine(head_path):
    from util.qwen_ctc import create_qwen_ctc_engine

    return create_qwen_ctc_engine(
        encoder_onnx_path=str(MODEL_DIR / "Qwen3-ASR-Encoder.q4.onnx"),
        ctc_onnx_path=str(head_path),
        tokens_path=str(MODEL_DIR / "tokens.txt"),
        preprocessor_path=str(MODEL_DIR),
    )


def scan_with_head(audio, head_path, show_spots):
    from util.qwen_ctc import create_qwen_ctc_engine  # noqa: F401

    engine = make_engine(head_path)
    n_seg = int(len(audio) / 16000 // SEGMENT_SEC)
    total_han = total_len = 0
    dirty = []
    try:
        for i in range(n_seg):
            seg = audio[int(i * SEGMENT_SEC * 16000) : int((i + 1) * SEGMENT_SEC * 16000)]
            text = engine.decode(seg).text
            h = han_count(text)
            total_han += h
            total_len += len(text)
            if h:
                dirty.append((i * SEGMENT_SEC, h, len(text), text))
        print(f"\n{'=' * 74}")
        print(f"CTC 头: {head_path.name}")
        print(f"片段数 {n_seg}，含中文片段 {len(dirty)} 个")
        print(
            f"汉字占比 {total_han}/{total_len} = "
            f"{total_han / max(total_len, 1) * 100:.2f}%"
        )
        for t, h, l, text in dirty:
            print(f"\n  --- t={t:.0f}s  han={h}/{l} ---")
            if show_spots:
                for left, mid, right in find_mixed_spots(text):
                    print(f"      …{left}[{mid}]{right}…")
            else:
                print(f"      {text[:120]}")
    finally:
        engine.cleanup()
    return len(dirty), n_seg


def cross_check(audio, starts):
    """用仓库自带的 SenseVoice 引擎独立转写同一段音频"""
    import sherpa_onnx

    sv_dir = ROOT / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    if not (sv_dir / "model.onnx").exists():
        print("（未安装 SenseVoice 模型，跳过交叉验证）")
        return
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(sv_dir / "model.onnx"),
        tokens=str(sv_dir / "tokens.txt"),
        num_threads=4,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        debug=False,
    )
    print(f"\n{'=' * 74}")
    print("交叉验证（SenseVoice 独立引擎）——若这里没有中文，说明音频里没有中文人声")
    for t0 in starts:
        seg = audio[int(t0 * 16000) : int((t0 + SEGMENT_SEC) * 16000)]
        if seg.size == 0:
            continue
        s = rec.create_stream()
        s.accept_waveform(16000, seg)
        rec.decode_stream(s)
        text = s.result.text
        print(f"\n  --- t0={t0:.0f}s  han={han_count(text)}/{len(text)} ---")
        print(f"      {text}")


def main():
    ap = argparse.ArgumentParser(description="Qwen3-CTC 头语言串味诊断")
    ap.add_argument("wav", help="16kHz 单声道 wav")
    ap.add_argument(
        "--heads",
        nargs="+",
        default=["v2"],
        choices=list(HEADS),
        help="要测试的 CTC 头（默认 v2 = aiinfra4）",
    )
    ap.add_argument(
        "--cross-check",
        action="store_true",
        help="用 SenseVoice 交叉验证音频内容",
    )
    ap.add_argument(
        "--spot",
        action="store_true",
        help="打印「英文里夹中文」的具体位置",
    )
    ap.add_argument("--start", type=float, default=0.0, help="交叉验证起始秒")
    args = ap.parse_args()

    wav = Path(args.wav)
    if not wav.exists():
        raise SystemExit(f"找不到文件: {wav}")
    audio = read_wav(wav)
    dur = len(audio) / 16000
    print(f"音频: {wav.name}  {dur:.1f}s")

    for name in args.heads:
        path = MODEL_DIR / HEADS[name]
        if not path.exists():
            print(f"（跳过 {name}：{path.name} 不存在）")
            continue
        scan_with_head(audio, path, args.spot)

    if args.cross_check:
        starts = [args.start + i * 60 for i in range(5)]
        cross_check(audio, starts)


if __name__ == "__main__":
    main()
