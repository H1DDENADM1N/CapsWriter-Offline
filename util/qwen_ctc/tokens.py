# coding: utf-8
"""
Qwen3-CTC 紧凑词表（tokens.txt）加载与字节级反解

tokens.txt 每行格式：`<base64 原始字节>\t<紧凑 id>`，例如 `IQ==\t0`。

关键点（来自 Qwen3-ASR-CTC-GGUF 的「四个坑」之一）：
**Qwen3 的反解必须走字节**。紧凑词表只保留 89 个字节基元，一个中文字符
可能横跨多个 token，逐 token 各自 decode 会产生乱码（mojibake）。
正确做法是先把所有 token 的字节按顺序拼接，再整体 decode 一次。
"""

import base64
from pathlib import Path
from typing import Dict, List


def load_tokens(path: str | Path) -> Dict[int, bytes]:
    """
    加载紧凑词表

    Args:
        path: tokens.txt 路径

    Returns:
        {紧凑 id: 原始字节}
    """
    id2bytes: Dict[int, bytes] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            b64, _, tid = line.rpartition("\t")
            if not b64:
                # 容错：没有制表符时整行当作 base64
                b64, tid = line, str(len(id2bytes))
            id2bytes[int(tid)] = base64.b64decode(b64)
    return id2bytes


def decode_bytes(id2bytes: Dict[int, bytes], ids: List[int]) -> str:
    """
    把紧凑 id 序列反解成文本

    Args:
        id2bytes: {紧凑 id: 原始字节}
        ids: 紧凑 id 序列（已去掉 blank/unk、已折叠重复）

    Returns:
        解码后的文本（非法字节序列用 U+FFFD 替换，不抛异常）
    """
    if not ids:
        return ""
    raw = b"".join(id2bytes.get(i, b"") for i in ids)
    return raw.decode("utf-8", errors="replace")
