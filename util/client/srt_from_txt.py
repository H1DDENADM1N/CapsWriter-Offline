"""
脚本介绍：
    用 sherpa-onnx 生成的字幕，总归是会有一些缺陷
    例如有错字，分句不准

    所以除了自动生成的 srt 文件
    还额外生成了 txt 文件（每行一句），和 json 文件（包含每个字的时间戳）

    用户可以在识别完成后，手动修改 txt 文件，更正少量的错误，正确地分行
    然后调用这个脚本，处理 txt 文件

    脚本会找到同文件名的 json 文件，从里面得到字级时间戳，再按照 txt 里面的分行，
    生成正确的 srt 字幕
"""

import difflib
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import List

import srt
import typer
from rich import print


def lines_match_words(text_lines: List[str], words: List) -> List[srt.Subtitle]:
    """
    使用 SequenceMatcher 将分行文本与字级时间戳进行最优对齐

    词只有 start（模型原始信息）；句末时间在组句时生成：
    句末 end = min(下一行首词 start - 0.1s 间隙, 末词 start + 1s 上限)，
    最后一行用时长模型兜底（中文按字 0.2s、英文按词 0.35s）。

    Args:
        text_lines: 用户修改并分行后的文本列表
        words: 原始字级时间戳列表 [{'word': '字', 'start': 0.0}, ...]

    Returns:
        对齐后的 srt.Subtitle 列表
    """
    raw_tokens_text = "".join([w["word"] for w in words])
    all_lines_text = "".join([line.strip() for line in text_lines])

    # 标点和清理模式：动态涵盖所有已知中英文标点
    from util.constants import Punctuation

    punc_pattern = re.compile(rf"[{re.escape(Punctuation.ALL)}\s\d]")

    # 建立 token_idx 到字符偏移的映射
    token_chars = []
    token_indices = []
    for i, w in enumerate(words):
        word_clean = punc_pattern.sub("", w["word"].lower())
        for char in word_clean:
            token_chars.append(char)
            token_indices.append(i)
    pure_tokens_text = "".join(token_chars)

    # 全局对齐
    clean_all_lines = punc_pattern.sub("", all_lines_text.lower())
    sm = difflib.SequenceMatcher(None, pure_tokens_text, clean_all_lines)
    matches = sm.get_matching_blocks()

    # 字符偏移 -> word 索引映射
    char_to_word_map = {}
    for match in matches:
        for i in range(match.size):
            char_to_word_map[match.b + i] = token_indices[match.a + i]

    # 第一遍：每行映射到词索引范围
    line_word_ranges = []  # [(start_word_idx, end_word_idx, line_text), ...]
    current_char_offset = 0
    last_word_idx = 0

    for line in text_lines:
        line_clean = punc_pattern.sub("", line.lower())
        if not line_clean:
            continue

        line_len = len(line_clean)
        found_word_indices = [
            char_to_word_map[i]
            for i in range(current_char_offset, current_char_offset + line_len)
            if i in char_to_word_map
        ]

        if found_word_indices:
            start_word_idx = min(found_word_indices)
            end_word_idx = max(found_word_indices)
            last_word_idx = end_word_idx
        else:
            start_word_idx = min(last_word_idx + 1, len(words) - 1)
            end_word_idx = start_word_idx
        line_word_ranges.append((start_word_idx, end_word_idx, line.strip()))
        current_char_offset += line_len

    # 第二遍：由行间关系生成句末时间
    subtitle_list = []
    for k, (start_idx, end_idx, line_text) in enumerate(line_word_ranges):
        t1 = words[start_idx]["start"]
        last_start = words[end_idx]["start"]
        if k + 1 < len(line_word_ranges):
            next_start = words[line_word_ranges[k + 1][0]]["start"]
            t2 = min(next_start - 0.1, last_start + 1.0)
        else:
            # 最后一行：时长模型兜底（中文按字 0.2s、英文按词 0.35s）
            text = punc_pattern.sub("", line_text)
            cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
            en_words = len(
                [w for w in text.split() if w and not all("一" <= c <= "鿿" for c in w)]
            )
            t2 = last_start + max(cjk * 0.2 + en_words * 0.35, 0.1)
        t2 = max(t2, t1 + 0.1)  # 保证 end > start
        subtitle_list.append(
            srt.Subtitle(
                index=len(subtitle_list) + 1,
                content=line_text,
                start=timedelta(seconds=t1),
                end=timedelta(seconds=t2),
            )
        )

    return subtitle_list


def get_words(json_file: Path) -> list:
    # 读取分词 json 文件
    with open(json_file, "r", encoding="utf-8") as f:
        json_info = json.load(f)

    # 获取带有时间戳的分词列表（词只有 start，结束时刻在组句时生成）
    words = [
        {"word": token.replace("@", ""), "start": timestamp}
        for (timestamp, token) in zip(json_info["timestamps"], json_info["tokens"])
    ]

    return words


def get_lines(txt_file: Path) -> List[str]:
    # 读取分好行的字幕
    with open(txt_file, "r", encoding="utf-8") as f:
        text_lines = f.readlines()
    return text_lines


def generate_srt_file(words: list, text_lines: List[str], srt_file: Path):
    """根据提供的 words 和 text_lines 生成 srt 文件"""
    text_lines = [line.rstrip("，。？！,.?!\r\n ") for line in text_lines]
    subtitle_list = lines_match_words(text_lines, words)
    with open(srt_file, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitle_list))


def one_task(media_file: Path):
    # 配置要打开的文件
    txt_file = media_file.with_suffix(".txt")
    json_file = media_file.with_suffix(".json")
    srt_file = media_file.with_suffix(".srt")
    if (not txt_file.exists()) or (not json_file.exists()):
        print(f"无法找到 {media_file}对应的txt、json文件，跳过")
        return None

    # 获取带有时间戳的分词列表，获取分行稿件，匹配得到 srt
    words = get_words(json_file)
    text_lines = get_lines(txt_file)

    generate_srt_file(words, text_lines, srt_file)


def main(files: List[Path]):
    for file in files:
        one_task(file)
        print(f"写入完成：{file}")


if __name__ == "__main__":
    typer.run(main)
