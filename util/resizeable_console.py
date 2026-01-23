"""
增强版 Console 类，添加 resize 上下文管理器方法
"""

from contextlib import contextmanager
from typing import Optional

from rich.console import Console as OriginalConsole


class Console(OriginalConsole):
    """
    增强版 Console，添加了 resize 上下文管理器方法

    使用示例：
        from resizeable_console import Console

        console = Console()

        with console.resize(width=45):
            console.print("临时宽度为45")
    """

    @contextmanager
    def resize(self, width: Optional[int] = None, height: Optional[int] = None):
        """
        临时改变控制台大小的上下文管理器

        Args:
            width (Optional[int]): 临时宽度，None 表示不改变
            height (Optional[int]): 临时高度，None 表示不改变

        Yields:
            Console: 修改尺寸后的控制台实例

        示例：
            with console.resize(width=45):
                console.print("临时宽度为45")
        """
        # 保存原来的尺寸
        old_width = self.width
        old_height = self.height

        try:
            # 设置新的尺寸
            if width is not None:
                self.width = width
            if height is not None:
                self.height = height
            yield self
        finally:
            # 恢复原来的尺寸
            self.width = old_width
            self.height = old_height


if __name__ == "__main__":
    # 测试代码
    console = Console()
    console.print("正常宽度输出")
    console.print("=" * console.width)

    with console.resize(width=45):
        console.print("临时宽度 45 输出")
        console.print("=" * console.width)
        console.rule()
        console.print("在这个上下文中，控制台宽度被临时设置为 45")

    console.print("恢复原宽度输出")
    console.print("=" * console.width)

    print("\n" + "=" * 50 + "\n")

    # 测试同时改变宽度和高度
    with console.resize(width=60, height=10):
        console.print(f"临时尺寸: {console.width}x{console.height}")
        for i in range(8):
            console.print(f"行 {i + 1}")
