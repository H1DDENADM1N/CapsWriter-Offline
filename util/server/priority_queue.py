# coding: utf-8
"""
进程安全的优先级队列管理器

使用多个独立的 multiprocessing.Queue 实现优先级队列，
确保在多进程环境下的线程安全和进程安全。
"""

from multiprocessing import Queue
from typing import Optional

from util.server.classes import Task


class PriorityQueue:
    """
    进程安全的优先级队列

    使用多个独立的队列实现优先级：
    - 高优先级队列：麦克风输入任务
    - 低优先级队列：文件转录任务

    识别进程优先从高优先级队列获取任务，
    确保实时任务优先处理。
    """

    def __init__(self, manager=None):
        """初始化优先级队列

        Args:
            manager: multiprocessing.Manager 实例，用于创建进程安全的队列
        """
        # 使用传入的 manager 或创建默认的 Queue
        if manager is not None:
            self.queue_mic: Queue = manager.Queue()
            self.queue_file: Queue = manager.Queue()
        else:
            self.queue_mic: Queue = Queue()
            self.queue_file: Queue = Queue()

    def put(self, task: Task, priority: int) -> None:
        """
        将任务放入对应优先级的队列

        Args:
            task: 任务对象
            priority: 优先级（1=麦克风，10=文件）
        """
        if priority == 1:
            self.queue_mic.put(task)
        else:
            self.queue_file.put(task)

    def get(self, timeout: Optional[float] = None) -> Optional[Task]:
        """
        从优先级队列获取任务

        优先从高优先级队列获取，如果高优先级队列为空，
        则从低优先级队列获取。

        Args:
            timeout: 超时时间（秒）

        Returns:
            任务对象，如果超时则返回 None
        """
        # 优先检查高优先级队列
        if not self.queue_mic.empty():
            try:
                return self.queue_mic.get_nowait()
            except Exception:
                pass

        # 高优先级队列为空，检查低优先级队列
        if not self.queue_file.empty():
            try:
                return self.queue_file.get_nowait()
            except Exception:
                pass

        # 两个队列都为空，使用阻塞获取
        try:
            # 先尝试从高优先级队列获取
            return self.queue_mic.get(timeout=timeout)
        except Exception:
            # 高优先级队列超时，尝试从低优先级队列获取
            try:
                return self.queue_file.get(timeout=timeout)
            except Exception:
                return None

    def empty(self) -> bool:
        """
        检查所有队列是否为空

        Returns:
            True 如果所有队列都为空，否则 False
        """
        return self.queue_mic.empty() and self.queue_file.empty()

    def qsize(self) -> int:
        """
        获取所有队列的总大小

        Returns:
            队列中任务的总数
        """
        return self.queue_mic.qsize() + self.queue_file.qsize()

    def qsize_mic(self) -> int:
        """获取高优先级队列大小"""
        return self.queue_mic.qsize()

    def qsize_file(self) -> int:
        """获取低优先级队列大小"""
        return self.queue_file.qsize()
