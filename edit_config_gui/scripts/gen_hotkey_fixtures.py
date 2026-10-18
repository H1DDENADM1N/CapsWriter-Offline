"""生成 hotkey 对拍集与真值（真值必须现跑 Python keyboard.parse_hotkey，绝不手写）。

产物：
  src-tauri/tests/fixtures/hotkey_cases.txt      —— 每行一个快捷键字符串
  src-tauri/tests/fixtures/hotkey_expected.txt   —— 每行 ok 或 err

用法：.venv\\Scripts\\python.exe edit_config_gui\\scripts\\gen_hotkey_fixtures.py

脚本会自校验用例集规模：841 行 / ok 432 / err 409。数字不对就直接失败，
逼迫调整用例集本身，而不是放宽断言。
"""

import json
import pathlib
import sys
import tomllib

import keyboard
from keyboard import _canonical_names as cn
from keyboard import _winkeyboard as wk

# from_name 只由 _setup_name_tables() 填充，不先跑会是空字典
wk._setup_name_tables()

ROOT = pathlib.Path(__file__).resolve().parents[2]  # 仓库根
OUT = pathlib.Path(__file__).resolve().parents[1] / "src-tauri" / "tests" / "fixtures"

EXPECTED_TOTAL = 841
EXPECTED_OK = 432


def expected(hk: str) -> str:
    try:
        keyboard.parse_hotkey(hk)
        return "ok"
    except Exception:
        return "err"


class Cases:
    """按插入顺序去重的用例集（同一条字符串只出现一次）。"""

    def __init__(self):
        self.seen = set()
        self.items = []

    def add(self, hk: str):
        if hk in self.seen:
            return
        self.seen.add(hk)
        self.items.append(hk)

    def __len__(self):
        return len(self.items)


cases = Cases()

# ---------------------------------------------------------------- A. 显式正/反例
# 覆盖配置里最常见的形态、别名、单字符、非法键、不 trim 等。
for hk in [
    "caps lock",
    "ctrl + alt + f5",
    "Ctrl + Alt + F5",
    "left shift",
    "ctrl + alt + [",
    "f13",
    "f24",
    "space",
    "enter",
    "shift",
    "+",
    "_",
    "esc",
    "escape",
    "ctrl+alt+f5",
    "alt+a, alt+b",
    "volume up",
    "left windows",
    "alt+f4",
    "f999",
    "f25",
    "",
    "ctrl + ",
    "mouse left",
    "  ctrl  +  alt  +  f5  ",
    "ctrl + shift + ,",
    "鼠标",
]:
    cases.add(hk)

