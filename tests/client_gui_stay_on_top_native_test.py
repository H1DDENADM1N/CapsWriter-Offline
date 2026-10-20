"""独立验证脚本：取消置顶（📌）按钮修复 —— 真实 Windows 平台 + 变异检验。

用法：
    # A/B/D：真实 Windows 平台（不设 QT_QPA_PLATFORM=offscreen）
    ./runtime/python.exe tests/client_gui_stay_on_top_native_test.py

    # C：变异检验（内存里 monkeypatch 回修复前行为，运行 Lead 的回归测试）
    ./runtime/python.exe tests/client_gui_stay_on_top_native_test.py --mutation

退出码：0 = 全部通过；1 = 存在反例（native/mutation 各自报告）。
"""

from __future__ import annotations

import os
import re
import sys

MODE = "native"
# 变异维度：both = 两个根因都还原；toggle = 只还原根因(1)；centered = 只还原根因(2)
MUTATE = "both"
for _arg in sys.argv[1:]:
    if _arg == "--mutation":
        MODE = "mutation"
    elif _arg == "--mutation-toggle":
        MODE, MUTATE = "mutation", "toggle"
    elif _arg == "--mutation-centered":
        MODE, MUTATE = "mutation", "centered"
    elif _arg == "--native":
        MODE = "native"

if MODE == "mutation":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
else:
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        print("FATAL: native 模式不得设置 QT_QPA_PLATFORM=offscreen")
        sys.exit(2)

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)  # GUI 构造读取相对 cwd 的 config.toml
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402


# ---------------------------------------------------------------- C: 变异检验


def run_mutation() -> int:
    """把两个方法 monkeypatch 回修复前行为，再跑 Lead 的回归测试。"""
    import importlib.util

    import start_client_gui as gui_module

    spec = importlib.util.spec_from_file_location(
        "cg_stay_on_top_test_mut",
        REPO_ROOT / "tests" / "client_gui_stay_on_top_test.py",
    )
    tm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tm)

    # 修复前的 window_stay_on_top_toggled：通过模块全局 gui 读取状态；
    # 该函数定义在本脚本模块内，global gui 在本模块不存在 -> NameError。
    def old_toggle(self):
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
            self.original_stays_on_top = False
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.original_stays_on_top = True
            global gui  # noqa: F824  —— 与修复前一致
        window_is_on_top = bool(gui.windowFlags() & Qt.WindowStaysOnTopHint)
        if window_is_on_top:
            self.stay_on_top_button.setText(chr(0xE840))
        else:
            self.stay_on_top_button.setText(" ")
        self.show()

    # 修复前的 show_window_centered：恢复分支漏掉
    #   「original_stays_on_top=False 且 was_on_top=False」组合。
    def old_show_centered(self):
        self.showNormal()
        self.activateWindow()
        self.show_client_interface()
        was_on_top = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        if not was_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        window_geometry = self.frameGeometry()
        window_geometry.moveCenter(screen_geometry.center())
        self.move(window_geometry.topLeft())
        if not self.original_stays_on_top and was_on_top:
            self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
            self.show()
        elif self.original_stays_on_top and not was_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()

    if MUTATE in ("both", "toggle"):
        gui_module.GUI.window_stay_on_top_toggled = old_toggle
    if MUTATE in ("both", "centered"):
        gui_module.GUI.show_window_centered = old_show_centered
    print(f"[mutation] platform={QApplication.platformName()} mutate={MUTATE}")
    print("[mutation] 已按维度还原修复前逻辑")

    rc = tm.main()
    print(f"[mutation] 回归测试退出码 = {rc}（期望非 0 = 测试确实能抓到 bug）")
    return 0 if rc != 0 else 1


# ---------------------------------------------------------------- A/B: 原生


