# 检查端口占用
# uv run .\dev\check_port.py
# uv run .\dev\check_port.py 6016

import ctypes
import sys

import psutil
import win32api
import win32con
import win32security
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

console = Console()


def is_running_as_admin() -> bool:
    """检查脚本是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def get_process_privilege_info(pid: int) -> dict:
    """
    获取进程的特权归属信息。
    重点区分：管理员组的未提升进程 (Standard) 与 提升后的管理员进程。
    """
    try:
        # 1. 获取进程句柄和令牌
        h_process = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        h_token = win32security.OpenProcessToken(h_process, win32con.TOKEN_QUERY)

        # 2. 获取用户 SID
        token_user = win32security.GetTokenInformation(
            h_token, win32security.TokenUser
        )[0]
        sid_str = win32security.ConvertSidToStringSid(token_user)

        # 3. 检查特定的系统高权限账户 SID
        if sid_str == "S-1-5-18":
            return {
                "role": "SYSTEM",
                "description": "SYSTEM (Local System)",
                "color": "bold red",
            }
        if sid_str == "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464":
            return {
                "role": "TrustedInstaller",
                "description": "TrustedInstaller (Highest Privilege)",
                "color": "bold magenta",
            }
        if sid_str == "S-1-5-19":
            return {"role": "LocalSvc", "description": "Local Service", "color": "cyan"}
        if sid_str == "S-1-5-20":
            return {
                "role": "NetworkSvc",
                "description": "Network Service",
                "color": "cyan",
            }

        # 4. 检查是否属于 Administrators 组
        admins_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
        token_groups = win32security.GetTokenInformation(
            h_token, win32security.TokenGroups
        )

        is_in_admin_group = False
        for group_sid, attrs in token_groups:
            # 注意：group_sid 也是 PySID 对象，可以直接和 PySID 对象比较
            if group_sid == admins_sid:
                is_in_admin_group = True
                break

        # 获取账户名用于显示
        try:
            account_name, domain_name, _ = win32security.LookupAccountSid(
                None, token_user
            )
            user_str = f"{domain_name}\\{account_name}"
        except:
            user_str = sid_str

        # 5. 核心逻辑：判断是否实际提升 (UAC)
        if is_in_admin_group:
            is_elevated = win32security.GetTokenInformation(
                h_token, win32security.TokenElevation
            )
            if is_elevated:
                # 确实有管理员权限
                return {
                    "role": "Admin",
                    "description": f"Administrator (Elevated): {user_str}",
                    "color": "bold red",
                }
            else:
                # 账号是管理员，但进程未提升，权限等同于普通用户
                return {
                    "role": "User",
                    "description": f"Standard User (Unelevated): {user_str}",
                    "color": "green",
                }

        # 普通用户组
        # S-1-5-21-...-1001 这种格式就是普通域/本地用户
        return {
            "role": "User",
            "description": f"Standard User: {user_str}",
            "color": "green",
        }

    except Exception:
        # 回退逻辑：当无法读取令牌（通常因为当前脚本权限不足）时的猜测
        try:
            p = psutil.Process(pid)
            username = p.username()

            if "SYSTEM" in username.upper():
                return {"role": "SYSTEM", "description": username, "color": "bold red"}
            if "TRUSTEDINSTALLER" in username.upper():
                return {
                    "role": "TrustedInstaller",
                    "description": username,
                    "color": "bold magenta",
                }

            # 如果用户名包含 Administrator，但无法验证令牌状态
            # 为了防止误判为高权限，保守判定为普通用户
            parts = username.split("\\")
            actual_user_name = parts[-1] if parts else username
            if actual_user_name.upper() == "ADMINISTRATOR":
                return {
                    "role": "User",
                    "description": f"Admin Group (Unknown Status): {username}",
                    "color": "yellow",
                }

            return {"role": "User", "description": username, "color": "green"}
        except:
            return {
                "role": "Unknown",
                "description": "Access Denied / Unknown",
                "color": "dim",
            }


def get_process_tree(pid: int) -> dict:
    """
    获取进程树。
    向上追溯到根进程，向下显示目标进程的所有子孙。
    """
    try:
        target = psutil.Process(pid)

        path_pids = []
        current = target
        root_process = target

        while True:
            path_pids.append(current.pid)
            try:
                parent = current.parent()
                if parent is None:
                    break
                root_process = parent
                current = parent
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

        target_parent_pid = None
        if len(path_pids) > 1:
            target_parent_pid = path_pids[1]

        def build_tree(
            process: psutil.Process, target_pid: int, parent_pid: int
        ) -> dict:
            try:
                children = []
                immediate_children = process.children(recursive=False)

                is_target_parent_level = process.pid == parent_pid
                is_target_process = process.pid == target_pid
                is_ancestor = process.pid in path_pids

                should_filter = is_ancestor and (
                    not is_target_parent_level and not is_target_process
                )

                for child in immediate_children:
                    should_include = False
                    if should_filter:
                        if child.pid in path_pids:
                            should_include = True
                    else:
                        should_include = True

                    if should_include:
                        child_info = build_tree(child, target_pid, parent_pid)
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

        tree_data = build_tree(root_process, pid, target_parent_pid)
        return {
            "root_pid": root_process.pid,
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
    icon = "🔴" if node_data["is_target"] else "🔵"
    style = "bold red" if node_data["is_target"] else ""
    guide_style = "red bold" if node_data["is_target"] else "yellow"

    node_text = (
        f"{icon} [yellow]PID:[/] {node_data['pid']} | "
        f"[green]{node_data['name']}[/] | "
        f"状态: [blue]{node_data['status']}[/] | "
        f"内存: {node_data['memory']} | "
        f"CPU: {node_data['cpu']}"
    )
    if node_data["is_target"]:
        node_text += "  [bold]← 目标进程[/]"

    new_node = tree.add(node_text, style=style, guide_style=guide_style)
    for child in node_data["children"]:
        add_tree_node(new_node, child)
    return new_node


def display_process_tree(tree_info: dict):
    """显示进程树"""
    if not tree_info or not tree_info.get("tree"):
        console.print("[yellow]⚠ 无法获取进程树信息[/yellow]")
        return

    console.print("\n[bold cyan]🌳 进程树[/bold cyan]")
    tree = Tree(f"[bold]根进程 (PID: {tree_info['root_pid']})[/]", guide_style="cyan")
    add_tree_node(tree, tree_info["tree"])
    console.print(tree)


def check_port(port: int, check_privileged: bool = True) -> dict:
    """
    检查指定端口占用情况，返回端口信息字典
    """
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            info = {
                "port": port,
                "pid": conn.pid,
                "status": "已占用",
                "status_style": "red",
                "privilege_role": "Unknown",
                "privilege_desc": "Unknown",
                "privilege_color": "dim",
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

                if check_privileged:
                    priv_info = get_process_privilege_info(conn.pid)
                    info["privilege_role"] = priv_info["role"]
                    info["privilege_desc"] = priv_info["description"]
                    info["privilege_color"] = priv_info["color"]
                else:
                    info["privilege_role"] = "User"
                    info["privilege_desc"] = info["username"]
                    info["privilege_color"] = "dim"

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
                        "privilege_role": "N/A",
                        "privilege_desc": "N/A",
                        "privilege_color": "dim",
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
        "privilege_role": "N/A",
        "privilege_desc": "N/A",
        "privilege_color": "dim",
    }


def display_single_port(port_info: dict, show_privileged: bool = True):
    """显示单个端口的详细信息"""
    if port_info["status"] == "已占用":
        console.print(
            Panel.fit(
                f"[bold]端口 {port_info['port']}[/bold]",
                border_style="red",
                title="端口占用检查",
            )
        )

        table = Table(box=box.ROUNDED, show_header=False, style="cyan")
        table.add_column("属性", style="bold yellow", width=15)
        table.add_column("值", style="white")

        table.add_row("状态", f"[{port_info['status_style']}]{port_info['status']}[/]")
        table.add_row("进程ID", str(port_info["pid"]))
        table.add_row("进程名称", port_info["name"])

        if show_privileged:
            role_text = Text(port_info["privilege_desc"])
            role_text.style = port_info["privilege_color"]
            table.add_row("特权/权限", role_text)

        table.add_row("启动用户", port_info["username"])

        if port_info["cpu_percent"] != "N/A":
            table.add_row("CPU使用率", f"{port_info['cpu_percent']:.1f}%")
            table.add_row("内存使用率", f"{port_info['memory_percent']:.1f}%")
            memory_mb = port_info["memory_rss"] / 1024 / 1024
            table.add_row("内存占用", f"{memory_mb:.1f} MB")

        table.add_row("执行路径", port_info["exe"])
        table.add_row("命令行", port_info["cmdline"])
        console.print(table)

        display_process_tree(port_info["process_tree"])

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
                f"[bold green]✓ 端口 {port_info['port']} 空闲[/bold green]",
                border_style="green",
                title="端口状态",
            )
        )


def display_multiple_ports(port_infos: list, show_privileged: bool = True):
    """显示多个端口的概览"""
    console.print(
        Panel.fit(
            "[bold cyan]📊 端口占用情况概览[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    table = Table(
        title="端口状态",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold yellow",
    )
    table.add_column("端口", style="cyan", justify="center", width=8)
    table.add_column("状态", justify="center", width=8)

    if show_privileged:
        table.add_column("权限", justify="left", width=8)

    table.add_column("PID", justify="center", width=10)
    table.add_column("进程名称", style="green", width=40)
    table.add_column("启动用户", style="yellow", width=15)
    table.add_column("CPU%", justify="right", width=8)
    table.add_column("内存", justify="right", width=10)

    for info in port_infos:
        status_text = Text(info["status"], style=info["status_style"])
        pid_text = str(info["pid"]) if info["pid"] != "N/A" else "N/A"
        row_data = [str(info["port"]), status_text]

        if show_privileged:
            if info["status"] != "空闲":
                priv_text = Text(info["privilege_role"], style=info["privilege_color"])
            else:
                priv_text = Text("-", style="dim")
            row_data.append(priv_text)

        cpu_text = (
            f"{info['cpu_percent']:.1f}" if info["cpu_percent"] != "N/A" else "N/A"
        )
        mem_text = (
            f"{info['memory_rss'] / 1024 / 1024:.1f}"
            if info["memory_rss"] != "N/A"
            else "N/A"
        )

        row_data.extend([pid_text, info["name"], info["username"], cpu_text, mem_text])
        table.add_row(*row_data)

    console.print(table)

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
    is_admin = is_running_as_admin()
    show_privileged = is_admin

    if not is_admin:
        console.print(
            Panel(
                "[yellow]⚠ 当前脚本未以管理员权限运行[/]\n"
                "[dim]无法准确读取所有进程的详细特权令牌[/]",
                border_style="yellow",
            )
        )
        console.print()

    sys.path.append(".")
    from util.config import DeepLXConfig, ServerConfig

    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    if port_arg:
        port_info = check_port(port_arg, check_privileged=is_admin)
        display_single_port(port_info, show_privileged=is_admin)
        sys.exit()

    ports: list[int] = [
        int(ServerConfig.speech_recognition_port),
        int(ServerConfig.offline_translate_port),
        int(DeepLXConfig.online_translate_port),
    ]

    port_names = {
        int(ServerConfig.speech_recognition_port): "语音识别",
        int(ServerConfig.offline_translate_port): "离线翻译",
        int(DeepLXConfig.online_translate_port): "DeepLX在线翻译",
    }

    port_infos = []
    for port in ports:
        info = check_port(port, check_privileged=is_admin)
        info["name"] = f"{info['name']} ({port_names.get(port, '未知')})"
        port_infos.append(info)

    display_multiple_ports(port_infos, show_privileged=is_admin)

    used_ports = [info for info in port_infos if info["status"] == "已占用"]
    if used_ports:
        console.print("\n[bold yellow]🔍 占用端口详细信息:[/bold yellow]")
        for info in used_ports:
            console.print(
                Rule(
                    f"\n[yellow]━[/] [bold]端口 {info['port']}[/bold]",
                    align="left",
                    style="yellow",
                )
            )
            if info["cmdline"] != "N/A":
                console.print(f"  [cyan]命令行:[/] {info['cmdline']}")
            if info["exe"] != "N/A":
                console.print(f"  [cyan]执行路径:[/] {info['exe']}")

            if show_privileged and info["privilege_desc"] != "Unknown":
                console.print(
                    f"  [yellow]特权/权限:[/] [{info['privilege_color']}]{info['privilege_desc']}[/]"
                )
            if info.get("process_tree"):
                display_process_tree(info["process_tree"])
            console.print(Rule(style="yellow"))
