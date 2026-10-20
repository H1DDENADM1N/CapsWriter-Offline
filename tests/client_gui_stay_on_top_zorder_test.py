"""回归测试：取消置顶后窗口必须真正让出窗口层顶端（别的窗口必须能盖住客户端）。

用户复现路径：
  点「取消置顶」→ 窗口的 WS_EX_TOPMOST 已清除，但仍滞留在原先（置顶层）的 Z-order 位置上；
  此时去点别的窗口，别的窗口仍被客户端盖住；必须再点回 start_client_gui、
  再点一次别的窗口，才恢复正常。

实测到的机制（见下方各检查的实际取值）：
  setWindowFlag(Qt.WindowStaysOnTopHint, False) 只清除 WS_EX_TOPMOST 样式位，
  **不改变窗口在 Z-order 中的位置** —— 窗口仍滞留在原先（置顶层）的位置上。
  Win32 激活窗口时只会把被激活的窗口抬到**它所属窗口层**的最顶端，因此之后点击
  别的普通窗口只是把它抬到普通窗口层顶端，仍低于客户端滞留的位置，表现为
  「点别的窗口也盖不住客户端」（实测：真实点击后前台已切换成别的窗口，但参照窗口
  仍位于客户端之下）；必须先点一下客户端、再点别的窗口，才能恢复。
  清除样式位后再调用 SetWindowPos(HWND_NOTOPMOST) 完全没有效果（层级不动）。

修复：apply_native_z_order() 在切换置顶状态后把窗口归位
  （置顶 → SetWindowPos(HWND_TOPMOST)；取消置顶 → 激活自身，把它拉回普通窗口层顶端）。
  这正是用户绕过方式（先点回 start_client_gui）的自动化：样式位切换会让客户端
  失去前台地位（实测 fg_before=0x10e06f8），所以激活自身不是 no-op，稳定生效。

设计选择：
  取消置顶后窗口**仍留在当前窗口位置**（可见、可继续输入），只是不再永远置顶 ——
  此后谁被激活谁就盖在它上面。另一种做法是 SetWindowPos(HWND_BOTTOM) 把它沉到
  所有普通窗口之后，那样取消置顶的瞬间它就会被别的窗口盖住（看起来像「消失」），
  所以没有采用；HWND_TOP 未经证实，HWND_NOTOPMOST 已实测无效。

判定方式：
  参照窗口 = 由本测试另起一个独立 python 进程创建的普通 Qt 窗口（普通窗口层）。
  核心检查：取消置顶后**激活**这个普通参照窗口，它必须位于客户端之上
  （Z1a/Z1；Z1r/Z1r2 用真实鼠标点击复核）。修复前该检查必然失败。
  Z1w/Z5w 额外断言取消置顶/居中后客户端仍在这个普通参照窗口之前
  （即窗口没有「消失」到别的窗口后面 —— 本修复的设计选择）。
  Z8/Z8b 用程序化激活（不移动光标）验证客户端可以被重新抬起。
  --real-click 模式额外做一次真实鼠标点击，验证真实用户操作下同样成立。

用法:
  ./runtime/python.exe tests/client_gui_stay_on_top_zorder_test.py
  ./runtime/python.exe tests/client_gui_stay_on_top_zorder_test.py --real-click
  ./runtime/python.exe tests/client_gui_stay_on_top_zorder_test.py --mutation
      # 把 apply_native_z_order 还原为「什么都不做」（修复前行为），再跑一遍；
      # 退出码 0 = 回归测试确实失败（抓到了 bug），1 = 没抓到（守卫失效）

返回码: 0 = 符合预期（native: 全部通过；mutation: 抓到 bug）；
        1 = 不符合预期；2 = 环境不满足（不得 offscreen）
"""

import os
import subprocess
import sys
import time
from pathlib import Path

REAL_CLICK = "--real-click" in sys.argv
MODE = "mutation" if "--mutation" in sys.argv else "native"

