/**
 * 命令面板的搜索。
 *
 * 三条设计约束（都来自规格 §9.7）：
 *
 * 1. **索引包含隐藏字段与派生只读键。** 遍历 `allFields()` 全量 161 项，而不是
 *    「当前可见」的字段。用户搜出来就是要改它，搜不到会以为编辑器坏了。
 * 2. **secret 字段的值永不入索引。** 本模块根本不索引任何字段的「值」，
 *    唯一读值时是动态表的行键与列值（用户自己填的进程名，不是密钥）。
 * 3. **稳定排序必须显式写 tie-breaker。** 分数相同时按
 *    pages → sections → fields 的声明顺序排，不依赖 `Array.prototype.sort` 的稳定性。
 */

import { allFields, fieldById, fieldId, pages } from './schema/index.ts';
import type { FieldMeta, JsonValue } from './schema/types.ts';
import { fullPinyinCandidates, hanRuns, initialCandidates } from './pinyin.ts';
import { configStore, isVisible } from './stores/config.svelte.ts';

export interface SearchHit {
  fieldId: string;
  segments: string[];
  title: string;
  /** 页标题（不是 id）：面板里要给人看 */
  page: string;
  score: number;
  matchedBy: 'title' | 'segment' | 'pinyin' | 'initial' | 'note';
  /** `visibleWhen` 不满足 → 'hidden'；派生只读键 → 'readonly' */
  badge?: 'hidden' | 'readonly';
  /** 仅 `badge === 'hidden'`：需要先开启哪个控制字段 */
  dependOn?: string[];
  /** 仅 `badge === 'readonly'`：真正生效的那个字段 */
  derivedFrom?: string[];
  /** 动态表条目的运行时命中，指向表格中的行键 */
  dynamicKey?: string;
}

export const SEARCH_LIMIT = 50;

interface Prep {
  meta: FieldMeta;
  id: string;
  order: number;
  page: string;
  runs: string[];
  full: string[];
  initials: string[];
}

/** schema 是静态的，索引只建一次 */
let cache: Prep[] | null = null;

function prepAll(): Prep[] {
  if (cache) return cache;

  const out: Prep[] = [];
  let order = 0;

  for (const page of pages) {
    for (const section of page.sections) {
      for (const meta of section.fields) {
        const runs = hanRuns(meta.title);
        out.push({
          meta,
          id: fieldId(meta.segments),
          order: order++,
          page: page.title,
          runs,
          full: runs.flatMap((r) => fullPinyinCandidates(r)),
          initials: runs.flatMap((r) => initialCandidates(r)),
        });
      }
    }
  }

  cache = out;
  return out;
}

// 只有测试会清缓存（schema 变了才有意义）
export function __clearIndexForTest(): void {
  cache = null;
}

function scoreOf(prep: Prep, q: string): { score: number; matchedBy: SearchHit['matchedBy'] } | null {
  const title = prep.meta.title.toLowerCase();

  if (title === q) return { score: 1000, matchedBy: 'title' };
  if (title.startsWith(q)) return { score: 800, matchedBy: 'title' };
  if (title.includes(q)) return { score: 600, matchedBy: 'title' };

  if (prep.meta.segments.some((s) => s.toLowerCase().includes(q))) {
    return { score: 500, matchedBy: 'segment' };
  }

  // 拼音只在「查询是 ASCII 字母」时才有意义，否则纯白算
  if (/^[a-z]+$/.test(q)) {
    for (const c of prep.full) {
      if (c.startsWith(q)) return { score: 400, matchedBy: 'pinyin' };
    }
    // 单字母不做「包含」匹配：会让任何词都命中，等于没有排序
    if (q.length >= 2) {
      for (const c of prep.full) {
        if (c.includes(q)) return { score: 300, matchedBy: 'pinyin' };
      }
    }
    for (const c of prep.initials) {
      // 首字母允许「包含」而不只是前缀：中文标题普遍是「语音识别服务端口」这种
      // 长定语结构，用户想敲的往往是后半截（dk）。只做前缀会让最常见的用法失效。
      if (c.startsWith(q)) return { score: 220, matchedBy: 'initial' };
    }
    if (q.length >= 2) {
      for (const c of prep.initials) {
        if (c.includes(q)) return { score: 200, matchedBy: 'initial' };
      }
    }
  }

  const note = (prep.meta.note ?? '').toLowerCase();
  if (note !== '' && note.includes(q)) return { score: 100, matchedBy: 'note' };

  return null;
}

