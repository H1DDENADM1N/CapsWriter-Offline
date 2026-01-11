# 检查端口占用
# uv run .\dev\check_port.py
# uv run .\dev\check_port.py 6016

import psutil
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

console = Console()


def get_process_tree(pid: int) -> dict:
    """获取进程树，包含所有兄弟进程，标记目标进程"""
    try:
        target = psutil.Process(pid)

        # 追踪到根进程，记录路径上的所有PID
        path_pids = []
        current = target
        root = current
        path_pids.append(current.pid)

        while True:
            try:
                parent = current.parent()
                if parent is None:
                    break
                root = parent
                current = parent
                path_pids.append(current.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

        def build_tree(process: psutil.Process, target_pid: int) -> dict:
            """递归构建进程树，并标记目标进程"""
            try:
                children = []
                for child in process.children():
                    child_info = build_tree(child, target_pid)
                    if child_info:
                        children.append(child_info)

                return {
                    "pid": process.pid,
                    "name": process.name(),
                    "status": process.status(),
                    "memory": f"{process.memory_info().rss / 1024 / 1024:.1f} MB",
                    "cpu": f"{process.cpu_percent(interval=0.1):.1f}%",
                    "is_target": process.pid == target_pid,
                    "children": children,
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None

        tree_data = build_tree(root, pid)

        return {
            "root_pid": root.pid,
            "target_pid": pid,
            "tree": tree_data,
        }
    except psutil.NoSuchProcess:
        return None


def get_child_processes(pid: int) -> list:
    """获取子进程信息"""
    children = []
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            try:
                children.append(
                    {
                        "pid": child.pid,
                        "name": child.name(),
                        "status": child.status(),
                        "memory": f"{child.memory_info().rss / 1024 / 1024:.1f} MB",
                        "cpu": f"{child.cpu_percent(interval=0.1):.1f}%",
                        "cmdline": " ".join(child.cmdline()),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except psutil.NoSuchProcess:
        pass

    return children


def add_tree_node(tree: Tree, node_data: dict) -> Tree:
    """递归添加节点到树"""
    # 确定图标和样式
    if node_data["is_target"]:
        icon = "🔴"
        style = "bold red"
        guide_style = "red bold"
    else:
        icon = "🔵"
        style = ""
        guide_style = "yellow"

    # 创建节点文本
    node_text = (
        f"{icon} [yellow]PID:[/] {node_data['pid']} | "
        f"[green]{node_data['name']}[/] | "
        f"状态: [blue]{node_data['status']}[/] | "
        f"内存: {node_data['memory']} | "
        f"CPU: {node_data['cpu']}"
    )

    if node_data["is_target"]:
        node_text += " [bold]← 目标进程[/]"

    # 添加节点
    new_node = tree.add(node_text, style=style, guide_style=guide_style)

    # 递归添加子节点
    for child in node_data["children"]:
        add_tree_node(new_node, child)

    return new_node


def display_process_tree(tree_info: dict):
    """显示进程树，包含兄弟进程"""
    if not tree_info or not tree_info.get("tree"):
        console.print("[yellow]⚠ 无法获取进程树信息[/yellow]")
        return

    console.print("\n[bold cyan]🌳 进程树[/bold cyan]")

    # 创建根树
    tree = Tree(f"[bold]根进程 (PID: {tree_info['root_pid']})[/]", guide_style="cyan")

    # 递归添加节点
    add_tree_node(tree, tree_info["tree"])

    console.print(tree)


def check_port(port: int) -> dict:
    """检查指定端口占用情况，返回端口信息字典"""
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            info = {
                "port": port,
                "pid": conn.pid,
                "status": "已占用",
                "status_style": "red",
            }
            try:
                p = psutil.Process(conn.pid)
                info.update(
                    {
                        "name": p.name(),
                        "cmdline": " ".join(p.cmdline()),
                        "exe": p.exe() if hasattr(p, "exe") else "N/A",
                        "username": p.username() if hasattr(p, "username") else "N/A",
                        "create_time": p.create_time(),
                        "cpu_percent": p.cpu_percent(interval=0.1),
                        "memory_percent": p.memory_percent(),
                        "memory_rss": p.memory_info().rss,
                    }
                )

                # 获取进程树和子进程信息
                tree_info = get_process_tree(conn.pid)
                info["process_tree"] = tree_info
                info["child_processes"] = get_child_processes(conn.pid)

            except psutil.NoSuchProcess:
                info.update(
                    {
                        "name": "进程不存在",
                        "cmdline": "N/A",
                        "exe": "N/A",
                        "username": "N/A",
                        "create_time": "N/A",
                        "cpu_percent": "N/A",
                        "memory_percent": "N/A",
                        "memory_rss": "N/A",
                        "process_tree": None,
                        "child_processes": [],
                    }
                )
            return info

    return {
        "port": port,
        "status": "空闲",
        "status_style": "green",
        "pid": "N/A",
        "name": "N/A",
        "cmdline": "N/A",
        "exe": "N/A",
        "username": "N/A",
        "create_time": "N/A",
        "cpu_percent": "N/A",
        "memory_percent": "N/A",
        "memory_rss": "N/A",
        "process_tree": None,
        "child_processes": [],
    }


def display_single_port(port_info: dict):
    """显示单个端口的详细信息"""
    if port_info["status"] == "已占用":
        console.print(
            Panel.fit(
                f"[bold]端口 {port_info['port']}[/bold]",
                border_style="red",
                title="端口占用检查",
            )
        )

        # 创建详细信息表
        table = Table(box=box.ROUNDED, show_header=False, style="cyan")
        table.add_column("属性", style="bold yellow", width=15)
        table.add_column("值", style="white")

        table.add_row("状态", f"[{port_info['status_style']}]{port_info['status']}[/]")
        table.add_row("进程ID", str(port_info["pid"]))
        table.add_row("进程名称", port_info["name"])
        table.add_row("启动用户", port_info["username"])

        # 添加性能信息
        if port_info["cpu_percent"] != "N/A":
            table.add_row("CPU使用率", f"{port_info['cpu_percent']:.1f}%")
            table.add_row("内存使用率", f"{port_info['memory_percent']:.1f}%")
            memory_mb = port_info["memory_rss"] / 1024 / 1024
            table.add_row("内存占用", f"{memory_mb:.1f} MB")

        table.add_row("执行路径", port_info["exe"])
        table.add_row("命令行", port_info["cmdline"])

        console.print(table)

        # 显示进程树
        display_process_tree(port_info["process_tree"])

        # 显示子进程
        if port_info["child_processes"]:
            console.print("\n[bold yellow]📋 子进程列表[/bold yellow]")
            child_table = Table(
                box=box.SIMPLE, show_header=True, header_style="bold magenta"
            )
            child_table.add_column("PID", style="cyan", width=10)
            child_table.add_column("名称", style="green", width=20)
            child_table.add_column("状态", width=10)
            child_table.add_column("内存", width=12)
            child_table.add_column("CPU", width=8)
            child_table.add_column("命令行", style="dim")

            for child in port_info["child_processes"]:
                status_style = "green" if child["status"] == "running" else "yellow"
                child_table.add_row(
                    str(child["pid"]),
                    child["name"],
                    f"[{status_style}]{child['status']}[/]",
                    child["memory"],
                    child["cpu"],
                    child["cmdline"],
                )

            console.print(child_table)

    else:
        console.print(
            Panel.fit(
                f"[bold green]✓ 端口 {port_info['port']} 可用[/bold green]",
                border_style="green",
                title="端口状态",
            )
        )


def display_multiple_ports(port_infos: list):
    """显示多个端口的概览"""
    console.print(
        Panel.fit(
            "[bold cyan]📊 端口占用情况概览[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    # 创建主表格
    table = Table(
        title="端口状态",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold yellow",
    )

    table.add_column("端口", style="cyan", justify="center", width=10)
    table.add_column("状态", justify="center", width=10)
    table.add_column("PID", justify="center", width=10)
    table.add_column("进程名称", style="green", width=20)
    table.add_column("启动用户", style="yellow", width=15)
    table.add_column("CPU%", justify="right", width=8)
    table.add_column("内存(MB)", justify="right", width=10)

    for info in port_infos:
        status_text = Text(info["status"], style=info["status_style"])
        pid_text = str(info["pid"]) if info["pid"] != "N/A" else "N/A"

        # 性能信息
        cpu_text = (
            f"{info['cpu_percent']:.1f}" if info["cpu_percent"] != "N/A" else "N/A"
        )
        mem_text = (
            f"{info['memory_rss'] / 1024 / 1024:.1f}"
            if info["memory_rss"] != "N/A"
            else "N/A"
        )

        table.add_row(
            str(info["port"]),
            status_text,
            pid_text,
            info["name"],
            info["username"],
            cpu_text,
            mem_text,
        )

    console.print(table)

    # 显示统计信息
    used_ports = sum(1 for info in port_infos if info["status"] == "已占用")
    free_ports = len(port_infos) - used_ports

    stats_columns = Columns(
        [
            Panel(f"[bold]{len(port_infos)}[/]\n总端口数", border_style="blue"),
            Panel(f"[bold green]{free_ports}[/]\n空闲端口", border_style="green"),
            Panel(f"[bold red]{used_ports}[/]\n占用端口", border_style="red"),
        ],
        expand=True,
    )

    console.print("\n")
    console.print(Panel(stats_columns, title="📈 统计信息", border_style="yellow"))


if __name__ == "__main__":
    import sys

    port: int = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    if port:
        # 检查单个端口
        port_info = check_port(port)
        display_single_port(port_info)
        sys.exit()

    sys.path.append(".")
    from util.config import DeepLXConfig, ServerConfig

    # 检查多个端口
    ports: list[int] = [
        int(ServerConfig.speech_recognition_port),
        int(ServerConfig.offline_translate_port),
        int(DeepLXConfig.online_translate_port),
    ]

    # 添加端口名称说明
    port_names = {
        int(ServerConfig.speech_recognition_port): "语音识别",
        int(ServerConfig.offline_translate_port): "离线翻译",
        int(DeepLXConfig.online_translate_port): "DeepLX在线翻译",
    }

    # 收集所有端口信息
    port_infos = []
    for port in ports:
        info = check_port(port)
        info["name"] = f"{info['name']} ({port_names.get(port, '未知')})"
        port_infos.append(info)

    # 显示多个端口信息
    display_multiple_ports(port_infos)

    # 如果有占用的端口，显示详细信息
    used_ports = [info for info in port_infos if info["status"] == "已占用"]
    if used_ports:
        console.print("\n[bold yellow]🔍 占用端口详细信息:[/bold yellow]")
        for info in used_ports:
            console.print(
                f"\n[yellow]━[/] [bold]端口 {info['port']}[/bold] [yellow]━[/]"
            )
            if info["cmdline"] != "N/A":
                console.print(f"  [cyan]命令行:[/] {info['cmdline']}")
            if info["exe"] != "N/A":
                console.print(f"  [cyan]执行路径:[/] {info['exe']}")

            # 显示进程树
            if info.get("process_tree"):
                display_process_tree(info["process_tree"])
