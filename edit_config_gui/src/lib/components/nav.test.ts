import { fireEvent, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fieldId, pages } from '../schema/index.ts';
import { configStore } from '../stores/config.svelte.ts';
import { navStore } from '../stores/nav.svelte.ts';
import { paletteStore } from '../stores/palette.svelte.ts';
import { uiStore } from '../stores/ui.svelte.ts';
import { zoomStore } from '../stores/zoom.svelte.ts';
import Sidebar from './Sidebar.svelte';
import TopBar from './TopBar.svelte';

/*
 * m3-svelte 的入口会连带求值 Slider（→ svelte/motion），后者在模块顶层读
 * matchMedia 来跟踪 prefers-reduced-motion；jsdom 没实现这个 API。
 * 用 vi.hoisted 保证补丁先于任何 import 生效。
 */
vi.hoisted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia === 'function') return;
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
});

beforeEach(() => {
  configStore.__resetForTest();
  navStore.__resetForTest();
  paletteStore.__resetForTest();
  uiStore.__resetForTest();
  zoomStore.__resetForTest();
  navStore.go(pages[0]!.id);
});

describe('Sidebar', () => {
  it('14 个导航项按 pages 顺序渲染', () => {
    const { getAllByRole } = render(Sidebar);
    const items = getAllByRole('tab').map((el) => el.textContent?.trim() ?? '');

    expect(items).toHaveLength(14);
    expect(items[0]).toContain(pages[0]!.title);
  });

  it('点击切换 current', async () => {
    const { getByText } = render(Sidebar);
    await fireEvent.click(getByText(pages[1]!.title));

    expect(navStore.current()).toBe(pages[1]!.id);
  });

  it('当前页的导航项标记 aria-selected', () => {
    const { getAllByRole } = render(Sidebar);
    const tabs = getAllByRole('tab');

    expect(tabs[0]!.getAttribute('aria-selected')).toBe('true');
    expect(tabs[1]!.getAttribute('aria-selected')).toBe('false');
  });

  it('该页有脏字段时导航项出现脏计数', () => {
    configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');

    const { getAllByRole } = render(Sidebar);
    const serverTab = getAllByRole('tab')[0]!;

    expect(serverTab.textContent).toMatch(/1/);
  });

  it('跨页的脏字段记在真正的归属页上', () => {
    // client.zhipuai 属于「AI 服务商」页，不属于「客户端」页
    configStore.setValue(fieldId(['client', 'zhipuai', 'api_key']), 'sk-test');

    const { getAllByRole } = render(Sidebar);
    const tabs = getAllByRole('tab');
    const clientTab = tabs.find((t) => t.textContent?.includes('客户端'))!;
    const providerTab = tabs.find((t) => t.textContent?.includes('AI 服务商'))!;

    expect(providerTab.textContent).toMatch(/1/);
    expect(clientTab.textContent).not.toMatch(/\d/);
  });

  it('没有脏字段时不渲染徽标', () => {
    const { getAllByRole } = render(Sidebar);

    for (const tab of getAllByRole('tab')) {
      expect(tab.querySelector('.badge')).toBeNull();
    }
  });

  it('go() 会清空 highlight', () => {
    navStore.focus(['server', 'addr']);
    expect(navStore.highlight()).not.toBeNull();

    navStore.go(pages[1]!.id);
    expect(navStore.highlight()).toBeNull();
  });

  it('「关于」固定在最后，且不混在配置页列表里', () => {
    const { getAllByRole, container } = render(Sidebar);
    const tabs = getAllByRole('tab');

    expect(tabs).toHaveLength(14);
    expect(tabs.at(-1)!.getAttribute('aria-label')).toBe('关于');
    // 结构上也得分开：主列表只放配置页
    const list = container.querySelector('.list')!;
    expect(list.querySelectorAll('[role="tab"]')).toHaveLength(13);
    expect(container.querySelector('.foot')!.textContent).toContain('关于');
  });

  it('折叠后隐藏文字但保留图标与可访问名', async () => {
    const { getAllByRole, container } = render(Sidebar);

    expect(container.querySelector('.sidebar')!.classList.contains('collapsed')).toBe(false);

    uiStore.toggleSidebar();
    // store 是模块级 $state：改完必须让 Svelte 冲刷一次，否则 DOM 还是旧的
    await tick();

    expect(container.querySelector('.sidebar')!.classList.contains('collapsed')).toBe(true);
    const tabs = getAllByRole('tab');
    // 文字节点还在 DOM 里（CSS 隐藏），但可访问名必须仍然完整
    expect(tabs[0]!.getAttribute('aria-label')).toBe(pages[0]!.title);
    expect(tabs[0]!.getAttribute('title')).toBe(pages[0]!.title);
    expect(tabs[0]!.querySelector('svg')).not.toBeNull();
  });
});

describe('navStore.pulse', () => {
  it('每次 focus() 自增，同一项连跳两次也自增（闪烁靠它重播）', () => {
    const before = navStore.pulse();

    navStore.focus(['server', 'addr']);
    expect(navStore.pulse()).toBe(before + 1);

    // highlight 值没变，靠 pulse 才能让「再闪一次」成立
    navStore.focus(['server', 'addr']);
    expect(navStore.pulse()).toBe(before + 2);
  });

  it('普通切页不参与计数', () => {
    const before = navStore.pulse();
    navStore.go(pages[1]!.id);
    expect(navStore.pulse()).toBe(before);
  });
});

describe('TopBar', () => {
  it('显示当前页标题', async () => {
    const { getByRole } = render(TopBar);
    expect(getByRole('heading', { level: 1 }).textContent).toBe(pages[0]!.title);

    navStore.go('debug');
    await Promise.resolve();
    expect(getByRole('heading', { level: 1 }).textContent).toBe('调试');
  });

  it('右上角搜索按钮打开命令面板', async () => {
    const { getByTitle } = render(TopBar);

    expect(paletteStore.open()).toBe(false);
    await fireEvent.click(getByTitle('搜索配置项（Ctrl + F）'));
    expect(paletteStore.open()).toBe(true);
  });

  it('折叠按钮切换侧边栏状态并写进 aria-expanded', async () => {
    const { getByLabelText } = render(TopBar);

    const btn = getByLabelText('折叠侧边栏');
    expect(btn.getAttribute('aria-expanded')).toBe('true');

    await fireEvent.click(btn);
    expect(uiStore.sidebarCollapsed()).toBe(true);
    expect(getByLabelText('展开侧边栏').getAttribute('aria-expanded')).toBe('false');
  });

  it('缩放不是 100% 时出现「还原」，点击后消失', async () => {
    const { queryByLabelText, getByLabelText } = render(TopBar);

    // 100% 时不该有还原按钮：它平时没有信息量，只该在需要时出现
    expect(queryByLabelText(/恢复默认缩放/)).toBeNull();

    zoomStore.zoomIn();
    await tick();

    const btn = getByLabelText('恢复默认缩放，当前 110%');
    expect(btn.textContent).toContain('110%');

    await fireEvent.click(btn);
    await tick();

    expect(zoomStore.current()).toBe(1);
    expect(queryByLabelText(/恢复默认缩放/)).toBeNull();
  });
});
