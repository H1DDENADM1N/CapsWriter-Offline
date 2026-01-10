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

console = Console()


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
                    }
                )
            except psutil.NoSuchProcess:
                info.update(
                    {
                        "name": "进程不存在",
                        "cmdline": "N/A",
                        "exe": "N/A",
                        "username": "N/A",
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
        table.add_row("执行路径", port_info["exe"])
        table.add_row("启动用户", port_info["username"])
        table.add_row("命令行", port_info["cmdline"])

        console.print(table)
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
    table.add_column("进程ID", justify="center", width=10)
    table.add_column("进程名称", style="green", width=20)
    table.add_column("启动用户", style="yellow", width=15)

    for info in port_infos:
        status_text = Text(info["status"], style=info["status_style"])
        pid_text = str(info["pid"]) if info["pid"] != "N/A" else "N/A"

        table.add_row(
            str(info["port"]), status_text, pid_text, info["name"], info["username"]
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
            console.print(f"  [cyan]命令行:[/] {info['cmdline']}")
            console.print(f"  [cyan]执行路径:[/] {info['exe']}")
