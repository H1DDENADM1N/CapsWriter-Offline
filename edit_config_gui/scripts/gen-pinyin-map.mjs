/**
 * 生成拼音索引表（`src/lib/pinyin-map.json`）。
 *
 * 字表的来源被刻意限制在两处：`config.toml` 全文 + `src/lib/schema/*.ts` 里会
 * 参与搜索的中文文案（title / note / segments）。不扫全仓——仓库里还有文档、
 * 计划、Python 注释，把它们算进来会让字表膨胀一倍却一个字也用不上，而
 * 「表里有、UI 里没有」的字永远不会被搜到，纯属噪音。
 *
 * 多音字必须保留全部读音（`重` 要同时有 zhong / chong），否则用户按自己习惯
 * 打的那一种拼法会静默搜不到。`ü` 额外展开 `v` 与 `u` 两种输入习惯。
 *
 * 用法：`node scripts/gen-pinyin-map.mjs`（在 `edit_config_gui/` 下）
 * 新增字段后必须重跑；忘了重跑会被 `src/lib/pinyin.test.ts` 的
 * `pinyin_map_covers_all_titles` 当场拦下。
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { pinyin } from 'pinyin-pro';

const HAN = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]/;

const here = import.meta.dirname;
const appDir = resolve(here, '..');
const repoRoot = resolve(appDir, '..');

const chars = new Set();

function collect(text) {
  for (const ch of text) {
    if (HAN.test(ch)) chars.add(ch);
  }
}

collect(readFileSync(resolve(repoRoot, 'config.toml'), 'utf8'));

const { allFields } = await import('../src/lib/schema/index.ts');
for (const f of allFields()) {
  collect(f.title);
  collect(f.note ?? '');
  for (const s of f.segments) collect(s);
}

const table = {};
for (const ch of [...chars].sort()) {
  const readings = new Set();
  for (const r of pinyin(ch, { type: 'array', multiple: true, toneType: 'none' })) {
    readings.add(r);
    if (r.includes('ü')) {
      readings.add(r.replaceAll('ü', 'v'));
      readings.add(r.replaceAll('ü', 'u'));
    }
  }
  table[ch] = [...readings].sort();
}

const out = resolve(appDir, 'src/lib/pinyin-map.json');
writeFileSync(out, `${JSON.stringify(table)}\n`, 'utf8');
console.log(`chars: ${Object.keys(table).length} -> ${out}`);
