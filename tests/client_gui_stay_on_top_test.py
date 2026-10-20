"""start_client_gui 置顶（📌）按钮的行为测试。

覆盖用户报告的回归点：点击「取消置顶」后窗口仍然置顶。

根因有两处（均已定位到行号）：
1. ``window_stay_on_top_toggled()`` 读取的是模块级全局 ``gui`` 而不是 ``self``；
   全局不存在时槽函数在 ``self.show()`` 之前抛 NameError，窗口会被隐藏。
2. ``show_window_centered()`` 恢复置顶状态的分支漏掉了
   「进入时未置顶（was_on_top=False）」的情况，于是把居中用的临时置顶留了下来，
   导致「取消置顶 → 托盘双击呼出」之后窗口又变回置顶。

用法：
    ./runtime/python.exe tests/client_gui_stay_on_top_test.py
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)  # GUI 构造会读取相对 cwd 的 config.toml
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import start_client_gui as gui_module  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def make_gui() -> "gui_module.GUI":
    """构造 GUI 实例，但不启动真实监听脚本。"""
    original_start_script = gui_module.GUI.start_script
    gui_module.GUI.start_script = lambda self: None
    try:
        window = gui_module.GUI()
    finally:
        gui_module.GUI.start_script = original_start_script
    window.show()
    APP.processEvents()
    return window


def set_pin_state(window, on_top: bool) -> None:
    """直接设置窗口置顶状态与记录的用户偏好，绕过按钮槽以隔离根因。"""
    window.setWindowFlag(Qt.WindowStaysOnTopHint, on_top)
    window.original_stays_on_top = on_top
    window.show()
    APP.processEvents()


def is_on_top(window) -> bool:
    return bool(window.windowFlags() & Qt.WindowStaysOnTopHint)


def close(window) -> None:
    window.hide()
    window.deleteLater()
    APP.processEvents()


# ------------------------------------------------------------ 按钮槽本身


@test
def test_click_unpins_window() -> None:
    """点击「取消置顶」必须真的取消置顶，且窗口不能消失。"""
    window = make_gui()
    try:
        assert is_on_top(window), "前置：窗口初始应处于置顶状态"
        window.stay_on_top_button.click()
        APP.processEvents()
        assert not is_on_top(window), "点击「取消置顶」后窗口仍然置顶"
        assert not window.original_stays_on_top, "未记录取消置顶的偏好"
        assert window.isVisible(), "点击「取消置顶」后窗口消失了（槽函数中途抛异常）"
    finally:
        close(window)


@test
def test_click_twice_restores_pinned() -> None:
    """再次点击应恢复置顶。"""
    window = make_gui()
    try:
        window.stay_on_top_button.click()
        APP.processEvents()
        assert not is_on_top(window)
        window.stay_on_top_button.click()
        APP.processEvents()
        assert is_on_top(window), "第二次点击未恢复置顶"
        assert window.original_stays_on_top
        assert window.isVisible()
    finally:
        close(window)


# ------------------------------------------------------------ 呼出窗口时的状态保持


@test
def test_show_window_centered_keeps_unpinned_state() -> None:
    """取消置顶后呼出窗口（show_window_centered）不得重新置顶。"""
    window = make_gui()
    try:
        set_pin_state(window, on_top=False)
        window.show_window_centered()
        APP.processEvents()
        assert not is_on_top(window), "show_window_centered 把未置顶窗口重新置顶了"
    finally:
        close(window)


@test
def test_show_window_centered_keeps_pinned_state() -> None:
    """保持置顶时，呼出窗口后仍应置顶。"""
    window = make_gui()
    try:
        set_pin_state(window, on_top=True)
        window.show_window_centered()
        APP.processEvents()
        assert is_on_top(window), "show_window_centered 把置顶窗口取消了置顶"
    finally:
        close(window)


@test
def test_unpin_then_show_centered_stays_unpinned() -> None:
    """用户真实操作序列：点「取消置顶」→ 托盘呼出窗口，仍应保持未置顶。"""
    window = make_gui()
    try:
        window.stay_on_top_button.click()
        APP.processEvents()
        assert not is_on_top(window), "点击「取消置顶」无效"
        window.show_window_centered()
        APP.processEvents()
        assert not is_on_top(window), "呼出窗口后又被置顶（用户报告的复现路径）"
    finally:
        close(window)


def main() -> int:
    failed = []
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed.append(fn.__name__)
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
