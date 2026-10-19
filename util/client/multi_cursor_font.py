"""文本框等宽字体：MapleMono-NF-CN-Regular 的加载与应用。

为什么需要这个模块（而不是一行 ``setFont``）：
Windows 上字体文件可能已经装在用户字体目录里，但 Qt 的字体数据库
不一定把它枚举成可用族名——实测 ::

    "MapleMono-NF-CN-Regular"  ->  Tahoma, exactMatch=False
    "Maple Mono NF CN"         ->  Tahoma, exactMatch=False

两个名字都匹配不到，``setFont`` 会静默退化成系统替代字体，看起来
「配置生效了」但屏幕上是 Tahoma。必须用 ``QFontDatabase.addApplicationFont``
显式把 ttf 注册进当前进程，之后 ``Maple Mono NF CN`` 才真正可用。

族名与文件名不同：文件 ``MapleMono-NF-CN-Regular.ttf`` 的族名是
``Maple Mono NF CN``（带空格、无 Regular 后缀）。以 ttf 内嵌的 family
为准，不要按文件名猜。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QFont, QFontDatabase

__all__ = [
    "FONT_FILE_NAME",
    "MONO_FONT_FAMILY",
    "apply_mono_font",
    "ensure_mono_font_loaded",
    "mono_font_stylesheet",
]

# ttf 里内嵌的族名（不是文件名）。加载后 Qt 就用这个名字找字体。
MONO_FONT_FAMILY = "Maple Mono NF CN"

FONT_FILE_NAME = "MapleMono-NF-CN-Regular.ttf"

# 加载状态三值：None = 还没试过，True = 已加载，False = 加载失败（不再重试）
_loaded: Optional[bool] = None
_font_path: Optional[Path] = None


def _candidate_dirs() -> list[Path]:
    """按优先级返回可能的字体目录。"""
    dirs: list[Path] = []
    # 1. 程序自带字体（便携包把 ttf 放这里就能免安装）
    dirs.append(Path(__file__).resolve().parents[2] / "assets" / "fonts")
    # 2. Windows 系统字体目录
    if sys.platform == "win32":
        windir = Path("C:/Windows/Fonts")
        dirs.append(windir)
        # 3. 用户字体目录（未做系统安装、仅「为当前用户安装」时在这里）
        local = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
        dirs.append(local)
    else:
        dirs.append(Path.home() / ".local" / "share" / "fonts")
        dirs.append(Path("/usr/share/fonts"))
    return dirs


def find_mono_font_file() -> Optional[Path]:
    """在候选目录里找字体文件；找不到返回 None。"""
    for directory in _candidate_dirs():
        candidate = directory / FONT_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def ensure_mono_font_loaded() -> bool:
    """确保字体已注册进当前进程；返回是否可用。

    幂等：成功后不再重复注册（每次 ``addApplicationFont`` 都会让 Qt
    多持有一份 20MB 字体的引用）。失败结果也会缓存，避免每次调用都
    去扫一遍磁盘。
    """
    global _loaded, _font_path
    if _loaded is not None:
        return _loaded

    # 已经能被 Qt 枚举到（系统做过字体安装并被索引）就不用再加载
    if MONO_FONT_FAMILY in QFontDatabase.families():
        _loaded = True
        return True

    path = find_mono_font_file()
    if path is None:
        _loaded = False
        return False

    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        _loaded = False
        return False

    families = QFontDatabase.applicationFontFamilies(font_id)
    if MONO_FONT_FAMILY not in families:
        # ttf 内嵌族名与预期不符时仍算成功，只要至少注册上一个族
        if not families:
            _loaded = False
            return False
    _font_path = path
    _loaded = True
    return True


def mono_font_stylesheet(point_size: int, alpha: int = 255) -> str:
    """生成文本框样式表：等宽字体 + 指定字号 + 深色背景。

    族名同时写进 stylesheet：Ctrl+滚轮缩放会整段重设 stylesheet，
    只靠 ``setFont`` 的话样式表里的 ``font-size`` 会覆盖掉字号而族名
    依赖继承，一旦宿主或主题重设样式就有丢失风险。显式写死最稳。

    ``alpha`` 是背景不透明度（0–255）。显隐时间标签时会在 0 与 255 之间
    切换，此时必须仍然带上 ``font-family``，否则进出窗口一次字体就丢。
    """
    size = max(1, int(point_size))
    a = max(0, min(255, int(alpha)))
    return (
        f"font-family: '{MONO_FONT_FAMILY}';"
        f" font-size: {size}pt;"
        f" background-color: rgba(46, 50, 54, {a});"
    )


# 语义别名：调用处按意图选名字，避免到处传 alpha 数字
def mono_font_stylesheet_with_alpha(point_size: int, alpha: int) -> str:
    """``mono_font_stylesheet`` 的实义别名，用于背景显隐切换。"""
    return mono_font_stylesheet(point_size, alpha)


def apply_mono_font(widget, point_size: Optional[int] = None) -> bool:  # noqa: ANN001
    """把等宽字体应用到 ``widget``；返回字体是否真的可用。

    字体不可用时**不覆盖** widget 原有字体，避免把用户的系统默认字体
    换成 Tahoma 这类奇怪的替代品——宁可保持原样。
    """
    if not ensure_mono_font_loaded():
        return False

    font = QFont(MONO_FONT_FAMILY)
    if point_size is not None:
        font.setPointSize(int(point_size))
    widget.setFont(font)
    return True
