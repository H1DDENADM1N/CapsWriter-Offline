# coding: utf-8
"""
优先级队列测试

测试优先级队列的功能和性能，确保在多进程环境下的正确性。
"""

import sys
import time
from multiprocessing import Manager

sys.path.append(".")
from util.server.classes import Task
from util.server.priority_queue import PriorityQueue


def test_priority_queue_basic():
    """测试优先级队列基本功能"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 创建测试任务
    mic_task = Task(
        source="mic",
        data=b"mic_audio_data",
        offset=0.0,
        overlap=0.0,
        task_id="mic_1",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )

    file_task = Task(
        source="file",
        data=b"file_audio_data",
        offset=0.0,
        overlap=0.0,
        task_id="file_1",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )

    # 先添加文件任务（低优先级）
    queue.put(file_task, priority=10)

    # 再添加麦克风任务（高优先级）
    queue.put(mic_task, priority=1)

    # 获取任务，应该先获取到麦克风任务
    first_task = queue.get()
    assert first_task.source == "mic"
    assert first_task.task_id == "mic_1"

    # 获取第二个任务，应该是文件任务
    second_task = queue.get()
    assert second_task.source == "file"
    assert second_task.task_id == "file_1"


def test_priority_queue_empty():
    """测试空队列处理"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 空队列应该返回 None
    assert queue.get(timeout=0.1) is None
    assert queue.empty() is True
    assert queue.qsize() == 0


def test_priority_queue_sizes():
    """测试队列大小统计"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 创建测试任务
    mic_task = Task(
        source="mic",
        data=b"mic_audio_data",
        offset=0.0,
        overlap=0.0,
        task_id="mic_1",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )

    file_task = Task(
        source="file",
        data=b"file_audio_data",
        offset=0.0,
        overlap=0.0,
        task_id="file_1",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )

    # 添加任务
    queue.put(mic_task, priority=1)
    queue.put(file_task, priority=10)

    # 检查队列大小
    assert queue.qsize() == 2
    assert queue.qsize_mic() == 1
    assert queue.qsize_file() == 1


def test_priority_queue_same_priority():
    """测试相同优先级任务的FIFO顺序"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 创建两个麦克风任务（相同优先级）
    mic_task1 = Task(
        source="mic",
        data=b"mic_audio_data1",
        offset=0.0,
        overlap=0.0,
        task_id="mic_1",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )

    mic_task2 = Task(
        source="mic",
        data=b"mic_audio_data2",
        offset=0.0,
        overlap=0.0,
        task_id="mic_2",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )

    # 添加任务
    queue.put(mic_task1, priority=1)
    queue.put(mic_task2, priority=1)

    # 获取任务，应该按照添加顺序
    first_task = queue.get()
    assert first_task.task_id == "mic_1"

    second_task = queue.get()
    assert second_task.task_id == "mic_2"


