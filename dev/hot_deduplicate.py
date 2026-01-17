# 热词去重

import hashlib
import sqlite3
from pathlib import Path

from loguru import logger


class Deduplicator:
    """文件去重器"""

    def __init__(self):
        """初始化"""
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

    def deduplicate_file(self, file_path: Path) -> dict:
        """去重文件"""
        # 读取文件
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        # 处理去重
        unique_lines = []
        duplicates = 0
        skipped_lines = 0  # 记录跳过的行数

        for line in lines:
            # 检查是否应该跳过
            if self._should_skip_line(line):
                skipped_lines += 1
                # 将跳过的行直接添加到结果中（不参与去重）
                unique_lines.append(line)
                continue

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

        # 写入去重后的内容
        if duplicates > 0:
            file_path.write_text("".join(unique_lines), encoding="utf-8")

        return {
            "total": len(lines),
            "skipped": skipped_lines,  # 跳过的行数
            "processed": len(lines) - skipped_lines,  # 实际处理的行数
            "duplicates": duplicates,
            "unique": len(unique_lines) - skipped_lines,  # 不包含跳过的行
            "final_total": len(unique_lines),  # 最终文件总行数（包含跳过的行）
        }

    def close(self):
        """关闭连接"""
        self.conn.close()


if __name__ == "__main__":
    file_path = Path("hot-rag.txt")

    if file_path.exists():
        dedup = Deduplicator()
        stats = dedup.deduplicate_file(file_path)

        logger.info(f"文件总行数: {stats['total']}")
        logger.info(f"跳过行数（空行/#开头）: {stats['skipped']}")
        logger.info(f"实际处理行数: {stats['processed']}")
        logger.info(f"重复行数: {stats['duplicates']}")
        logger.info(f"去重后非重复行数: {stats['unique']}")
        logger.info(f"最终文件总行数: {stats['final_total']}")
        logger.success("去重完成!")

        dedup.close()
    else:
        logger.error(f"文件不存在: {file_path}")