# ------------------------------------------------- B. config.toml 实际出现的快捷键值
# 用 tomllib 真解析，而不是正则扫文本：正则会把注释掉的示例行也抓进来
# （比如 `# "<进程名>" = { hotkey = "<对应程序设置的全局快捷键>" }`），
# 也会漏掉 `prompt_*_shortcut` 这种带下划线前缀的键（`\bshortcut\b` 匹配不上）。
# 递归遍历保留文件顺序，同时覆盖 `*_shortcut` 与内联表里的 `hotkey` 两种形态。
def collect_hotkeys(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and (
                key.endswith("_shortcut") or key.endswith("hotkey") or key == "hotkey"
            ):
                out.append(value)
            else:
                collect_hotkeys(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_hotkeys(value, out)


config_values = []
collect_hotkeys(tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8")), config_values)
if not config_values:
    sys.exit("config.toml 里没抓到任何快捷键值，遍历逻辑或路径不对")
for hk in config_values:
    cases.add(hk)

# ----------------------------------------------------- C. 修饰符 × 主键 × 空格写法
# 修饰符含：普通四键、带左右前缀的键、大小写变体（规范化要能把大小写抹平）。
MODIFIERS = ["ctrl", "alt", "shift", "windows", "left ctrl", "right shift", "Ctrl", "ALT"]
# 主键：字母/数字、F 键边界（f1/f12/f13/f24/f0/f25/f999）、命名键、符号、单字符、
# 非 ASCII、空串。空串用来触发 normalize_name 的非空校验。
MAIN_KEYS = [
    "a", "f1", "f12", "f13", "f24", "space", "enter", "[", "]", "esc", "escape",
    "tab", "backspace", "delete", "del", "home", "end", "page up", "volume up",
    "媒体", "mouse left", "f0", "f25", "f999", "", "+", "-", "_", "1", "5",
]
STYLES = ["{m} + {k}", "{m}+{k}", "{m}  +  {k}"]
for m in MODIFIERS:
    for k in MAIN_KEYS:
        for style in STYLES:
            cases.add(style.format(m=m, k=k))

# ------------------------------------------------------------- D. 逗号分段的组合
# `,` 后只允许吃一个空白；多一个空格、缺键、坏键都要判非法。
HEADS = ["alt+a", "ctrl+alt+f5", "caps lock", "bad key"]
TAILS = [
    ", alt+b", ",alt+b", " ,  alt+b",
    ", ctrl+shift+z", ",ctrl+shift+z", " ,  ctrl+shift+z",
    ", nonsense", ",nonsense", " ,  nonsense",
    ", ", ",", " ,  ",
]
for head in HEADS:
    for tail in TAILS:
        cases.add(head + tail)

# ---------------------------------------------- E. 单字符 / 数字串 / 大小写 / 空白
for ch in list("abcxyz") + list("0189") + list("-=[];,./`"):
    cases.add(ch)
for hk in [
    "255", "4294967295", "-1", "1.5", "3 ", " 3",
    "CAPS LOCK", "Caps Lock", "caps  lock", "caps\tlock",
    " ctrl + a", "ctrl + a ", "ctrl +", "+a", "a+", "ctrl++a",
]:
    cases.add(hk)

# ------------------------------------------------------------------------ 写出
oks = [expected(hk) for hk in cases.items]
ok_n = oks.count("ok")
err_n = len(oks) - ok_n

print(f"total: {len(cases)}  ok: {ok_n}  err: {err_n}")

# 先落盘再校验规模：规模不对时文件仍可用于 diff 排查，但脚本以非零码退出。
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "hotkey_cases.txt").write_text("\n".join(cases.items) + "\n", encoding="utf-8")
(OUT / "hotkey_expected.txt").write_text("\n".join(oks) + "\n", encoding="utf-8")
print(f"wrote {OUT / 'hotkey_cases.txt'}")
print(f"wrote {OUT / 'hotkey_expected.txt'}")

if (len(cases), ok_n, err_n) != (EXPECTED_TOTAL, EXPECTED_OK, EXPECTED_TOTAL - EXPECTED_OK):
    sys.exit(
        f"用例集规模不符：期望 {EXPECTED_TOTAL}/{EXPECTED_OK}/{EXPECTED_TOTAL - EXPECTED_OK}，"
        f"实际 {len(cases)}/{ok_n}/{err_n}"
    )


# ============================================================ 别名穷举对拍集
# 手工挑选的 841 例覆盖不到「canonical_names 里的某个别名到底认不认」，
# 而这正是移植 normalize_name 最容易错的地方。所以再加一份**全量**对拍：
# 1171 个 canonical 键 + 205 个 from_name 名字 + 每个名字的 left/right/大写变体。
# 真值同样现跑 Python，一个都不手写。
#
# 注意：必须用 JSON 而不是行式文本 —— `canonical_names` 里有两个键本身是
# `'\n'` 和 `'\r'`，写进行式文件会直接把文件切碎、后续逐行错位。
alias_cases = Cases()
for name in sorted(wk.from_name.keys()):
    alias_cases.add(name)
    alias_cases.add("left " + name)
    alias_cases.add("right " + name)
    alias_cases.add(name.upper())
for name in sorted(cn.canonical_names.keys()):
    alias_cases.add(name)

alias_rows = [[hk, expected(hk)] for hk in alias_cases.items]
alias_ok_n = sum(1 for _, r in alias_rows if r == "ok")
print(f"alias total: {len(alias_rows)}  ok: {alias_ok_n}  err: {len(alias_rows) - alias_ok_n}")

(OUT / "hotkey_alias.json").write_text(
    json.dumps(alias_rows, ensure_ascii=False, indent=0), encoding="utf-8"
)
print(f"wrote {OUT / 'hotkey_alias.json'}")


# =================================================== 空白字符语义对拍集（JSON）
# `re` 的 `\s` 与 Rust `char::is_whitespace()` 不完全等价：Python 的 `str.isspace()`
# 把 U+001C..U+001F 也算空白，Unicode White_Space 属性不认。这直接影响
# `re.split(r'\s?\+\s?')` 能在 `+` 前吃掉哪个字符，所以必须单独对拍。
# 这里还顺带覆盖 NBSP(U+00A0)、全角空格(U+3000)、各类 Unicode 空白、制表符。
ws_rows = []
for ws in [
    "\u0009", "\u000a", "\u000b", "\u000c", "\u000d",
    "\u001c", "\u001d", "\u001e", "\u001f",
    "\u0020", "\u0085", "\u00a0", "\u1680", "\u2000", "\u2003",
    "\u2028", "\u2029", "\u202f", "\u205f", "\u3000",
]:
    for tmpl in ["a{ws}+b", "ctrl{ws}+a", "ctrl +{ws}a", "a+{ws}b", "ctrl{ws}alt"]:
        ws_rows.append([tmpl.format(ws=ws), expected(tmpl.format(ws=ws))])
# 多空白叠加：`\s?` 只吃一个，第二个留在段内 → 非法
for hk in ["ctrl  +  a", "ctrl\t\t+\t\ta", "ctrl\u3000\u3000+\u3000\u3000a"]:
    ws_rows.append([hk, expected(hk)])

# 「只吃一个」与「吃光」的关键区别：分隔符后跟 **2 个以上**空白再接合法键。
# 只吃一个 → 段首残留空白 → 段非法；吃光 → 段合法。这两类的真值必然不同。
for hk in [
    "alt+a,  alt+b",           # 逗号后两个空格
    "alt+a,\t\talt+b",         # 逗号后两个制表符
    "alt+a,\u3000\u3000alt+b", # 逗号后两个全角空格
    "ctrl  +  a",              # 加号两侧各两个空格
    "ctrl   +   a",
    "ctrl\u3000+ a",
    "ctrl +  a",
]:
    ws_rows.append([hk, expected(hk)])

ws_ok_n = sum(1 for _, r in ws_rows if r == "ok")
print(f"ws total: {len(ws_rows)}  ok: {ws_ok_n}  err: {len(ws_rows) - ws_ok_n}")
(OUT / "hotkey_whitespace.json").write_text(
    json.dumps(ws_rows, ensure_ascii=False, indent=0), encoding="utf-8"
)
print(f"wrote {OUT / 'hotkey_whitespace.json'}")
