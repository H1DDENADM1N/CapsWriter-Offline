"""把 Python `keyboard` 包的两张键名表导出成 JSON，供 Rust 端 include_str! 使用。

产物（必须入库，离线可编译）：
  src-tauri/src/hotkey_names.json      —— 能被识别为某个扫描码的名字全集（_winkeyboard.from_name 的键）
  src-tauri/src/canonical_names.json   —— 别名 → 规范名映射（_canonical_names.canonical_names）

用法：.venv\\Scripts\\python.exe edit_config_gui\\scripts\\export_hotkey_tables.py
"""

import json
import pathlib

from keyboard import _canonical_names as cn
from keyboard import _winkeyboard as wk

# from_name 是 defaultdict(list)，只有在 _setup_name_tables() 跑过之后才填满。
wk._setup_name_tables()

out = pathlib.Path(__file__).resolve().parents[1] / "src-tauri" / "src"
(out / "hotkey_names.json").write_text(
    json.dumps(sorted(wk.from_name.keys()), ensure_ascii=False, indent=0), encoding="utf-8"
)
(out / "canonical_names.json").write_text(
    json.dumps(cn.canonical_names, ensure_ascii=False, indent=0), encoding="utf-8"
)
print("from_name:", len(wk.from_name), "canonical:", len(cn.canonical_names))
