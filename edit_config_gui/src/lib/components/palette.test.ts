import { fireEvent, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fieldId } from '../schema/index.ts';
import { configStore } from '../stores/config.svelte.ts';
import { navStore } from '../stores/nav.svelte.ts';
import { paletteStore } from '../stores/palette.svelte.ts';
import CommandPalette from './CommandPalette.svelte';

/**
 * jsdom 没有实现 `window.matchMedia`，而 `m3-svelte` 的包入口在求值时会把
 * Slider 一起带进来，它内部用 Svelte 的 `MediaQuery` 读 `prefers-reduced-motion`。
 * 这是测试环境的缺口，不是面板的行为；用 `vi.hoisted` 补在静态 import 求值之前。
 */
vi.hoisted(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

beforeEach(() => {
  configStore.__resetForTest();
  navStore.__resetForTest();
  paletteStore.__resetForTest();
});

/** store 是模块级 `$state`，改动要等一次 tick 才会落到 DOM */
async function openWith(query?: string): Promise<void> {
  paletteStore.show();
  if (query !== undefined) paletteStore.setQuery(query);
  await tick();
}

describe('命令面板', () => {
  it('Ctrl+F 打开、Esc 关闭', async () => {
    render(CommandPalette);

    await fireEvent.keyDown(window, { key: 'f', ctrlKey: true });
    expect(paletteStore.open()).toBe(true);
    await tick();
    expect(document.querySelector('.panel')).not.toBeNull();

    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(paletteStore.open()).toBe(false);
  });

  it('输入关键词后列出结果', async () => {
    render(CommandPalette);
    await openWith();

    const input = document.querySelector<HTMLInputElement>('.query')!;
    await fireEvent.input(input, { target: { value: 'duankou' } });
    await tick();

    expect(paletteStore.query()).toBe('duankou');
    expect(document.querySelectorAll('[role="option"]').length).toBeGreaterThan(0);
  });

  it('↑↓ 移动选中项并在越界时回卷', async () => {
    render(CommandPalette);
    await openWith('端口');

    const count = document.querySelectorAll('[role="option"]').length;
    expect(count).toBeGreaterThan(1);

    await fireEvent.keyDown(window, { key: 'ArrowDown' });
    expect(paletteStore.selectedIndex()).toBe(1);

    await fireEvent.keyDown(window, { key: 'ArrowUp' });
    expect(paletteStore.selectedIndex()).toBe(0);

    await fireEvent.keyDown(window, { key: 'ArrowUp' });
    expect(paletteStore.selectedIndex()).toBe(count - 1);
  });

  it('回车跳转、写进 recent 并关闭', async () => {
    render(CommandPalette);
    await openWith('adb_addr');

    await fireEvent.keyDown(window, { key: 'Enter' });

    expect(paletteStore.open()).toBe(false);
    // 隐藏字段跳去控制项，而不是跳到一个看不见的控件
    expect(navStore.highlight()).toBe(fieldId(['client', 'enable_adb_control']));
    expect(navStore.current()).toBe('client');
    expect(paletteStore.recent()).toEqual([fieldId(['client', 'adb_addr'])]);
  });

  it('回车跳转普通字段时高亮自己', async () => {
    render(CommandPalette);
    await openWith('speech_recognition_port');

    await fireEvent.keyDown(window, { key: 'Enter' });

    expect(navStore.highlight()).toBe(fieldId(['server', 'speech_recognition_port']));
  });

  it('每条结果前面带 MD3 图形标志', async () => {
    render(CommandPalette);
    await openWith('adb_addr');

    const row = document.querySelector('[role="option"]')!;
    const mark = row.querySelector('.mark');
    expect(mark).toBeTruthy();
    expect(mark!.querySelector('path')).not.toBeNull();
    expect(mark!.getAttribute('aria-hidden')).toBe('true');
  });

  it('点击遮罩关闭，点击面板本身不关闭', async () => {
    render(CommandPalette);
    await openWith();

    await fireEvent.click(document.querySelector('.panel')!);
    expect(paletteStore.open()).toBe(true);

    await fireEvent.click(document.querySelector('.backdrop')!);
    expect(paletteStore.open()).toBe(false);
  });

  it('空查询时不请求搜索，只给操作提示', async () => {
    render(CommandPalette);
    await openWith();

    expect(document.querySelectorAll('[role="option"]')).toHaveLength(0);
    expect(document.body.textContent).toContain('回车跳转');
  });
});
