import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { DEFAULT_ACCENT, argbToHex, hexToArgb, pickAccent, themeCss } from './theme.ts';

describe('hexToArgb', () => {
  it('解析六位写法并补上不透明 alpha', () => {
    expect(hexToArgb('#0078d4')).toBe(0xff0078d4);
    expect(hexToArgb('0078d4')).toBe(0xff0078d4);
    expect(hexToArgb('  #0078D4 ')).toBe(0xff0078d4);
  });

  it('展开三位简写', () => {
    expect(hexToArgb('#fff')).toBe(0xffffffff);
    expect(hexToArgb('#08d')).toBe(0xff0088dd);
  });

  it('非法输入返回 null 而不是 NaN', () => {
    // NaN 一旦流进 Hct.fromInt 会得到 undefined 令牌且没有任何报错
    expect(hexToArgb('')).toBeNull();
    expect(hexToArgb('#12')).toBeNull();
    expect(hexToArgb('#gggggg')).toBeNull();
    expect(hexToArgb('#1234567')).toBeNull();
    expect(hexToArgb('rgb(0, 120, 212)')).toBeNull();
  });
});

describe('argbToHex', () => {
  it('丢掉 alpha 并补零到六位', () => {
    expect(argbToHex(0xc4_00_78_d4)).toBe('#0078d4');
    expect(argbToHex(0xff_00_00_01)).toBe('#000001');
  });

  it('与 hexToArgb 互逆', () => {
    for (const hex of ['#000000', '#ffffff', '#b1d300', '#8e44ad']) {
      expect(argbToHex(hexToArgb(hex) as number)).toBe(hex);
    }
  });
});

describe('pickAccent', () => {
  it('跳过近黑的 DWM 色，取下一个候选', () => {
    // 本机实测：开着「自动从背景取色」时 ColorizationColor 解出来就是近黑
    expect(pickAccent(['#010000', '#0078d4'])).toBe('#0078d4');
  });

  it('第一个候选够鲜艳时原样返回（小写归一）', () => {
    expect(pickAccent(['#B1D300'])).toBe('#b1d300');
  });

  it('候选为空、全是垃圾、或全是灰时回退默认蓝', () => {
    expect(pickAccent([])).toBe(DEFAULT_ACCENT);
    expect(pickAccent(['nope', '#12345'])).toBe(DEFAULT_ACCENT);
    expect(pickAccent(['#808080', '#c0c0c0'])).toBe(DEFAULT_ACCENT);
  });
});

describe('themeCss', () => {
  const css = themeCss('#0078d4');

  it('同时给出深浅两套色值', () => {
    // 一份 CSS 描述两套，靠 color-scheme 切换，切主题不用重新生成
    expect(css).toContain('color-scheme: light dark');
    expect(css).toMatch(/--m3c-surface: light-dark\(#f\w{5}, #1\w{5}\)/);
  });

  it('包含组件真正会用到的令牌', () => {
    for (const token of [
      '--m3c-surface',
      '--m3c-surface-container-low',
      '--m3c-surface-container-highest',
      '--m3c-on-surface',
      '--m3c-on-surface-variant',
      '--m3c-outline',
      '--m3c-outline-variant',
      '--m3c-primary',
      '--m3c-on-primary',
      '--m3c-primary-container',
      '--m3c-secondary-container',
      '--m3c-tertiary',
      '--m3c-error',
      '--m3c-shadow',
    ]) {
      expect(css).toContain(`${token}:`);
    }
  });

  it('不同种子生成不同配色；非法种子退回默认蓝', () => {
    expect(themeCss('#0078d4')).not.toBe(themeCss('#b1d300'));
    expect(themeCss('不是颜色')).toBe(css);
  });
});

describe('app.css：下拉列表（picker）的主题覆盖', () => {
  // 原生 <select> 的候选列表由浏览器绘制，m3-svelte 里那条 ::picker(select) 规则
  // 会被 Svelte 加上作用域类而失效，结果列表退回系统浅色的默认外观。
  // 这是全局样式文件里必须存在、且不能被「整理」掉的一段。
  // 直接读源文件：vitest 的 css 处理会把 `?raw` 也清空，只能走文件系统。
  const css = readFileSync(resolve(process.cwd(), 'src/app.css'), 'utf8');
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');

  it('用不带前缀的 ::picker(select) 声明 appearance: base-select', () => {
    // 只写 select::picker() 或带作用域类，Chromium 都不认，列表会退回平台原生菜单（固定浅色）
    expect(withoutComments).toMatch(/(^|\n)\s*::picker\(select\)\s*\{/);
    const block = withoutComments.slice(withoutComments.indexOf('::picker(select) {'));
    expect(block).toContain('appearance: base-select');
    expect(block).toContain('--m3c-surface-container-high');
    expect(block).toContain('color-scheme: inherit');
  });

  it('picker 内部只写普通 option 选择器，不写伪元素后跟选择器', () => {
    // `::picker(select) option` 这种写法 lightningcss 直接报错（构建失败），
    // 而 `select::picker(select)` 这类带前缀的写法 Chromium 不认。
    expect(withoutComments).not.toMatch(/::picker\(select\)\s+[a-z.#[:]/);
    expect(withoutComments).toMatch(/(^|\n)\s*option:checked\s*\{/);
  });

  it('整套样式表里不出现 prefers-color-scheme 媒体查询：它的来源和 Windows 设置不是一回事', () => {
    // 注释里提到这个名字是允许的（那是「为什么禁止」的说明），真正的规则块不行
    expect(withoutComments).not.toMatch(/@media[^{}]*prefers-color-scheme/);
  });
});