/** 动态表条目：查询命中当前存在的行键或某列的文本时，补一条运行时命中 */
function dynamicHits(q: string, values: Record<string, JsonValue>): SearchHit[] {
  const out: SearchHit[] = [];

  for (const prep of prepAll()) {
    if (prep.meta.widget !== 'dynamicTable') continue;

    const rows = values[prep.id];
    if (typeof rows !== 'object' || rows === null) continue;

    for (const [key, cols] of Object.entries(rows as Record<string, JsonValue>)) {
      const texts = [key];
      if (typeof cols === 'object' && cols !== null) {
        for (const v of Object.values(cols as Record<string, JsonValue>)) texts.push(String(v));
      }

      if (!texts.some((t) => t.toLowerCase().includes(q))) continue;

      out.push({
        fieldId: `${prep.id}\u0000${key}`,
        segments: [...prep.meta.segments, key],
        title: key,
        page: prep.page,
        score: 700,
        matchedBy: 'title',
        dynamicKey: key,
        badge: isVisible(prep.meta, values) ? undefined : 'hidden',
      });
    }
  }

  return out;
}

function badgeOf(meta: FieldMeta, values: Record<string, JsonValue>): SearchHit['badge'] {
  if (meta.derivedFrom) return 'readonly';
  if (!isVisible(meta, values)) return 'hidden';
  return undefined;
}

export function searchAll(q: string): { hits: SearchHit[]; truncated: boolean } {
  const needle = q.trim().toLowerCase();
  if (needle === '') return { hits: [], truncated: false };

  const values = configStore.values();
  const prep = prepAll();

  const scored: { hit: SearchHit; order: number }[] = [];

  for (const p of prep) {
    const s = scoreOf(p, needle);
    if (!s) continue;

    const badge = badgeOf(p.meta, values);
    const hit: SearchHit = {
      fieldId: p.id,
      segments: [...p.meta.segments],
      title: p.meta.title,
      page: p.page,
      score: s.score,
      matchedBy: s.matchedBy,
    };
    if (badge) hit.badge = badge;
    if (badge === 'hidden' && p.meta.visibleWhen) hit.dependOn = [...p.meta.visibleWhen.segments];
    if (badge === 'readonly' && p.meta.derivedFrom) hit.derivedFrom = [...p.meta.derivedFrom];

    scored.push({ hit, order: p.order });
  }

  for (const hit of dynamicHits(needle, values)) {
    scored.push({ hit, order: Number.MAX_SAFE_INTEGER });
  }

  scored.sort((a, b) => b.hit.score - a.hit.score || a.order - b.order);

  const all = scored.map((x) => x.hit);
  return { hits: all.slice(0, SEARCH_LIMIT), truncated: all.length > SEARCH_LIMIT };
}

export function searchFields(q: string): SearchHit[] {
  return searchAll(q).hits;
}

/** 面板里按下回车时用它决定往哪跳：隐藏字段跳去控制项，其余跳自己 */
export function landingSegments(hit: SearchHit): string[] {
  if (hit.badge === 'hidden' && hit.dependOn) return hit.dependOn;
  if (hit.badge === 'readonly' && hit.derivedFrom) return hit.derivedFrom;
  return hit.segments;
}

/** 供面板显示「当前值」时用；secret 字段返回 undefined，避免把密钥摊在屏幕上 */
export function previewOf(fieldIdOrSegments: string | string[]): string | undefined {
  const meta = Array.isArray(fieldIdOrSegments)
    ? fieldById(fieldId(fieldIdOrSegments))
    : fieldById(fieldIdOrSegments);
  if (!meta || meta.widget === 'secret' || meta.widget === 'readonly') return undefined;

  const v = configStore.values()[fieldId(meta.segments)];
  if (v === undefined) return undefined;
  const text = typeof v === 'string' ? v : JSON.stringify(v);
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}