if MODE != "mutation" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    print("FATAL: native 模式不得设置 QT_QPA_PLATFORM=offscreen")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)  # GUI 构造读取相对 cwd 的 config.toml
sys.path.insert(0, str(REPO_ROOT))

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

WS_EX_TOPMOST = 0x00000008
REF_TITLE = "CG-ZORDER-REF-EXTERNAL-PROCESS"
REF_SIZE = (520, 320)

CHILD_CODE = (
    "import sys\n"
    "from PySide6.QtWidgets import QApplication, QWidget\n"
    "a = QApplication(sys.argv)\n"
    "w = QWidget()\n"
    f"w.setWindowTitle({REF_TITLE!r})\n"
    f"w.resize({REF_SIZE[0]}, {REF_SIZE[1]})\n"
    "w.move(900, 400)\n"
    "w.show()\n"
    "a.exec()\n"
)


def run_mutation() -> int:
    """把 apply_native_z_order 还原为「什么都不做」，跑回归测试并期望它失败。"""
    import start_client_gui as gui_module

    gui_module.GUI.apply_native_z_order = lambda self: None
    print("[mutation] apply_native_z_order 已还原为修复前行为（不重排 Z-order）")
    rc = run_native()
    print(f"[mutation] 回归测试退出码 = {rc}（期望非 0 = 测试确实能抓到 bug）")
    return 0 if rc != 0 else 1


