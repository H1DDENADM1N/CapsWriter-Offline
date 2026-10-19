/**
 * MD3 配色：把 Windows 当前主题色展开成一整套 `--m3c-*` 令牌。
 *
 * 为什么要有这个文件（而不是在 store 里直接调 m3-svelte）：
 * 「哪个候选色才算主题色」是一条需要解释、也需要测的规则——DWM 色在开着
 * 「自动从背景取色」时可能接近纯黑，直接拿它当种子会得到一整套灰调配色。
 * 纯函数放这里，store 只管生命周期（轮询、注入 <style>）。
 *
 * 生成的是 `light-dark(<light>, <dark>)` 形式（见 m3-svelte `etc/colors`）：
 * 一份 CSS 同时描述深浅两套，实际取哪套由 `color-scheme` 决定，而 `color-scheme`
 * 由 theme store 按注册表写。这样切换深浅色不需要重新生成 CSS。
 */

import { Hct, SchemeTonalSpot } from '@ktibow/material-color-utilities-nightly';
import { colors, genCSS } from 'm3-svelte/etc/colors';

/** 读不到系统主题色时的种子：Windows 默认蓝，生成的配色仍然像「系统色」。 */
export const DEFAULT_ACCENT = '#0078d4';

/**
 * 低于这个 HCT 彩度就认为「这不是用户选的主题色」。
 *
 * 12 是刻意的低门槛：Windows 的强调色允许选很淡的粉、很深的紫，彩度 20 上下
 * 就已经是合法的自定义色；真正要挡的是自动取色混出来的近黑/近灰（彩度 < 5，
 * 例如本机 `ColorizationColor` 解出来的 rgb(1,0,0)）。
 */
export const MIN_CHROMA = 12;

/** `#rgb` / `#rrggbb` → `0xAARRGGBB`（alpha 固定 ff，HCT 只吃不透明色）。非法返回 null。 */
export function hexToArgb(hex: string): number | null {
  const raw = hex.trim().replace(/^#/, '');
  const full =
    raw.length === 3
      ? raw
          .split('')
          .map((c) => c + c)
          .join('')
      : raw;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  return (0xff000000 | Number.parseInt(full, 16)) >>> 0;
}

/** `0xAARRGGBB` → `#rrggbb`（丢掉 alpha）。 */
export function argbToHex(argb: number): string {
  return `#${((argb >>> 0) & 0xffffff).toString(16).padStart(6, '0')}`;
}

/**
 * 从候选里挑出第一个「够鲜艳」的颜色当种子；都不够鲜艳就用默认蓝。
 *
 * 顺序有意义：Rust 侧把更接近系统当前外观的候选排在前面（DWM 色 → 强调色），
 * 这里只负责淘汰不可信的，不重排。
 */
export function pickAccent(candidates: readonly string[]): string {
  for (const candidate of candidates) {
    const argb = hexToArgb(candidate);
    if (argb === null) continue;
    if (Hct.fromInt(argb).chroma >= MIN_CHROMA) return argbToHex(argb);
  }
  return DEFAULT_ACCENT;
}

/**
 * 生成令牌 CSS。
 *
 * 只给种子色、不暴露 scheme 对象：调用方（store）不需要知道 MD3 的 scheme 种类，
 * 配色方案以后想换（TonalSpot → Vibrant 之类）也只改这里一行。
 */
export function themeCss(accent: string): string {
  const argb = hexToArgb(accent) ?? (hexToArgb(DEFAULT_ACCENT) as number);
  const source = Hct.fromInt(argb);
  return genCSS(
    new SchemeTonalSpot(source, false, 0),
    new SchemeTonalSpot(source, true, 0),
    colors,
  );
}
