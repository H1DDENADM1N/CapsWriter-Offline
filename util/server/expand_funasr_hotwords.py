import asyncio
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

import pypinyin
from loguru import logger as default_logger
from loguru._logger import Logger

from util.config import ModelPaths
from util.fun_asr_gguf.core import logger


class Deduplicator:
    """文件去重器"""

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger if logger is not None else default_logger
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self._init_database()

    def _init_database(self):
        """初始化数据库"""
        self.cursor.execute("""
            CREATE TABLE lines (
                hash TEXT PRIMARY KEY,
                content TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def _hash_line(self, line: str) -> str:
        """计算行的哈希值"""
        return hashlib.md5(line.encode("utf-8")).hexdigest()

    def _should_skip_line(self, line: str) -> bool:
        """判断是否应该跳过该行（空行或#开头）"""
        stripped_line = line.strip()
        # 跳过空行和以#开头的行
        return not stripped_line or stripped_line.startswith("#")

    def deduplicate_list(self, lines: list) -> list:
        """
        对行列表进行去重
        同时过滤掉空行和注释行 (直接丢弃，不参与后续排序)

        Args:
            lines: 原始行列表

        Returns:
            去重并过滤后的有效行列表
        """
        unique_lines = []
        duplicates = 0
        skipped = 0
        processed = 0

        for line in lines:
            # 检查是否应该跳过 (空行/注释)
            if self._should_skip_line(line):
                skipped += 1
                continue

            processed += 1
            line_hash = self._hash_line(line)

            # 检查是否已存在
            self.cursor.execute("SELECT 1 FROM lines WHERE hash = ?", (line_hash,))

            if self.cursor.fetchone() is None:
                # 新行，插入数据库并保留
                self.cursor.execute(
                    "INSERT INTO lines (hash, content) VALUES (?, ?)", (line_hash, line)
                )
                unique_lines.append(line)
            else:
                duplicates += 1

        self.conn.commit()

        # 输出统计信息
        self.logger.trace(f"文件总行数: {len(lines)}")
        self.logger.trace(f"跳过行数（空行/#开头）: {skipped}")
        self.logger.trace(f"实际处理行数: {processed}")
        self.logger.trace(f"重复行数: {duplicates}")
        self.logger.trace(f"去重后非重复行数: {len(unique_lines)}")

        return unique_lines

    def close(self):
        """关闭连接"""
        self.conn.close()


class HotwordSorter:
    """热词排序器 - 英文和中文混合排序"""

    def __init__(self, case_sensitive: bool = False):
        """
        初始化排序器

        Args:
            case_sensitive: 是否区分大小写
        """
        self.case_sensitive = case_sensitive

    def is_english(self, text: str) -> bool:
        """判断是否为纯英文"""
        return text.strip() and all(ord(c) < 128 for c in text.strip())

    def get_sort_key(self, line: str) -> tuple:
        """
        获取排序键值
        """
        line = line.strip()
        if not line:
            return (
                2,
                "",
                line,
            )  # 空行排最后 (虽然在去重阶段已被过滤，但保留此逻辑以防万一)

        is_eng = self.is_english(line)

        if is_eng:
            # 英文：根据大小写敏感设置处理
            if self.case_sensitive:
                sort_str = line
            else:
                sort_str = line.lower()
        else:
            # 中文：转换为拼音
            pinyin_list = pypinyin.lazy_pinyin(
                line,
                style=pypinyin.Style.NORMAL,
                errors="ignore",
            )
            sort_str = " ".join(pinyin_list).lower()

        return (int(not is_eng), sort_str, line)

    def sort_lines(self, lines: list) -> list:
        """对行列表进行排序"""
        return sorted(lines, key=self.get_sort_key)


async def expand_funasr_hotwords(passed_logger) -> None:
    """扩展 FunASR 热词文件"""

    hot_zh_path = Path("hot-zh.txt")
    hot_en_path = Path("hot-en.txt")
    funasr_hotwords_path = ModelPaths.funasr_hotwords_path

    all_lines = []

    # 1. 读取阶段：一次性读取所有源文件内容到内存
    # 读取现有的 FunASR 热词文件
    if funasr_hotwords_path.exists():
        content = funasr_hotwords_path.read_text(encoding="utf-8")
        all_lines.extend(content.splitlines())

    # 读取 hot-zh.txt
    if hot_zh_path.exists():
        content = hot_zh_path.read_text(encoding="utf-8")
        all_lines.extend(content.splitlines())
        passed_logger.trace(f"已读取 {hot_zh_path}")

    # 读取 hot-en.txt
    if hot_en_path.exists():
        content = hot_en_path.read_text(encoding="utf-8")
        all_lines.extend(content.splitlines())
        passed_logger.trace(f"已读取 {hot_en_path}")

    passed_logger.trace(f"所有文件合并后总行数: {len(all_lines)}")

    # 2. 处理阶段：在内存中完成去重和过滤
    deduplicator = Deduplicator(logger=passed_logger)
    # 使用新的 deduplicate_list 方法，直接处理内存中的列表
    # 该方法内部已包含对空行和注释行的过滤逻辑
    unique_lines = deduplicator.deduplicate_list(all_lines)
    deduplicator.close()
    passed_logger.success("去重完成!")

    # 3. 处理阶段：在内存中完成排序
    sorter = HotwordSorter(case_sensitive=False)
    sorted_lines = sorter.sort_lines(unique_lines)

    # 显示部分结果预览
    # logger.info("排序结果预览（前10行）:")
    # for i, line in enumerate(sorted_lines[:10], 1):
    #     logger.info(f"  {i}. {line}")

    passed_logger.info(f"最终有效行数: {len(sorted_lines)}")

    # 4. 写入阶段：一次性将结果写回文件
    try:
        final_content = "\n".join(sorted_lines) + "\n"
        funasr_hotwords_path.write_text(final_content, encoding="utf-8")
        passed_logger.success(f"热词文件已更新并写入: {funasr_hotwords_path}")
    except Exception as e:
        passed_logger.error(f"写入文件失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(expand_funasr_hotwords(logger))