def run_native() -> int:
    import time

    import win32con
    import win32gui

    import start_client_gui as gui_module

    WS_EX_TOPMOST = win32con.WS_EX_TOPMOST
    APP = QApplication.instance() or QApplication([])

    print(f"[native] platformName={APP.platformName()}")
    print(f"[native] WS_EX_TOPMOST=0x{WS_EX_TOPMOST:x}")
    print(f"[native] has setWindowFlag(Qt.WindowStaysOnTopHint,bool): "
          f"{hasattr(gui_module.GUI, 'setWindowFlag')}")

    failures: list[str] = []
    checks = {"n": 0}

    def check(label, cond, detail=""):
        checks["n"] += 1
        status = "PASS" if cond else "FAIL"
        if not cond:
            failures.append(label)
        print(f"  [{status}] {label}  {detail}")

    def make_gui():
        original = gui_module.GUI.start_script
        gui_module.GUI.start_script = lambda self: None
        try:
            w = gui_module.GUI()
        finally:
            gui_module.GUI.start_script = original
        w.show()
        APP.processEvents()
        time.sleep(0.25)
        APP.processEvents()
        return w

    def close(w):
        w.hide()
        w.deleteLater()
        APP.processEvents()

    def qt_top(w):
        return bool(w.windowFlags() & Qt.WindowStaysOnTopHint)

    def native_top(w):
        hwnd = int(w.winId())
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        return bool(ex & WS_EX_TOPMOST), hwnd, ex

    def state(w):
        ntop, hwnd, ex = native_top(w)
        return (
            f"qt_topmost={qt_top(w)} native_topmost={ntop} "
            f"hwnd=0x{hwnd:x} exstyle=0x{ex:x} visible={w.isVisible()}"
            f" original={getattr(w, 'original_stays_on_top', None)}"
        )

    def center_hwnd(w):
        """把窗口移离屏幕中心，确保 is_centered() 为 False。"""
        w.move(1, 1)
        APP.processEvents()
        time.sleep(0.1)
        APP.processEvents()

    # ---- A1 初始置顶
    print("\n[A1] 初始状态：应置顶（Qt + 原生）")
    w = make_gui()
    try:
        ntop, _, _ = native_top(w)
        print(f"     {state(w)}")
        check("A1 Qt 初始置顶", qt_top(w))
        check("A1 原生 WS_EX_TOPMOST 初始置顶", ntop)
    finally:
        close(w)

    # ---- A2 点击取消置顶
    print("\n[A2] 点击「取消置顶」后：两者皆非 TOPMOST 且 isVisible=True")
    w = make_gui()
    try:
        w.stay_on_top_button.click()
        APP.processEvents()
        time.sleep(0.25)
        APP.processEvents()
        ntop, _, _ = native_top(w)
        print(f"     {state(w)}")
        check("A2 Qt 已取消置顶", not qt_top(w))
        check("A2 原生已取消置顶", not ntop)
        check("A2 窗口仍可见", w.isVisible())
        check("A2 original_stays_on_top=False", not w.original_stays_on_top)
    finally:
        close(w)

    # ---- A3 再次点击恢复置顶
    print("\n[A3] 再次点击：两者恢复 TOPMOST")
    w = make_gui()
    try:
        w.stay_on_top_button.click()
        APP.processEvents()
        time.sleep(0.2)
        APP.processEvents()
        check("A3 第一次点击后非置顶", not qt_top(w) and not native_top(w)[0])
        w.stay_on_top_button.click()
        APP.processEvents()
        time.sleep(0.25)
        APP.processEvents()
        ntop, _, _ = native_top(w)
        print(f"     {state(w)}")
        check("A3 Qt 恢复置顶", qt_top(w))
        check("A3 原生恢复 TOPMOST", ntop)
        check("A3 original_stays_on_top=True", w.original_stays_on_top)
    finally:
        close(w)

    # ---- A4 取消置顶后 show_window_centered 保持非置顶
    print("\n[A4] 取消置顶 -> show_window_centered()：保持非 TOPMOST")
    w = make_gui()
    try:
        w.stay_on_top_button.click()
        APP.processEvents()
        time.sleep(0.2)
        APP.processEvents()
        center_hwnd(w)
        print(f"     before: {state(w)}")
        w.show_window_centered()
        APP.processEvents()
        time.sleep(0.25)
        APP.processEvents()
        ntop, _, _ = native_top(w)
        print(f"     after : {state(w)}")
        check("A4 Qt 仍非置顶", not qt_top(w))
        check("A4 原生仍非 TOPMOST", not ntop)
    finally:
        close(w)

    # ---- A5 置顶状态下 show_window_centered 保持置顶
    print("\n[A5] 置顶状态下 show_window_centered()：保持 TOPMOST")
    w = make_gui()
    try:
        center_hwnd(w)
        print(f"     before: {state(w)}")
        w.show_window_centered()
        APP.processEvents()
        time.sleep(0.25)
        APP.processEvents()
        ntop, _, _ = native_top(w)
        print(f"     after : {state(w)}")
        check("A5 Qt 仍置顶", qt_top(w))
        check("A5 原生仍 TOPMOST", ntop)
    finally:
        close(w)

    # ---- B 托盘真实路径
    print("\n[B] 托盘双击（可见但未居中，已取消置顶）：不得重新置顶")
    w = make_gui()
    try:
        w.stay_on_top_button.click()
        APP.processEvents()
        time.sleep(0.2)
        APP.processEvents()
        center_hwnd(w)
        print(f"     before: {state(w)} is_centered={w.is_centered()}")
        check("B 前置：窗口可见", w.isVisible())
        check("B 前置：未居中", not w.is_centered())
        check("B 前置：非置顶", not qt_top(w) and not native_top(w)[0])
        w.on_tray_icon_activated(QSystemTrayIcon.DoubleClick)
        APP.processEvents()
        time.sleep(0.3)
        APP.processEvents()
        ntop, _, _ = native_top(w)
        print(f"     after : {state(w)} isVisible={w.isVisible()}")
        check("B 托盘双击后 Qt 仍非置顶", not qt_top(w))
        check("B 托盘双击后原生仍非 TOPMOST", not ntop)
    finally:
        close(w)

    # ---- B2 托盘真实路径（隐藏后呼出，最常见的用户路径）
    print("\n[B2] 托盘双击（窗口已隐藏，已取消置顶）：呼出后不得重新置顶")
    w = make_gui()
    try:
        w.stay_on_top_button.click()
        APP.processEvents()
        time.sleep(0.2)
        APP.processEvents()
        w.hide()
        APP.processEvents()
        time.sleep(0.1)
        APP.processEvents()
        print(f"     before: {state(w)}")
        check("B2 前置：窗口已隐藏", not w.isVisible())
        check("B2 前置：非置顶", not qt_top(w) and not native_top(w)[0])
        w.on_tray_icon_activated(QSystemTrayIcon.DoubleClick)
        APP.processEvents()
        time.sleep(0.3)
        APP.processEvents()
        ntop, _, _ = native_top(w)
        print(f"     after : {state(w)} isVisible={w.isVisible()}")
        check("B2 呼出后 Qt 仍非置顶", not qt_top(w))
        check("B2 呼出后原生仍非 TOPMOST", not ntop)
    finally:
        close(w)

    # ---- D 静态源码扫描
    print("\n[D] 静态确认：window_stay_on_top_toggled 内不再引用模块全局 gui")
    src = (REPO_ROOT / "start_client_gui.py").read_text(encoding="utf-8")
    start = src.index("def window_stay_on_top_toggled")
    end = src.index("def show_time_label_button_toggled")
    body = src[start:end]
    print("     方法体行数:", body.count("\n"))
    for line in body.strip().splitlines()[1:]:
        print("     | " + line)
    # 注意：区域按方法名截取，可能扫到相邻方法，`win32gui.` 不算裸 gui 引用
    bare_gui = re.search(r"(?<![\w.])gui\.", body)
    check("D 方法体内无 `global gui`", "global gui" not in body)
    check(
        "D 方法体内无裸 gui 引用",
        bare_gui is None,
        f"命中: {bare_gui.group(0) if bare_gui else ''}",
    )
    check("D 使用 self.setWindowFlag", "self.setWindowFlag(" in body)
    check("D 调用了 Z-order 重排", "self.apply_native_z_order()" in body)

    print(f"\n[native] 共 {checks['n']} 项检查，{len(failures)} 项失败")
    if failures:
        print("[native] 失败项: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    if MODE == "mutation":
        sys.exit(run_mutation())
    sys.exit(run_native())
