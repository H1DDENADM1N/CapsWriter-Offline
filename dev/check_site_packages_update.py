import os
import re
import subprocess
from pathlib import Path

import tomlkit
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table


def get_outdated_packages():
    """
    获取过时的包信息

    Returns:
        list[dict]: 包信息列表  例如：{'name': 'loguru', 'current': '0.7.0', 'latest': '0.7.3', 'type': 'wheel'}

    """
    def run_outdated(no_cache: bool) -> "subprocess.CompletedProcess[str]":
        """执行 uv pip list --outdated；no_cache=True 时追加 --no-cache 绕过缓存。

        将 uv 的临时目录与缓存目录重定向到工作区内（.uv_tmp / .uv_cache），
        使脚本在受限/沙箱环境中也能运行——不依赖系统 %TEMP% 与
        AppData\\Local\\uv\\cache 的写入权限（这些路径常被沙箱/防护拦截，导致
        os error 5 拒绝访问）。
        """
        base = Path.cwd().resolve()
        tmp_dir = base / ".uv_tmp"
        cache_dir = base / ".uv_cache"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["TMP"] = str(tmp_dir)
        env["TEMP"] = str(tmp_dir)
        env["TMPDIR"] = str(tmp_dir)
        env["UV_CACHE_DIR"] = str(cache_dir)

        cmd = ["uv", "pip", "list", "--outdated", "--format=columns"]
        if no_cache:
            cmd.insert(1, "--no-cache")
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=True,
        )

    try:
        # 使用 rich 的进度条显示加载状态
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=Console(stderr=True),
        ) as progress:
            task = progress.add_task("🔍 检查可更新的包...", total=None)

            try:
                result = run_outdated(no_cache=False)
            except subprocess.CalledProcessError:
                # uv 缓存被占用/不可写时（例如 sdists-v9\.git 被其它进程锁住），
                # 自动改用 --no-cache 绕过缓存重新查询。
                result = run_outdated(no_cache=True)
                rprint(
                    "[yellow]⚠ 标准模式受 uv 缓存影响，已自动改用 --no-cache 完成检查。[/yellow]"
                )

            progress.update(task, description="✅ 检查完成")
    except FileNotFoundError:
        rprint(
            "[red]❌ 未找到 'uv' 可执行文件。请确保 uv 已安装并在 PATH 中。[/red]"
        )
        return []
    except subprocess.CalledProcessError as e:
        rprint(
            "[red]❌ 标准检查和 --no-cache 回退均失败（退出码 "
            + str(e.returncode)
            + "）。\n[/red]"
        )
        if e.stderr:
            rprint(
                "[red]错误详情：[/red]\n[yellow]" + e.stderr.strip() + "[/yellow]"
            )
        return []

    outdated_packages = []
    lines = result.stdout.strip().split("\n")

    # 跳过标题行和分隔线
    for line in lines[2:]:
        if line.strip():
            # 实际格式: Package | Version | Latest | Type
            parts = re.split(r"\s+", line.strip())
            outdated_packages.append(
                {
                    "name": parts[0],
                    "current": parts[1],
                    "latest": parts[2],
                    "type": parts[3],
                }
            )

    return outdated_packages


def format_rich_table_output(outdated_packages):
    """
    使用 rich 格式化为表格输出

    Args:
        outdated_packages (list[dict]): 包信息列表  例如：{'name': 'loguru', 'current': '0.7.0', 'latest': '0.7.3', 'type': 'wheel'}
    """
    console = Console()
    packages = outdated_packages
    title = "🔄 可更新的包"

    if not packages:
        console.print(
            Panel("✅ 所有包都是最新的！", title="检查结果", border_style="green")
        )
        return

    # 创建表格
    table = Table(title=title, show_header=True, header_style="bold magenta")

    table.add_column("包名", style="cyan", no_wrap=True, width=25)
    table.add_column("当前版本", style="blue", width=15)
    table.add_column("最新版本", style="green", width=15)
    table.add_column("类型", style="yellow", width=10)
    table.add_column("项目依赖", style="red", width=8)

    for pkg in packages:
        is_project = "[green]✅[/green]" if pkg.get("in_project") else "[red]❌[/red]"

        table.add_row(
            pkg["name"],
            pkg["current"],
            pkg["latest"],
            pkg.get("type", "N/A"),
            is_project,
        )

    console.print(table)


