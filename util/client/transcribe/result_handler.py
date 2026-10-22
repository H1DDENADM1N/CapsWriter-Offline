# coding: utf-8
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger as default_logger
from loguru._logger import Logger

from util.client import srt_from_txt
from util.client.hot_sub import hot_sub
from util.config import ClientConfig as Config


class ResultHandler:
    """结果处理器：负责文本格式化和文件保存"""

    @staticmethod
    def count_units(text: str) -> int:
        """统计切分单位：中日韩字符按字计，其余文本按空格分词计"""
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        words = len(
            [
                w
                for w in re.split(r"\s+", text)
                if w and not all("一" <= c <= "鿿" for c in w)
            ]
        )
        return cjk + words

    @classmethod
    def smart_split(cls, text: str, min_units: int = 3) -> str:
        """
        智能分行功能（两遍处理）
        1. 保留标点符号；英文标点需后跟空格才切分（避免 3.14 被切分）
        2. 第一遍只按强标点（。？.?!）切句，缩写点（如 Philip H. 的 H.）不切
        3. 第二遍在句内按弱标点（，,）分行：两侧片段都超过 min_units 才断，
           任一侧太短（英文按词、中文按字计数）就并入相邻片段
        """
        # 第一遍：按强标点切句
        parts = re.split(r"([。？]|[.?!](?:\s+|$))", text)
        sentences, buffer = [], ""
        for part in parts:
            clean_part = part.strip()
            if clean_part and clean_part in "。？.?!":
                buffer += part
                # 缩写点不切行：单个大写字母（如 Philip H. 的 H.）或常见头衔缩写（如 Dr.）
                if re.search(
                    r"(?:^|\s)(?:[A-Z]|Dr|Mr|Mrs|Ms|Prof|St|Jr|Sr|vs|etc)\.\s*$",
                    buffer,
                ):
                    continue
                sentences.append(buffer)
                buffer = ""
            else:
                buffer += part
        if buffer.strip():
            sentences.append(buffer)

        # 第二遍：句内按弱标点分行，两侧都够长才断
        lines = []
        for sent in sentences:
            parts = re.split(r"([，,](?:\s+|$))", sent)
            segs = []
            for i in range(0, len(parts), 2):
                segs.append(parts[i] + (parts[i + 1] if i + 1 < len(parts) else ""))
            for i, seg in enumerate(segs):
                lines.append(seg)
                nxt = segs[i + 1] if i + 1 < len(segs) else None
                if nxt is None or not seg.rstrip().endswith(("，", ",")):
                    continue  # 句末（强标点结尾）或最后一个片段，已断
                if cls.count_units(seg) > min_units and cls.count_units(nxt) > min_units:
                    continue  # 两侧都够长，保持断行
                # 任一侧太短，并入下一片段
                segs[i + 1] = seg + segs[i + 1]
                lines.pop()

        return "\n".join(lines)

    @classmethod
    def save_results(
        cls, file: Path, message: Dict[str, Any], logger: Optional[Logger] = None
    ) -> str:
        """
        保存转录结果到文件

        Returns:
            split_text: 切分后的文本（用于显示）
        """
        _logger = logger if logger is not None else default_logger
        _logger.debug(f"message keys: {message.keys()}")
        _logger.debug(f"原始text: {message.get('text', 'NOT FOUND')}")
        _logger.debug(f"text_accu: {message.get('text_accu', 'NOT FOUND')}")
        text_display = message["text"]
        if Config.use_hot_sub_when_transcribe_file:
            text_display = hot_sub(text_display, logger=_logger)
        text_accu = message.get("text_accu", message["text"])
        if Config.use_hot_sub_when_transcribe_file:
            text_accu = hot_sub(text_accu, debug=True, logger=_logger)
        text_split = cls.smart_split(text_accu)
        timestamps = message["timestamps"]
        tokens = message["tokens"]
        # 记录处理前后的变化
        _logger.debug(f"text_display: 处理后={text_display}")
        _logger.debug(f"text_accu: 处理后={text_accu}")
        # 文件名
        json_filename = file.with_suffix(".json")
        txt_filename = file.with_suffix(".txt")
        merge_filename = file.with_suffix(".merge.txt")

        # 1. 保存 merge.txt
        if Config.file_save_merge:
            with open(merge_filename, "w", encoding="utf-8") as f:
                f.write(text_accu)
            _logger.debug(f"保存合并文本: {merge_filename}")

        # 2. 保存 txt
        if Config.file_save_txt:
            with open(txt_filename, "w", encoding="utf-8") as f:
                f.write(text_split)
            _logger.debug(f"保存切分文本: {txt_filename}")

        # 3. 保存 json
        if Config.file_save_json:
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(
                    {"timestamps": timestamps, "tokens": tokens}, f, ensure_ascii=False
                )
            _logger.debug(f"保存 JSON 结果: {json_filename}")

        # 4. 生成 srt
        if Config.file_save_srt:
            # 构建 words 信息（无需依赖 json 文件；词只有 start，结束时刻在组句时生成）
            words = [
                {"word": token.replace("@", ""), "start": timestamp}
                for (timestamp, token) in zip(timestamps, tokens)
            ]

            text_lines = text_split.splitlines()
            srt_filename = file.with_suffix(".srt")

            if not words:
                # 纯 LLM 模式（含 0.6B）不产出 tokens，也就没有字级时间戳。
                # generate_srt_file 拿空 words 会在定行首时间时索引 -1 抛
                # IndexError，让整个文件转录失败 —— 这里直接跳过硬字幕并说明原因，
                # txt / json / merge.txt 照常落盘。
                _logger.info("当前识别模式没有字级时间戳，未生成 SRT 字幕")
            else:
                srt_from_txt.generate_srt_file(words, text_lines, srt_filename)
                _logger.debug(f"保存 SRT 字幕: {srt_filename}")

        # 5. 清理中间生成的 txt
        if not Config.file_save_txt and txt_filename.exists():
            try:
                txt_filename.unlink()
                logger.debug(f"清理中间 TXT 文件: {txt_filename}")
            except Exception as e:
                logger.warning(f"清理中间 TXT 文件失败: {e}")

        return text_display
