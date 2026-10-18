import { describe, expect, it } from 'vitest';

import {
  HAN,
  fullPinyinCandidates,
  hanRuns,
  initialCandidates,
  readingsOf,
} from './pinyin.ts';
import { allFields } from './schema/index.ts';
import map from './pinyin-map.json';

const TABLE = map as Record<string, string[]>;

describe('pinyin-map 与 schema 的同步（验收第 21 条）', () => {
  it('pinyin_map_covers_all_titles', () => {
    // 所有会参与搜索的中文文案（title + note + segments 里的中文段）的每个汉字
    // 都必须在表里。漏一个字的后果是「用户搜那个字静默 0 结果」，而这类回归
    // 只有在新增字段后才会出现——所以必须由测试兜住，不能靠人记得重跑脚本。
    const missing = new Set<string>();

    for (const f of allFields()) {
      for (const text of [f.title, f.note ?? '', ...f.segments]) {
        for (const ch of text) {
          if (HAN.test(ch) && !(ch in TABLE)) missing.add(ch);
        }
      }
    }

    expect(
      [...missing].sort(),
      'pinyin-map.json 缺字，请在 edit_config_gui/ 下重跑 node scripts/gen-pinyin-map.mjs',
    ).toEqual([]);
  });

  it('多音字保留全部读音', () => {
    expect(TABLE['重']).toEqual(expect.arrayContaining(['zhong', 'chong']));
    expect(TABLE['率']).toEqual(expect.arrayContaining(['shuai']));
  });

  it('ü 同时提供 lü / lv / lu 三种输入习惯', () => {
    expect(TABLE['率']).toEqual(expect.arrayContaining(['lü', 'lv', 'lu']));
  });
});

describe('拼音查表', () => {
  it('表外字返回空数组', () => {
    expect(readingsOf('a')).toEqual([]);
    expect(readingsOf('，')).toEqual([]);
  });

  it('全拼候选包含两种读音', () => {
    const c = fullPinyinCandidates('重叠');
    expect(c).toContain('chongdie');
    expect(c).toContain('zhongdie');
  });

  it('首字母候选去重', () => {
    expect(initialCandidates('端口')).toEqual(['dk']);
  });

  it('含表外字时不做拼音匹配', () => {
    expect(fullPinyinCandidates('ADB 设备')).toEqual([]);
    expect(initialCandidates('a端')).toEqual([]);
  });

  it('hanRuns 按非汉字段切分', () => {
    expect(hanRuns('ADB 设备地址')).toEqual(['设备地址']);
    expect(hanRuns('中文')).toEqual(['中文']);
    expect(hanRuns('abc')).toEqual([]);
  });
});