def check_pyproject_deps():
    """
    检查 pyproject.toml 中的依赖

    Returns:
        list[str]: 包名列表
    """
    toml_path = Path("pyproject.toml")

    if not toml_path.exists():
        return None

    with open(toml_path, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())
    project_deps = []

    # 收集 project.dependencies
    if "project" in doc and "dependencies" in doc["project"]:
        for dep in doc["project"]["dependencies"]:
            if isinstance(dep, str):
                pkg_name = (
                    dep.split(">=")[0]
                    .split("==")[0]
                    .split("~=")[0]
                    .split("[")[0]
                    .strip()
                )
                project_deps.append(pkg_name.lower())

    # 收集 project.optional-dependencies
    if "project" in doc and "optional-dependencies" in doc["project"]:
        for group_deps in doc["project"]["optional-dependencies"].values():
            for dep in group_deps:
                if isinstance(dep, str):
                    pkg_name = (
                        dep.split(">=")[0]
                        .split("==")[0]
                        .split("~=")[0]
                        .split("[")[0]
                        .strip()
                    )
                    project_deps.append(pkg_name.lower())

    # 收集 dependency-groups
    if "dependency-groups" in doc:
        for group_deps in doc["dependency-groups"].values():
            for dep in group_deps:
                if isinstance(dep, str):
                    pkg_name = (
                        dep.split(">=")[0]
                        .split("==")[0]
                        .split("~=")[0]
                        .split("[")[0]
                        .strip()
                    )
                    project_deps.append(pkg_name.lower())

    return project_deps


def display_statistics(outdated_packages, project_deps=None):
    """
    显示统计信息

    Args:
        outdated_packages (list[dict]): 包信息列表  例如：{'name': 'loguru', 'current': '0.7.0', 'latest': '0.7.3', 'type': 'wheel'}
        project_deps (list[str], optional): 项目依赖包列表

    Returns:
        None
    """
    console = Console()

    outdated_count = len(outdated_packages)
    if outdated_count > 0:
        # 创建统计面板
        stats_text = f"[bold green]{outdated_count}[/bold green] 个包可以更新"

        if project_deps:
            project_outdated = [
                p for p in outdated_packages if p["name"].lower() in project_deps
            ]
            if project_outdated:
                stats_text += f"\n其中 [bold blue]{len(project_outdated)}[/bold blue] 个是项目依赖"
                stats_text += "\n\n💡 非项目依赖，运行 '[cyan]uv pip install <包名> == <最新版本>[/cyan]' 测试新版是否兼容"
                stats_text += f"\n\n💡 项目依赖，运行 '[cyan]uv add [--group <组名>] [--optional dev] <包名> >= <最新版本>[/cyan]' 测试新版是否兼容"
                stats_text += "\n\n💡 修改 '[cyan]pyproject.toml[/cyan]' 并运行 '[cyan]uv sync --all-groups --all-extras[/cyan]'"

        console.print(Panel(stats_text, title="📊 统计信息", border_style="blue"))
    else:
        console.print(
            Panel("🎉 所有包都是最新的！", title="检查结果", border_style="green")
        )


def check_site_packages_update():
    """主函数"""
    console = Console()

    # 显示开始信息
    console.print(
        Panel("🔍 检查包更新情况...", title="包更新检查器", border_style="cyan")
    )

    # 获取过时的包
    outdated_packages = get_outdated_packages()

    # 获取 pyproject.toml 中的依赖
    project_deps = check_pyproject_deps()
    if project_deps:
        console.print(
            f"\n📋 发现 [bold blue]{len(project_deps)}[/bold blue] 个 pyproject.toml 中定义的依赖"
        )
        # 标记项目依赖
        for pkg in outdated_packages:
            if pkg["name"].lower() in project_deps:
                pkg["in_project"] = True

    # 显示统计信息
    format_rich_table_output(outdated_packages)
    display_statistics(outdated_packages, project_deps)


if __name__ == "__main__":
    check_site_packages_update()
