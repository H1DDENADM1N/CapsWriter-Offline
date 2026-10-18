/**
 * 拼音查表：只负责「这个字的读音是什么」，不做任何打分或匹配。
 *
 * 表是构建期产物（`scripts/gen-pinyin-map.mjs` → `pinyin-map.json`），
 * 运行期零依赖：`pinyin-pro` 只在生成脚本里用到，不进 bundle。
 */

import map from './pinyin-map.json';

const TABLE = map as Record<string, string[]>;

/** 汉字区段（含扩展 A 与兼容区）；全角标点、拉丁字母都不算 */
export const HAN = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]/;

/**
 * 候选串上限。
 *
 * 一个 10 字标题若字字都是多音字，全拼组合是 2^10；不封顶会在一次按键里生成
 * 上千个串。封顶后仍然覆盖绝大多数真实标题（多音字通常只有一两处）。
 */
const MAX_CANDIDATES = 64;

/** 单字的全部读音（含 ü 的 v/u 变体）；表里没有的字返回空数组 */
export function readingsOf(ch: string): string[] {
  return TABLE[ch] ?? [];
}

/** 全拼候选串：逐字取音做笛卡尔积 */
export function fullPinyinCandidates(word: string): string[] {
  if (word === '') return [];

  let out = [''];
  for (const ch of word) {
    const rs = readingsOf(ch);
    if (rs.length === 0) return [];
    const next: string[] = [];
    for (const prefix of out) for (const r of rs) next.push(prefix + r);
    out = next.slice(0, MAX_CANDIDATES);
  }
  return out;
}

/** 首字母候选串：每个字取任意读音的首字母 */
export function initialCandidates(word: string): string[] {
  if (word === '') return [];

  let out = [''];
  for (const ch of word) {
    const rs = readingsOf(ch);
    if (rs.length === 0) return [];
    const heads = [...new Set(rs.map((r) => r[0] ?? ''))].filter((h) => h !== '');
    if (heads.length === 0) return [];
    const next: string[] = [];
    for (const prefix of out) for (const h of heads) next.push(prefix + h);
    out = next.slice(0, MAX_CANDIDATES);
  }
  return out;
}

/**
 * 把一段文案切成「连续汉字段」。
 *
 * 必须切段而不能整串取音：`ADB 设备地址` 里的空格与拉丁字母在字表里没有读音，
 * 整串取音会直接返回空数组，于是「shebei」这种最自然的输入反而搜不到。
 */
export function hanRuns(text: string): string[] {
  const runs: string[] = [];
  let cur = '';

  for (const ch of text) {
    if (HAN.test(ch)) {
      cur += ch;
    } else if (cur !== '') {
      runs.push(cur);
      cur = '';
    }
  }
  if (cur !== '') runs.push(cur);

  return runs;
}
