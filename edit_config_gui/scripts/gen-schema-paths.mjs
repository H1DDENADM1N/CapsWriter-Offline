/**
 * 生成 `src-tauri/tests/schema_paths.json`：schema 里「可编辑的固定叶子键」
 * 的 segments 列表。
 *
 * 为什么要这么绕一圈：前端 schema 是 TS，Rust 侧的覆盖测试读不了 TS，只能读
 * JSON；而「schema 与 config.toml 的 162 个叶子键一一对应」这条断言需要两边
 * 都能独立核对。于是分工如下 ——
 *
 *   schema（TS）  --本脚本-->  schema_paths.json  --coverage.rs-->  config.toml
 *   schema（TS）  --coverage.test.ts---------------------------->  schema_paths.json
 *
 * 前端测试保证「schema 与 JSON 同步」，Rust 测试保证「JSON 与真实配置文件同步」，
 * 两条链合起来闭合。任何一边加/删/改键而忘了另一边，都会在这里或那里变红。
 *
 * 期望输出：editable 151 / derived 9 / paths 151
 *   （162 个 TOML 叶子 − 2 条动态表条目 = 160；160 − 9 个派生只读键 = 151）
 */
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  allFields,
  derivedFields,
  editableFields,
} from '../src/lib/schema/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '..', 'src-tauri', 'tests', 'schema_paths.json');

const editable = editableFields();
const readonly = allFields().filter((f) => f.widget === 'readonly');
const derived = derivedFields();

// 只读视图必须与 derivedFields() 完全一致。若有人新加一个 widget:'readonly'
// 却忘了写 derivedFrom，这里会立刻报出来，而不是等到运行时「跳转按钮消失」。
const key = (s) => s.join('\u0000');
const a = readonly.map((f) => key(f.segments)).sort();
const b = derived.map((f) => key(f.segments)).sort();
if (a.length !== b.length || a.some((x, i) => x !== b[i])) {
  console.error(
    'readonly 视图与 derivedFields() 不一致：',
    '\n  readonly =',
    a,
    '\n  derived  =',
    b,
  );
  process.exit(1);
}

const paths = editable.map((f) => f.segments).sort((x, y) =>
  key(x) < key(y) ? -1 : key(x) > key(y) ? 1 : 0,
);

writeFileSync(out, JSON.stringify(paths, null, 2) + '\n', 'utf8');
console.log(
  `editable: ${editable.length}  derived: ${derived.length}  paths: ${paths.length}`,
);