def run_native() -> int:
    from PySide6.QtWidgets import QSystemTrayIcon

    import start_client_gui as gui_module

    APP = QApplication.instance() or QApplication([])
    failures: list[str] = []
    checks = {"n": 0}

    def check(label, cond, detail=""):
        checks["n"] += 1
        status = "PASS" if cond else "FAIL"
        if not cond:
            failures.append(label)
        print(f"  [{status}] {label}  {detail}")
        return bool(cond)

    def pump(sec=0.3):
        for _ in range(int(sec / 0.05) + 1):
            APP.processEvents()
            time.sleep(0.05)

    def visible_order():
        """按 Z-order（自顶向下）枚举可见的顶层窗口。"""
        handles: list[int] = []
        win32gui.EnumWindows(
            lambda h, _l: _l.append(h) if win32gui.IsWindowVisible(h) else None,
            handles,
        )
        return handles

    def rank(hwnd):
        order = visible_order()
        return order.index(hwnd) if hwnd in order else -1

    def native_top(hwnd):
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        return bool(ex & WS_EX_TOPMOST), ex

    def click(hwnd):
        """真实鼠标点击窗口中心，返回点击后该窗口是否成为前台窗口。"""
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        old = win32api.GetCursorPos()
        win32api.SetCursorPos(((left + right) // 2, (top + bottom) // 2))
        time.sleep(0.15)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.35)
        win32api.SetCursorPos(old)
        pump(0.25)
        return win32gui.GetForegroundWindow() == hwnd

    def activate(hwnd):
        """程序化激活窗口（不移动光标），返回它是否成为前台窗口。"""
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        pump(0.35)
        return win32gui.GetForegroundWindow() == hwnd

    def make_gui():
        original = gui_module.GUI.start_script
        gui_module.GUI.start_script = lambda self: None
        try:
            w = gui_module.GUI()
        finally:
            gui_module.GUI.start_script = original
        w.move(80, 80)
        w.show()
        pump(0.3)
        return w

    def close(w):
        w.hide()
        w.deleteLater()
        pump(0.15)

    def state(w):
        # 注意：setWindowFlag 可能触发原生窗口重建，hwnd 必须在每次读取时重新取
        hwnd = int(w.winId())
        ntop, ex = native_top(hwnd)
        return (
            f"qt_topmost={bool(w.windowFlags() & Qt.WindowStaysOnTopHint)} "
            f"native_topmost={ntop} hwnd=0x{hwnd:x} exstyle=0x{ex:x} "
            f"visible={w.isVisible()} original={getattr(w, 'original_stays_on_top', None)}"
        )

    def ref_above_client(w, ref):
        """普通参照窗口是否真的位于客户端之上（核心要求）。"""
        r_self, r_ref = rank(int(w.winId())), rank(ref)
        return (
            r_ref != -1 and r_self != -1 and r_ref < r_self,
            f"rank_ref={r_ref} rank_self={r_self}  (rank 越小越靠前)",
        )

    def client_above_ref(w, ref):
        r_self, r_ref = rank(int(w.winId())), rank(ref)
        return (
            r_self != -1 and r_ref != -1 and r_self < r_ref,
            f"rank_self={r_self} rank_ref={r_ref}",
        )

    child = None
    try:
        print(
            f"[zorder] platformName={APP.platformName()} mode={MODE} "
            f"real_click={REAL_CLICK}"
        )
        print("启动跨进程参照窗口 ...")
        child = subprocess.Popen([sys.executable, "-c", CHILD_CODE], cwd=str(REPO_ROOT))
        ref = 0
        for _ in range(60):
            ref = win32gui.FindWindow(None, REF_TITLE)
            if ref and win32gui.IsWindowVisible(ref):
                break
            pump(0.25)
        if not ref:
            print("FATAL: 找不到跨进程参照窗口")
            return 2
        print(f"参照窗口 hwnd=0x{ref:x}（独立进程，普通窗口层）")

        # ---------------- Z1 取消置顶后不得再压在普通窗口之上

        print("\n[Z1] 取消置顶后：客户端必须让出顶端（核心回归）")
        w = make_gui()
        try:
            ntop0, ex_before = native_top(int(w.winId()))
            check("Z0 初始为置顶", ntop0, state(w))
            check("Z0b 前置条件：客户端原本在参照窗口之上", client_above_ref(w, ref)[0],
                  client_above_ref(w, ref)[1])
            w.window_stay_on_top_toggled()
            pump(0.3)
            _, ex_after = native_top(int(w.winId()))
            check(
                "Z2 取消置顶后原生 WS_EX_TOPMOST 已清除",
                not native_top(int(w.winId()))[0],
                state(w),
            )
            check("Z3 取消置顶后窗口仍可见", w.isVisible(), state(w))
            check(
                "Z7 取消置顶只清除 WS_EX_TOPMOST，其它样式位不变",
                (ex_before & ~WS_EX_TOPMOST) == ex_after,
                f"ex_before=0x{ex_before:x} ex_after=0x{ex_after:x}",
            )
            # 设计选择：取消置顶后窗口仍留在当前窗口位置（可见、可继续输入），
            # 只是不再永远置顶 —— 谁被激活谁就盖在它上面。
            ok, detail = client_above_ref(w, ref)
            check(
                "Z1w 取消置顶后客户端仍在这个普通参照窗口之前（没有「消失」到别人后面）",
                ok,
                detail,
            )
            check(
                "Z1a 取消置顶后激活别的普通窗口，它成为前台窗口",
                activate(ref),
                f"foreground=0x{win32gui.GetForegroundWindow():x} ref=0x{ref:x}",
            )
            # 核心判据：修复前客户端滞留在置顶层位置，激活普通窗口也盖不住它。
            ok, detail = ref_above_client(w, ref)
            check("Z1 取消置顶后激活别的普通窗口，它必须在客户端之上（核心）", ok, detail)
            if REAL_CLICK:
                w.window_stay_on_top_toggled()  # 重新置顶
                pump(0.25)
                w.window_stay_on_top_toggled()  # 再次取消置顶：回到被测的原始状态
                pump(0.3)
                check(
                    "Z1r 真实点击别的窗口后它成为前台窗口",
                    click(ref),
                    f"foreground=0x{win32gui.GetForegroundWindow():x} ref=0x{ref:x}",
                )
                ok, detail = ref_above_client(w, ref)
                check("Z1r2 真实点击后参照窗口在客户端之上", ok, detail)
            # Z8 放在真实点击之后：激活客户端本身就会把它拉回普通窗口层顶端，
            # 放在前面会掩盖真实点击的判据。
            hwnd_client = int(w.winId())
            fg_before = win32gui.GetForegroundWindow()
            rank_before = rank(hwnd_client)
            check(
                "Z8 取消置顶后重新激活客户端，它能成为前台窗口",
                activate(hwnd_client),
                f"foreground=0x{win32gui.GetForegroundWindow():x} client=0x{hwnd_client:x} "
                f"fg_before=0x{fg_before:x} rank_before={rank_before}",
            )
            ok, detail = client_above_ref(w, ref)
            check("Z8b 重新激活后客户端在参照窗口之上（窗口可被重新抬起）", ok, detail)
        finally:
            close(w)

        # ---------------- Z4 托盘呼出（hide/show）不得复活置顶

        print("\n[Z4] 取消置顶后 hide/show（托盘呼出路径）：不得复活置顶")
        w = make_gui()
        try:
            w.window_stay_on_top_toggled()
            pump(0.25)
            w.hide()
            pump(0.2)
            w.show()
            pump(0.3)
            check(
                "Z4 hide/show 后原生仍非 TOPMOST",
                not native_top(int(w.winId()))[0],
                state(w),
            )
        finally:
            close(w)

        # ---------------- Z5 show_window_centered 不得把非置顶窗口留在顶端

        print("\n[Z5] show_window_centered（实际置顶但原始不置顶）：必须恢复到不置顶")
        w = make_gui()
        try:
            w.original_stays_on_top = False
            w.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            w.show()
            pump(0.3)
            check("Z0c 前置条件：当前原生确实置顶", native_top(int(w.winId()))[0], state(w))
            w.show_window_centered()
            pump(0.35)
            check(
                "Z5 show_window_centered 后原生非 TOPMOST",
                not native_top(int(w.winId()))[0],
                state(w),
            )
            check("Z5b 居中后窗口仍可见", w.isVisible(), state(w))
            # 设计选择：居中后窗口仍留在普通窗口层顶端（可见），只是不置顶。
            ok, detail = client_above_ref(w, ref)
            check("Z5w 居中后客户端仍在这个普通参照窗口之前（没有「消失」）", ok, detail)
            check(
                "Z5a 居中后激活别的普通窗口，它成为前台窗口",
                activate(ref),
                f"foreground=0x{win32gui.GetForegroundWindow():x} ref=0x{ref:x}",
            )
            ok, detail = ref_above_client(w, ref)
            check("Z5c 居中后激活别的普通窗口，它必须在客户端之上（核心）", ok, detail)
        finally:
            close(w)

        # ---------------- Z6 重新置顶仍然有效

        print("\n[Z6] 再点一次（重新置顶）：客户端必须重新压住普通窗口")
        w = make_gui()
        try:
            w.window_stay_on_top_toggled()  # 取消置顶
            pump(0.25)
            w.window_stay_on_top_toggled()  # 重新置顶
            pump(0.3)
            check(
                "Z6 重新置顶后原生 WS_EX_TOPMOST 恢复",
                native_top(int(w.winId()))[0],
                state(w),
            )
            above, detail = client_above_ref(w, ref)
            check("Z6b 置顶状态下参照窗口在客户端之下", above, detail)
        finally:
            close(w)
    finally:
        if child is not None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except Exception:
                child.kill()
        for icon in APP.findChildren(QSystemTrayIcon):
            icon.hide()
        APP.processEvents()

    print(f"\n[zorder] 共 {checks['n']} 项检查，{len(failures)} 项失败")
    if failures:
        print("[zorder] 失败项: " + ", ".join(failures))
        return 1
    print("[zorder] 全部通过")
    return 0


if __name__ == "__main__":
    if MODE == "mutation":
        sys.exit(run_mutation())
    sys.exit(run_native())
