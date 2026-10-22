"""端到端测试：真实音频 -> CapsWriter 服务端 -> 识别结果

用法：
    .venv/Scripts/python.exe dev/e2e_qwen_ctc_test.py [wav] [port] [--expect MODE]

把 wav 按服务端协议（base64 float32 16kHz 单声道）推给服务端，
收服务端回的 JSON 结果（text / tokens / timestamps），按服务端当前
配置的三种模式之一做**内容级**断言：

    ctc       纯 CTC（解码器留空）：字级时间戳，tokens 逐字符对应
    two-pass  两遍（解码器 + enable_ctc=true）：LLM 文本 + NW 对齐时间戳
    llm       纯 LLM（解码器 + enable_ctc=false，或 CTC 头不可用）：
              无 token / 时间戳，文本自带标点

`--expect` 缺省为 `auto`：按返回结果的形态判定实际模式。三模式共用
同一段 websocket 收发与同一套断言代码，只由 `expect` 决定走哪一支。

脚本**不会自己起服务端**：改完 config.toml 必须重启服务端（multiprocessing
spawn，热改不生效），再跑本脚本。
"""

import argparse
import asyncio
import base64
import json
import sys
import time
import uuid
import wave
from pathlib import Path

import numpy as np
import websockets

# 直接运行 dev/e2e_qwen_ctc_test.py 时，sys.path[0] 是 dev/，
# 需要把仓库根目录加进去才能 import util.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from util.constants import Punctuation

# 服务端补标点用的标点集合 + ASCII 标点
PUNCTUATION_ALL = set(Punctuation.ALL) | set(",.!?;:\"'()[]{}-")
# 数字归一化会改动字符（中文数字 -> 阿拉伯数字），比较时两侧都剔除
NUMBER_CHARS = set("0123456789零一二三四五六七八九十百千万亿两")

# LLM 自带标点：两遍 / 纯 LLM 的文本必须至少含一个。纯 CTC 的 token 流
# 没有标点（标点只可能由服务端标点模型补到 text 上），用它来区分
# 「LLM 二遍真的跑了」和「悄悄退回纯 CTC」。
LLM_PUNCTUATION = set("，。！？；：、…—·,.!?;:'\"")

# 各音频的**内容**基准子串。只断「非空」挡不住退回纯 CTC 的回归，
# 必须断到具体内容（brief「断言怎么写才抓得住回归」）。
EXPECTED_SUBSTRING = {
    "zh.wav": "開放時間",
    "en.wav": "gold",
}

SEG_DURATION = 15.0
SEG_OVERLAP = 2.0
SAMPLE_RATE = 16000

# 需要 token 的两种模式（纯 CTC / 两遍）
TOKEN_MODES = ("ctc", "two-pass")


def normalize(text: str) -> str:
    """去掉标点、数字与空白，只保留可比对的正文字符"""
    return "".join(
        ch
        for ch in text
        if ch not in PUNCTUATION_ALL and ch not in NUMBER_CHARS and not ch.isspace()
    )


def has_llm_punctuation(text: str) -> bool:
    """文本里是否含 LLM 自带的标点（纯 CTC 的 token 流不会出现）"""
    return any(ch in LLM_PUNCTUATION for ch in text)


def expected_substring(wav: Path) -> str:
    """按音频文件名取内容基准子串；未知音频返回 None（只做形态断言）"""
    return EXPECTED_SUBSTRING.get(wav.name)


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1, "只支持单声道"
        assert w.getframerate() == SAMPLE_RATE, f"只支持 16kHz，当前 {w.getframerate()}"
        frames = w.getnframes()
        return np.frombuffer(w.readframes(frames), dtype=np.int16).astype(np.float32) / 32768.0


def default_wav():
    """默认音频：仓库自带的 SenseVoice 测试音频（16k 单声道）"""
    return (
        Path(__file__).resolve().parent.parent
        / "models"
        / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
        / "test_wavs"
        / "zh.wav"
    )


async def run_ws_session(wav: Path, port: str):
    """走一遍完整的 websocket 会话，返回 (最终结果, 音频时长)

    三种模式共用这一段：服务端模式由 config.toml 决定，客户端只管收发。
    """
    audio = read_wav(wav)
    duration = len(audio) / SAMPLE_RATE
    print(f"音频: {wav.name}  {duration:.2f}s  {len(audio)} samples")

    task_id = str(uuid.uuid1())
    url = f"ws://127.0.0.1:{port}"

    async with websockets.connect(url, subprotocols=["binary"], max_size=None) as ws:
        # 按 1 秒一片发送，模拟实时流
        chunk = SAMPLE_RATE  # 1s
        pos = 0
        while pos < len(audio):
            piece = audio[pos : pos + chunk]
            pos += chunk
            msg = {
                "task_id": task_id,
                "seg_duration": SEG_DURATION,
                "seg_overlap": SEG_OVERLAP,
                "is_final": False,
                "time_start": time.time(),
                "time_frame": time.time(),
                "source": "mic",
                "data": base64.b64encode(piece.tobytes()).decode("utf-8"),
            }
            await ws.send(json.dumps(msg))
            await asyncio.sleep(0.01)

        # 结束消息
        msg = {
            "task_id": task_id,
            "seg_duration": SEG_DURATION,
            "seg_overlap": SEG_OVERLAP,
            "is_final": True,
            "time_start": time.time(),
            "time_frame": time.time(),
            "source": "mic",
            "data": "",
        }
        await ws.send(json.dumps(msg))
        print("音频已发送完毕，等待结果…")

        # 收结果，直到拿到 is_final=True
        results = []
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
            except asyncio.TimeoutError:
                print("!! 等待超时")
                break
            res = json.loads(raw)
            # 服务端连接成功时会先发一条握手消息，跳过
            if res.get("type") == "connection_ack":
                print("<- 收到握手消息:", res.get("client_id"))
                continue
            results.append(res)
            print(
                f"<- 收到结果: is_final={res['is_final']} "
                f"duration={res['duration']:.2f}s "
                f"tokens={len(res['tokens'])} text_len={len(res['text'])}"
            )
            if res["is_final"]:
                break

    assert results, "没有收到任何结果"
    return results[-1], duration


