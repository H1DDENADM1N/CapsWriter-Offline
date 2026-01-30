# 检查端口占用
# 无参数调用，检查 CapsWriter Offline 所需的端口占用情况
# uv run .\dev\check_port.py

# uv run .\dev\check_port.py 6016
# uv run .\dev\check_port.py 6016 6017 1188

# 需要管理员权限运行以获取完整的进程令牌信息
# gsudo uv run .\dev\check_port.py
# gsudo uv run .\dev\check_port.py 6016
# gsudo uv run .\dev\check_port.py 6016 6017 1188

import ctypes
from typing import Any, Dict, List, Optional, Tuple, Union

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

# 类型别名
ProcessInfo = Dict[str, Any]
PrivilegeInfo = Dict[str, str]
TreeNode = Dict[str, Any]
ProcessTree = Dict[str, Any]
PortInfo = Dict[str, Any]


def is_running_as_admin() -> bool:
    """检查脚本是否以管理员权限运行"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_process_privilege_info(pid: int) -> PrivilegeInfo:
    """
    获取进程的特权归属信息

    Args:
        pid (int): 进程ID

    Returns:
        dict: 特权归属信息
            {"role": "SYSTEM", "description": "SYSTEM (Local System)", "color": "bold red"}
            {"role": "User", "description": "Standard User: Administrator", "color": "green"}
            ...

    """
    try:
        # 1. 获取进程句柄和令牌
        h_process: int = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION, False, pid
        )
        h_token: int = win32security.OpenProcessToken(h_process, win32con.TOKEN_QUERY)

        # 2. 获取用户 SID
        token_user: Tuple = win32security.GetTokenInformation(
            h_token, win32security.TokenUser
        )[0]
        sid_str: str = win32security.ConvertSidToStringSid(token_user)

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
        admins_sid: Any = win32security.ConvertStringSidToSid("S-1-5-32-544")
        token_groups: Tuple = win32security.GetTokenInformation(
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
            user_str: str = f"{domain_name}\\{account_name}"
        except Exception:
            user_str: str = sid_str

        # 5. 核心逻辑：判断是否实际提升 (UAC)
        if is_in_admin_group:
            is_elevated: bool = win32security.GetTokenInformation(
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
        except Exception:
            return {
                "role": "Unknown",
                "description": "Access Denied / Unknown",
                "color": "dim",
            }


def get_process_tree(pid: int) -> Optional[ProcessTree]:
    """
    获取进程树。
    向上追溯到根进程，向下显示目标进程的所有子孙。
    显示目标进程的兄弟进程和所有子进程。

    Args:
        pid (int): 目标进程ID

    Returns:
        dict: 进程树字典
        {
            "root": "进程树根进程信息",
            "children": [
                {
                    "process": "进程信息",
                    "children": [
                        {
                            "process": "进程信息",
                            "children": [...],
                        },
                        ...
                    ],
                },
                ...
            ],
        }
    """
    try:
        target = psutil.Process(pid)

        path_pids: List[int] = []
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

        target_parent_pid: Optional[int] = None
        if len(path_pids) > 1:
            target_parent_pid = path_pids[1]

        def build_tree(
            process: psutil.Process, target_pid: int, parent_pid: Optional[int]
        ) -> Optional[TreeNode]:
            try:
                children: List[TreeNode] = []
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
        if not tree_data:
            return None

        return {
            "root_pid": root_process.pid,
            "target_pid": pid,
            "tree": tree_data,
        }
    except psutil.NoSuchProcess:
        return None


def get_child_processes(pid: int) -> List[ProcessInfo]:
    """
    获取子进程信息

    Args:
        pid (int): 父进程ID

    Returns:
        list: 子进程信息列表
        [
            {
                "pid": 子进程ID,
                "name": 子进程名称,
                "status": 子进程状态,
                "memory": 子进程内存使用量,
                "cpu": 子进程CPU使用率,
                "cmdline": 子进程命令行参数,
            },
        ]
    """
    children: List[ProcessInfo] = []
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


def add_tree_node(port: int, tree: Tree, node_data: TreeNode) -> Tree:
    """
    递归添加节点到树

    Args:
        port (int): 端口号

        tree (rich.tree.Tree): Tree对象

        node_data: 节点数据
            {
                "pid": 子进程ID,
                "name": 子进程名称,
                "status": 子进程状态,
                "memory": 子进程内存使用量,
                "cpu": 子进程CPU使用率,
                "is_target": 是否为目标进程,
                "children": 子进程列表,
            }

    Returns:
        Tree (rich.tree.Tree): 添加了节点的树对象


    """
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
        node_text += f"  [bold]👈 占用 {port} 端口的进程[/]"

    new_node = tree.add(node_text, style=style, guide_style=guide_style)
    for child in node_data["children"]:
        add_tree_node(port, new_node, child)
    return new_node


def display_process_tree(port: int, tree_info: ProcessTree) -> None:
    """
    显示进程树

    Args:
        port (int): 端口号

        tree_info (dict): 进程树信息
            {
                "root_pid": 根进程ID,
                "target_pid": 目标进程ID,
                "tree": {
                    "pid": 子进程ID,
                    "name": 子进程名称,
                    "status": 子进程状态,
                    "memory": 子进程内存使用量,
                    "cpu": 子进程CPU使用率,
                    "is_target": 是否为目标进程,
                    "children": 子进程列表,
                }
            }
    """
    if not tree_info or not tree_info.get("tree"):
        console.print("[yellow]⚠ 无法获取进程树信息[/yellow]")
        return

    console.print("\n[bold cyan]🌳 进程树[/bold cyan]")
    tree = Tree(f"[bold]根进程 (PID: {tree_info['root_pid']})[/]", guide_style="cyan")
    add_tree_node(port, tree, tree_info["tree"])
    console.print(tree)


def check_port(port: int, check_privileged: bool = True) -> PortInfo:
    """
    检查指定端口占用情况，返回端口信息字典

    Args:
        port (int): 端口号

        check_privileged (bool, optional): 是否检查端口是否被root进程占用. Defaults to True.

    Returns:
        port_info (dict): 端口信息字典
            {
                "port": 端口号,
                "pid": 占用进程ID,
                "status": 端口状态, "已占用" 或 "空闲",
                "status_style": 端口状态样式, "red" 或 "green",
                "privilege_role": 端口所属角色, "User" 或 "SYSTEM",
                "privilege_desc": 端口所属角色描述, "Standard User" 或 "Administrator (Elevated)",
                "privilege_color": 端口所属角色颜色, "dim" 或 "bold red",
                "name": 占用进程名称,
                "cmdline": 占用进程命令行参数,
                "exe": 占用进程可执行文件路径,
                "username": 占用进程用户名,
                "create_time": 占用进程创建时间,
                "cpu_percent": 占用进程CPU使用率,
                "memory_percent": 占用进程内存使用率,
                "memory_rss": 占用进程内存使用量,
                "process_tree": 占用进程树信息,
                "child_processes": 占用进程的子进程信息,
            }
    """
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            info: PortInfo = {
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


def display_ports_info(
    port_infos: List[PortInfo], show_privileged: bool = True
) -> None:
    """
    显示端口概览

    Args:
        port_infos (list[dict]): 端口信息列表
            [
                {
                    "port": 端口号,
                    "pid": 占用进程ID,
                    "status": 端口状态, "已占用" 或 "空闲",
                    "status_style": 端口状态样式, "red" 或 "green",
                    "privilege_role": 端口所属角色, "User" 或 "SYSTEM",
                    "privilege_desc": 端口所属角色描述, "Standard User" 或 "Administrator (Elevated)",
                    "privilege_color": 端口所属角色颜色, "dim" 或 "bold red",
                    "name": 占用进程名称,
                    "cmdline": 占用进程命令行参数,
                    "exe": 占用进程可执行文件路径,
                    "username": 占用进程用户名,
                    "create_time": 占用进程创建时间,
                    "cpu_percent": 占用进程CPU使用率,
                    "memory_percent": 占用进程内存使用率,
                    "memory_rss": 占用进程内存使用量,
                    "process_tree": 占用进程树信息,
                    "child_processes": 占用进程的子进程信息,
                },
                ...
            ]
        show_privileged (bool, optional): 是否显示端点的权限信息. Defaults to True.

    """
    table = Table(
        expand=True,
        box=box.ROUNDED,
        header_style="bold blue",
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
        row_data: List[Union[str, Text]] = [str(info["port"]), status_text]

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

    all_ports: int = len(port_infos)
    used_ports: int = sum(1 for info in port_infos if info["status"] == "已占用")
    free_ports: int = all_ports - used_ports
    stats_columns = Columns(
        [
            Panel(
                f"[bold]{all_ports}[/]\n总端口数",
                border_style="blue",
                height=5,
            ),
            Panel(
                f"[bold green]{free_ports}[/]\n空闲端口",
                border_style="green",
                height=5,
            ),
            Panel(
                f"[bold red]{used_ports}[/]\n占用端口",
                border_style="red",
                height=5,
            ),
        ],
        padding=(0, 0),  # (上下, 左右) 间距
        expand=True,
    )

    combined_renderable = Columns(
        [stats_columns, table],
        padding=(0, 0),  # (上下, 左右) 间距
        expand=True,
    )
    console.print(
        Panel(
            combined_renderable,
            title="📊 端口状态",
            title_align="left",
            border_style="bold yellow",
        )
    )
    console.print("\n")


def display_ports_details(
    port_infos: List[PortInfo],
    show_privileged: bool = True,
    show_process_tree: bool = True,
    show_child_processes: bool = True,
) -> None:
    """
    显示端口详情

    Args:
        port_infos (list[dict]): 端口信息列表
            [
                {
                    "port": 端口号,
                    "pid": 占用进程ID,
                    "status": 端口状态, "已占用" 或 "空闲",
                    "status_style": 端口状态样式, "red" 或 "green",
                    "privilege_role": 端口所属角色, "User" 或 "SYSTEM",
                    "privilege_desc": 端口所属角色描述, "Standard User" 或 "Administrator (Elevated)",
                    "privilege_color": 端口所属角色颜色, "dim" 或 "bold red",
                    "name": 占用进程名称,
                    "cmdline": 占用进程命令行参数,
                    "exe": 占用进程可执行文件路径,
                    "username": 占用进程用户名,
                    "create_time": 占用进程创建时间,
                    "cpu_percent": 占用进程CPU使用率,
                    "memory_percent": 占用进程内存使用率,
                    "memory_rss": 占用进程内存使用量,
                    "process_tree": 占用进程树信息,
                    "child_processes": 占用进程的子进程信息,
                },
                ...
            ]
        show_privileged (bool, optional): 是否显示端点的权限信息.
        show_process_tree (bool, optional): 是否显示进程树. Defaults to True.
        show_child_processes (bool, optional): 是否显示进程的子进程. Defaults to True.
    """

    console.print("\n[bold yellow]🔍 占用端口详细信息:[/bold yellow]")
    for i, info in enumerate(port_infos, start=1):
        console.print(
            Rule(
                f"\n[yellow]━[/] [bold magenta]{i}. 端口 {info['port']}[/]",
                align="left",
                style="yellow",
            )
        )
        if info["cmdline"] != "N/A":
            console.print(
                Text.from_markup("  [cyan]命令行:[/] ") + Text(info["cmdline"])
            )  # 使用Text对象，避免语法高亮
        if info["exe"] != "N/A":
            console.print(f"  [cyan]执行路径:[/] {info['exe']}")

        if show_privileged and info["privilege_desc"] != "Unknown":
            console.print(
                f"  [yellow]权限:[/] [{info['privilege_color']}]{info['privilege_desc']}[/]"
            )
        if show_process_tree and info.get("process_tree"):
            display_process_tree(info["port"], info["process_tree"])
        if show_child_processes and info["child_processes"]:
            console.print("\n[bold cyan]📋 子进程列表[/bold cyan]")
            child_table = Table(
                box=box.SIMPLE, show_header=True, header_style="bold blue"
            )
            child_table.add_column("PID", style="cyan", width=10)
            child_table.add_column("名称", style="green", width=20)
            child_table.add_column("状态", width=10)
            child_table.add_column("内存", width=12)
            child_table.add_column("CPU", width=8)
            child_table.add_column("命令行", style="dim")

            for child in info["child_processes"]:
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
        console.print(Rule(style="yellow"))


def check_server_ports(logger) -> List[PortInfo]:
    """
    检查 CapsWriter Offline 服务端所需的端口占用情况

    语音识别端口：config.toml 中的 ServerConfig.speech_recognition_port
    离线翻译端口：config.toml 中的 ServerConfig.offline_translate_port

    Returns:
        list[dict]: 端口信息列表
    """
    try:
        from util.config import ServerConfig

        ports: List[int] = [
            int(ServerConfig.speech_recognition_port),
            int(ServerConfig.offline_translate_port),
        ]

        port_names: Dict[int, str] = {
            int(ServerConfig.speech_recognition_port): "语音识别",
            int(ServerConfig.offline_translate_port): "离线翻译",
        }

        port_infos: List[PortInfo] = []
        for port in ports:
            info: PortInfo = check_port(port, check_privileged=is_running_as_admin())
            info["name"] = f"{info['name']} ({port_names.get(port, '未知')})"
            port_infos.append(info)

        return port_infos
    except Exception as e:
        logger.error(f"检查端口时发生错误: {e}")
        return []


def check_port_server(logger) -> List[PortInfo] | None:
    """
    检查服务端端口并显示结果
    返回端口信息列表
    """
    is_admin = is_running_as_admin()

    # if not is_admin:
    # console.print(
    #     Panel(
    #         "[yellow]⚠ 当前脚本未以管理员权限运行[/]\n"
    #         "[dim]无法准确读取所有进程的详细特权令牌[/]",
    #         border_style="yellow",
    #     )
    # )
    # console.print("\n")

    port_infos = check_server_ports(logger)

    if not port_infos:
        logger.error("无法获取端口信息")
        return None  # 无法获取端口信息

    display_ports_info(port_infos, show_privileged=is_admin)

    used_ports: Tuple[int, ...] = tuple(
        info["port"] for info in port_infos if info["status"] == "已占用"
    )
    if used_ports:
        used_port_infos: List[PortInfo] = [
            info for info in port_infos if info["status"] == "已占用"
        ]
        display_ports_details(
            used_port_infos,
            show_privileged=is_admin,
            show_process_tree=True,
            show_child_processes=True,
        )
        return used_port_infos
    else:
        console.print("[bold green]✅ 所有端口均未占用[/bold green]")
        return None


if __name__ == "__main__":
    from loguru import logger as default_logger

    from util.config import ServerConfig as Config
    from util.server.cosmic import console

    console.print("检查服务端端口配置:")
    console.print(f"语音识别端口: {Config.speech_recognition_port}")
    console.print(f"离线翻译端口: {Config.offline_translate_port}")
    console.print("\n")

    check_port_server(default_logger)
