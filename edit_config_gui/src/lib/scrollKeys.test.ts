import { describe, expect, it, vi } from 'vitest';

import {
  ARROW_SCROLL,
  PAGE_RATIO,
  applyScrollKey,
  isTypingTarget,
  scrollDeltaForKey,
} from './scrollKeys.ts';

function keyEvent(over: Partial<{ key: string; target: EventTarget | null }> = {}) {
  const preventDefault = vi.fn();
  return {
    key: 'PageDown',
    target: null as EventTarget | null,
    preventDefault,
    ...over,
  };
}

function scroller(clientHeight = 800) {
  const scrollBy = vi.fn();
  return { clientHeight, scrollBy };
}

describe('scrollDeltaForKey', () => {
  it('PageDown / PageUp 按可视高度的 90% 翻页', () => {
    expect(scrollDeltaForKey('PageDown', 800)).toBe(800 * PAGE_RATIO);
    expect(scrollDeltaForKey('PageUp', 800)).toBe(-800 * PAGE_RATIO);
  });

  it('方向键固定滚 80px', () => {
    expect(scrollDeltaForKey('ArrowDown', 800)).toBe(ARROW_SCROLL);
    expect(scrollDeltaForKey('ArrowUp', 800)).toBe(-ARROW_SCROLL);
  });

  it('其它键不接管，交给页面自己处理', () => {
    expect(scrollDeltaForKey('Enter', 800)).toBeNull();
    expect(scrollDeltaForKey('a', 800)).toBeNull();
    expect(scrollDeltaForKey('End', 800)).toBeNull();
  });

  it('可视高度还没量出来（0 或负数）时不产生反向滚动', () => {
    expect(scrollDeltaForKey('PageDown', 0)).toBe(0);
    expect(scrollDeltaForKey('PageDown', -100)).toBe(0);
  });
});

describe('isTypingTarget', () => {
  const el = (tagName: string, extra: Record<string, unknown> = {}) =>
    ({ tagName, ...extra }) as unknown as EventTarget;

  it('输入类控件里不接管方向键', () => {
    expect(isTypingTarget(el('INPUT', { type: 'text' }))).toBe(true);
    expect(isTypingTarget(el('INPUT', { type: 'password' }))).toBe(true);
    expect(isTypingTarget(el('INPUT', { type: 'number' }))).toBe(true);
    expect(isTypingTarget(el('TEXTAREA'))).toBe(true);
    expect(isTypingTarget(el('SELECT'))).toBe(true);
  });

  it('内容可编辑区域同样让开', () => {
    expect(isTypingTarget(el('DIV', { isContentEditable: true }))).toBe(true);
  });

  it('普通容器、按钮、null 都不算输入目标', () => {
    expect(isTypingTarget(el('DIV'))).toBe(false);
    expect(isTypingTarget(el('BUTTON'))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
    expect(isTypingTarget(el('BODY'))).toBe(false);
  });
});

describe('applyScrollKey', () => {
  it('PageDown 滚一屏并吃掉默认行为', () => {
    const e = keyEvent({ key: 'PageDown' });
    const sc = scroller(800);

    expect(applyScrollKey(e, sc, false)).toBe(true);
    expect(sc.scrollBy).toHaveBeenCalledWith({ top: 800 * PAGE_RATIO });
    expect(e.preventDefault).toHaveBeenCalled();
  });

  it('↑/↓ 滚 80px，方向相反', () => {
    const down = keyEvent({ key: 'ArrowDown' });
    const up = keyEvent({ key: 'ArrowUp' });
    const sc = scroller();

    applyScrollKey(down, sc, false);
    applyScrollKey(up, sc, false);

    expect(sc.scrollBy).toHaveBeenNthCalledWith(1, { top: ARROW_SCROLL });
    expect(sc.scrollBy).toHaveBeenNthCalledWith(2, { top: -ARROW_SCROLL });
  });

  it('输入框里不接管，也不吃掉按键', () => {
    const e = keyEvent({ target: { tagName: 'INPUT', type: 'text' } as unknown as EventTarget });
    const sc = scroller();

    expect(applyScrollKey(e, sc, false)).toBe(false);
    expect(sc.scrollBy).not.toHaveBeenCalled();
    expect(e.preventDefault).not.toHaveBeenCalled();
  });

  it('命令面板 / 对话框开着时不接管（方向键归它们）', () => {
    const e = keyEvent();
    const sc = scroller();

    expect(applyScrollKey(e, sc, true)).toBe(false);
    expect(sc.scrollBy).not.toHaveBeenCalled();
  });

  it('按住 Ctrl/Alt/Meta 时不当翻页用', () => {
    const sc = scroller();
    for (const mod of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }]) {
      const e = { ...keyEvent(), ...mod };
      expect(applyScrollKey(e, sc, false)).toBe(false);
    }
    expect(sc.scrollBy).not.toHaveBeenCalled();
  });

  it('还没挂上滚动容器时不报错', () => {
    const e = keyEvent();
    expect(applyScrollKey(e, null, false)).toBe(false);
  });

  it('非翻页键一律放行', () => {
    const e = keyEvent({ key: 'Enter' });
    const sc = scroller();
    expect(applyScrollKey(e, sc, false)).toBe(false);
    expect(sc.scrollBy).not.toHaveBeenCalled();
  });
});