def detect_mode(final) -> str:
    """按返回形态判定服务端实际生效的模式（--expect auto 用）"""
    tokens = final["tokens"]
    timestamps = final["timestamps"]
    if not tokens and not timestamps:
        return "llm"
    if len(tokens) == len(final["text"]):
        return "two-pass"
    return "ctc"


def check_result(final, duration: float, wav: Path, expect: str) -> str:
    """按模式做内容级断言，返回实际（或声明）的模式"""
    text = final["text"]
    tokens = final["tokens"]
    timestamps = final["timestamps"]
    mode = detect_mode(final) if expect == "auto" else expect

    # 先打印形态，断言挂了也能从输出里直接看出是哪一项
    print("\n" + "=" * 70)
    print(f"期望模式: {expect}   实际形态判定: {detect_mode(final)}")
    print("text:", text)
    print(
        f"len(text)={len(text)}  len(tokens)={len(tokens)}  "
        f"len(timestamps)={len(timestamps)}  "
        f"含 LLM 标点={has_llm_punctuation(text)}"
    )
    print("前 15 个 token:", tokens[:15])
    print("前 15 个时间戳:", [round(t, 3) for t in timestamps[:15]])
    print("=" * 70)

    # ── 三种模式共同的内容断言 ──
    assert text.strip(), "文本为空"
    assert final["duration"] > 0, "duration 为 0"

    if mode in TOKEN_MODES:
        assert tokens, f"{mode} 模式必须返回 token"
        assert len(tokens) == len(timestamps), (
            f"{mode} 模式 tokens / timestamps 数量不一致: "
            f"{len(tokens)} vs {len(timestamps)}"
        )
        # 时间戳单调不减（两遍模式的 NW 对齐也必须保证）
        assert timestamps == sorted(timestamps), f"{mode} 模式时间戳非单调递增"
        assert timestamps[0] >= 0, "存在负时间戳"
        assert timestamps[-1] <= duration + 1.0, "时间戳超出音频长度"
        # tokens 逐字符；text 还会补标点、数字归一化、中英文间距调整，
        # 所以只在去掉标点/数字/空白后相等
        assert normalize(text) == normalize("".join(tokens)), (
            f"{mode} 模式 join(tokens) 与去掉标点后的 text 不一致"
        )

    if mode == "two-pass":
        # 两遍模式的 text 是 LLM 文本，tokens 是它的逐字符拆分，必须等长
        assert len(tokens) == len(text), (
            "两遍模式 tokens 必须是 text 的逐字符拆分："
            f"len(tokens)={len(tokens)} len(text)={len(text)}"
        )
        # 内容基准 + LLM 自带标点：缺任一条都说明可能退回了纯 CTC
        sub = expected_substring(wav)
        if sub:
            assert sub in text, f"两遍模式文本缺少期望内容 {sub!r}: {text!r}"
        assert has_llm_punctuation(text), (
            f"两遍模式文本没有 LLM 自带标点（疑似退回纯 CTC）: {text!r}"
        )
    elif mode == "llm":
        # 纯 LLM 不得伪造 token / 时间戳
        assert tokens == [], f"纯 LLM 模式 tokens 必须为空，实际 {len(tokens)} 个"
        assert timestamps == [], (
            f"纯 LLM 模式 timestamps 必须为空，实际 {len(timestamps)} 个"
        )
        # 内容基准 + 标点：否则「LLM 没跑、text 恰好被填」也能过
        sub = expected_substring(wav)
        if sub:
            assert sub in text, f"纯 LLM 模式文本缺少期望内容 {sub!r}: {text!r}"
        assert has_llm_punctuation(text), (
            f"纯 LLM 模式文本没有自带标点: {text!r}"
        )
    elif mode == "ctc":
        # 纯 CTC 与改动前一致：字级时间戳 + 逐字符 token；标点只可能
        # 来自服务端标点模型，所以不断言 text 有/无标点，而是断 token 流
        # 里没有标点（CTC 头本身不产标点）
        assert not any(has_llm_punctuation(t) for t in tokens), (
            f"纯 CTC 模式的 token 流里出现了标点: {tokens[:20]}"
        )

    return mode


async def main():
    parser = argparse.ArgumentParser(description="QwenCTC 端到端测试")
    parser.add_argument("wav", nargs="?", default=None, help="16kHz 单声道 wav")
    parser.add_argument("port", nargs="?", default="6016", help="服务端端口")
    parser.add_argument(
        "--expect",
        choices=("auto", "ctc", "two-pass", "llm"),
        default="auto",
        help="期望的服务端模式；auto 按返回形态判定",
    )
    args = parser.parse_args()

    wav = Path(args.wav) if args.wav else default_wav()
    final, duration = await run_ws_session(wav, args.port)
    mode = check_result(final, duration, wav, args.expect)
    print(f"\n[OK] 端到端测试通过（模式 {mode}）")
    return 0


if __name__ == "__main__":
    # Windows 控制台默认 GBK，输出中文/符号前先切到 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