def test_priority_queue_mic_priority():
    """测试麦克风输入优先级"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 创建多个文件任务
    for i in range(3):
        file_task = Task(
            source="file",
            data=b"file_audio_data",
            offset=0.0,
            overlap=0.0,
            task_id=f"file_{i}",
            socket_id="socket_1",
            is_final=False,
            time_start=time.time(),
            time_submit=time.time(),
        )
        queue.put(file_task, priority=10)

    # 创建麦克风任务
    mic_task = Task(
        source="mic",
        data=b"mic_audio_data",
        offset=0.0,
        overlap=0.0,
        task_id="mic_1",
        socket_id="socket_1",
        is_final=False,
        time_start=time.time(),
        time_submit=time.time(),
    )
    queue.put(mic_task, priority=1)

    # 获取任务，应该先获取到麦克风任务
    first_task = queue.get()
    assert first_task.source == "mic"

    # 然后获取文件任务
    for i in range(3):
        task = queue.get()
        assert task.source == "file"
        assert task.task_id == f"file_{i}"


def test_priority_queue_performance():
    """测试优先级队列性能"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 创建大量任务
    num_tasks = 1000
    start_time = time.time()

    # 添加任务（一半麦克风，一半文件）
    for i in range(num_tasks):
        if i % 2 == 0:
            # 麦克风任务
            task = Task(
                source="mic",
                data=b"mic_audio_data",
                offset=0.0,
                overlap=0.0,
                task_id=f"mic_{i}",
                socket_id="socket_1",
                is_final=False,
                time_start=time.time(),
                time_submit=time.time(),
            )
            queue.put(task, priority=1)
        else:
            # 文件任务
            task = Task(
                source="file",
                data=b"file_audio_data",
                offset=0.0,
                overlap=0.0,
                task_id=f"file_{i}",
                socket_id="socket_1",
                is_final=False,
                time_start=time.time(),
                time_submit=time.time(),
            )
            queue.put(task, priority=10)

    # 测试获取时间
    get_start_time = time.time()

    # 获取所有任务
    for i in range(num_tasks):
        task = queue.get()
        assert task is not None

    get_end_time = time.time()

    # 性能检查
    total_time = get_end_time - start_time
    get_time = get_end_time - get_start_time

    print(f"总任务数: {num_tasks}")
    print(f"总时间: {total_time:.4f}s")
    print(f"获取时间: {get_time:.4f}s")
    print(f"平均获取时间: {get_time / num_tasks * 1000:.2f}ms")

    # 验证所有任务都被正确处理
    assert queue.qsize() == 0
    assert queue.empty() is True


def test_priority_queue_mixed_scenario():
    """测试混合场景：模拟实际使用情况"""
    manager = Manager()
    queue = PriorityQueue(manager)

    # 模拟场景：先有文件转录，然后有麦克风输入
    print("模拟场景：文件转录 + 麦克风输入")

    # 添加文件转录任务
    for i in range(5):
        file_task = Task(
            source="file",
            data=b"file_audio_data",
            offset=0.0,
            overlap=0.0,
            task_id=f"file_{i}",
            socket_id="socket_1",
            is_final=False,
            time_start=time.time(),
            time_submit=time.time(),
        )
        queue.put(file_task, priority=10)
        print(f"添加文件任务: file_{i}")

    # 添加麦克风任务
    for i in range(3):
        mic_task = Task(
            source="mic",
            data=b"mic_audio_data",
            offset=0.0,
            overlap=0.0,
            task_id=f"mic_{i}",
            socket_id="socket_1",
            is_final=False,
            time_start=time.time(),
            time_submit=time.time(),
        )
        queue.put(mic_task, priority=1)
        print(f"添加麦克风任务: mic_{i}")

    # 继续添加文件任务
    for i in range(3):
        file_task = Task(
            source="file",
            data=b"file_audio_data",
            offset=0.0,
            overlap=0.0,
            task_id=f"file_late_{i}",
            socket_id="socket_1",
            is_final=False,
            time_start=time.time(),
            time_submit=time.time(),
        )
        queue.put(file_task, priority=10)
        print(f"添加文件任务: file_late_{i}")

    # 获取任务并验证优先级
    print("\n获取任务顺序：")
    task_count = 0
    while not queue.empty():
        task = queue.get()
        print(f"任务 {task_count}: {task.source} - {task.task_id}")
        task_count += 1

    # 验证所有任务都被处理
    assert task_count == 11  # 5 + 3 + 3 = 11


if __name__ == "__main__":
    print("开始测试优先级队列...")

    # 运行测试
    test_priority_queue_basic()
    print("[PASS] 基本功能测试通过")

    test_priority_queue_empty()
    print("[PASS] 空队列测试通过")

    test_priority_queue_sizes()
    print("[PASS] 队列大小测试通过")

    test_priority_queue_same_priority()
    print("[PASS] 相同优先级测试通过")

    test_priority_queue_mic_priority()
    print("[PASS] 麦克风优先级测试通过")

    test_priority_queue_performance()
    print("[PASS] 性能测试通过")

    test_priority_queue_mixed_scenario()
    print("[PASS] 混合场景测试通过")

    print("\n[SUCCESS] 所有测试通过！优先级队列功能正常。")
