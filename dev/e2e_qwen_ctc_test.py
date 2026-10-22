"""端到端测试：真实音频 -> CapsWriter 服务端 -> 识别结果

用法：
    .venv/Scripts/python.exe dev/e2e_qwen_ctc_test.py <wav> [port]

把 wav 按服务端协议（base64 float32 16kHz 单声道）推给服务端，
收服务端回的 JSON 结果（text / tokens / timestamps），并做基本断言。
"""

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

SEG_DURATION = 15.0
SEG_OVERLAP = 2.0
SAMPLE_RATE = 16000


def normalize(text: str) -> str:
    """去掉标点、数字与空白，只保留可比对的正文字符"""
    return "".join(
        ch
        for ch in text
        if ch not in PUNCTUATION_ALL and ch not in NUMBER_CHARS and not ch.isspace()
    )


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


async def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else default_wav()
    port = sys.argv[2] if len(sys.argv) > 2 else "6016"

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

    if not results:
        print("!! 没有收到任何结果")
        return 1

    final = results[-1]
    text = final["text"]
    tokens = final["tokens"]
    timestamps = final["timestamps"]

    print("\n" + "=" * 70)
    print("最终文本:", text)
    print("token 数:", len(tokens), " 时间戳数:", len(timestamps))
    print("前 15 个 token:", tokens[:15])
    print("前 15 个时间戳:", [round(t, 3) for t in timestamps[:15]])
    print("=" * 70)

    # 断言
    assert text.strip(), "文本为空"
    assert len(tokens) == len(timestamps), "tokens / timestamps 数量不一致"
    # tokens 是逐字符的原始识别结果；text 在服务端还会补标点、数字归一化、
    # 中英文间距调整，所以两者只在去掉标点/数字/空白后相等
    assert normalize(text) == normalize("".join(tokens)), (
        "join(tokens) 与去掉标点后的 text 不一致"
    )
    assert timestamps == sorted(timestamps), "时间戳非单调递增"
    assert timestamps[0] >= 0, "存在负时间戳"
    assert timestamps[-1] <= duration + 1.0, "时间戳超出音频长度"
    assert final["duration"] > 0, "duration 为 0"
    print("\n[OK] 端到端测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
