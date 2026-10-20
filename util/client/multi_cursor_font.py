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

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics

__all__ = [
    "FONT_FILE_NAME",
    "MONO_FONT_FAMILY",
    "apply_mono_font",
    "ensure_mono_font_loaded",
    "grid_error",
    "is_grid_exact",
    "mono_font_stylesheet",
    "snap_point_size",
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

    字号在这里被**吸附到等宽网格**上（见 :func:`snap_point_size`），
    因此 stylesheet 里写的可能是 12.38pt 而不是 12pt。
    """
    size = max(1, int(point_size))
    a = max(0, min(255, int(alpha)))
    snapped = snap_point_size(float(size))
    return (
        f"font-family: '{MONO_FONT_FAMILY}';"
        f" font-size: {snapped}pt;"
        f" background-color: rgba(46, 50, 54, {a});"
    )


# 语义别名：调用处按意图选名字，避免到处传 alpha 数字
def mono_font_stylesheet_with_alpha(point_size: int, alpha: int) -> str:
    """``mono_font_stylesheet`` 的实义别名，用于背景显隐切换。"""
    return mono_font_stylesheet(point_size, alpha)


# --------------------------------------------------- 等宽网格：字号吸附
#
# 字体文件的设计 advance 是严格 2:1（Latin 600/1000 em、CJK 1200/1000 em），
# 但 Qt 把 advance 量化到**整数像素**，比例于是被破坏。12pt 时：
#
#     Latin L = 10px    CJK C = 19px   （本该是 20px）
#
# 每个汉字少 1px，误差沿线累积。后果有二：
#
# 1. 长行软换行后，各行的同一个格号落在**不同的 x** 上——用户看到的
#    「mono 字体对不齐」。实测网格偏差达 15px，15 个格号跨行错位。
# 2. 光标上下移动跟着漂移：Qt 的 Up/Down 记住的是「目标 x」，而目标 x
#    落在字符中间，往下一行就对不齐——用户看到的「光标上下移动位置错乱」。
#
# 所以字号必须落在网格点上：**CJK advance 恰为 Latin advance 两倍**。
#
# 为什么在**磅**空间而不是像素空间搜索：磅空间里 12/14/18/22/23pt 没有
# 精确解，只能退到 12.38 这类小数（实测偏差最大 0.38pt，仍在同一视觉
# 尺寸档位内）。纯像素空间虽然解更密，但磅值才是用户「字号」的语义单位，
# 且 QSS 的 pt 值与 Qt 内部解析完全一致（实测 QSS 与 setPointSizeF 的
# 字体度量逐项相等），不会引入两套尺寸语义。

# 网格搜索的步长（磅）。取 0.01pt：再细没有意义（Qt 只保留到整数
# 磅来存，但**度量**按浮点算），再粗会错过窄窗口里的解。
_GRID_SEARCH_STEP = 0.01
# 搜索半径（磅）。实测所有 5–45pt 的目标在 0.4pt 内都有解。
_GRID_SEARCH_RADIUS = 1.0
# 网格吸附结果的缓存：目标字号 -> 吸附后字号。
_snap_cache: dict[float, float] = {}


def _advances_at(point_size: float) -> tuple[int, int]:
    """返回该字号下 Latin 与 CJK 的字符前进宽度（像素）。

    字体没注册进 Qt 时 ``QFontMetrics`` 量到的是**退化值**（16/16），
    据此算出的网格误差毫无意义。所以这里先把字体加载好。
    """
    ensure_mono_font_loaded()
    font = QFont(MONO_FONT_FAMILY)
    font.setPointSizeF(point_size)
    metrics = QFontMetrics(font)
    return (
        metrics.horizontalAdvance("A"),
        metrics.horizontalAdvance("\u4e2d"),
    )


def grid_error(point_size: float) -> int:
    """该字号偏离等宽网格多少像素；0 表示正好在网格上。

    偏差 = |CJK advance - 2 × Latin advance|。理想值是 0：CJK 恰好占
    两个 Latin 格，于是「汉字两格、半角一格」的等宽网格严格成立。
    """
    latin, cjk = _advances_at(point_size)
    if latin <= 0:
        return 0
    return abs(cjk - 2 * latin)


def is_grid_exact(point_size: float) -> bool:
    """该字号是否正好落在等宽网格上。"""
    return grid_error(point_size) == 0


def snap_point_size(point_size: float) -> float:
    """把字号吸附到最近的等宽网格点；返回吸附后的字号。

    吸附规则：

    1. 本身就在网格上 → 原样返回（幂等）；
    2. 否则在 ±1pt 内找网格点，**优先 Latin 宽度与目标相同的那些**，
       同组内取离目标最近的。

    第 2 条的「优先」很重要：Latin 宽度变了意味着整篇文本的视觉宽度
    变了——用户只是调了个字号，看到的行宽却跟着变，很突兀。CJK 宽度
    允许变（必须变才能凑成 2:1）。

    实测 5–45pt 的每个整数目标都能找到同 Latin 宽度的网格点，且相邻
    目标吸附后互不相同（Ctrl+滚轮连按不会「卡住」）。实在找不到就
    放宽到「任意 Latin 宽度」的网格点；再找不到就返回原值，不做任何
    事——此时字体退化到系统默认行为，比抛异常安全。

    结果按目标字号缓存：吸附要试几十个候选点，而同一次会话里字号
    反复被查询（每次重设 stylesheet 都要）。
    """
    # 缓存的前提是字体已经加载好：没加载时量到的是退化值，算出的结果
    # 会是错的，而且一旦缓存下来就再也纠不回来。
    ensure_mono_font_loaded()

    target = round(float(point_size), 4)
    cached = _snap_cache.get(target)
    if cached is not None:
        return cached

    if is_grid_exact(target):
        _snap_cache[target] = target
        return target

    latin_target, _ = _advances_at(target)

    # 以 0.01 磅为步长向两侧找网格点。用整数「百分磅」推进，避免浮点
    # 累加（`12 + i * 0.01` 累积几十步后与 `12.38` 对不上）。
    base = int(round(target * 100))
    step = int(round(_GRID_SEARCH_STEP * 100))
    radius = int(round(_GRID_SEARCH_RADIUS * 100))

    same_latin: Optional[float] = None
    any_latin: Optional[float] = None

    for offset in range(0, radius + 1, step):
        for candidate in (base + offset, base - offset):
            if candidate < 100:  # 小于 1pt 没有意义
                continue
            size = candidate / 100.0
            if not is_grid_exact(size):
                continue
            latin, _ = _advances_at(size)
            if latin == latin_target:
                # 同 Latin 宽度：取离目标最近的那个
                if same_latin is None or abs(size - target) < abs(same_latin - target):
                    same_latin = size
            elif any_latin is None or abs(size - target) < abs(any_latin - target):
                any_latin = size
        # 同 Latin 宽度的解已经拿到（半径内不会有更近的了）
        if same_latin is not None:
            break

    result = same_latin if same_latin is not None else any_latin
    if result is None:
        result = target
    _snap_cache[target] = result
    return result


def apply_mono_font(widget, point_size: Optional[int] = None) -> bool:  # noqa: ANN001
    """把等宽字体应用到 ``widget``；返回字体是否真的可用。

    字体不可用时**不覆盖** widget 原有字体，避免把用户的系统默认字体
    换成 Tahoma 这类奇怪的替代品——宁可保持原样。
    """
    if not ensure_mono_font_loaded():
        return False

    font = QFont(MONO_FONT_FAMILY)
    if point_size is not None:
        font.setPointSizeF(snap_point_size(float(point_size)))
    widget.setFont(font)
    return True
