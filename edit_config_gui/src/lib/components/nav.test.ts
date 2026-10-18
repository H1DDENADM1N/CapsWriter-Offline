import { fireEvent, render } from '@testing-library/svelte';
import { beforeEach, describe, expect, it } from 'vitest';

import { fieldId, pages } from '../schema/index.ts';
import { configStore } from '../stores/config.svelte.ts';
import { navStore } from '../stores/nav.svelte.ts';
import Sidebar from './Sidebar.svelte';

beforeEach(() => {
  configStore.__resetForTest();
  navStore.__resetForTest();
  navStore.go(pages[0]!.id);
});

describe('Sidebar', () => {
  it('13 个导航项按 pages 顺序渲染', () => {
    const { getAllByRole } = render(Sidebar);
    const items = getAllByRole('tab').map((el) => el.textContent?.trim() ?? '');

    expect(items).toHaveLength(13);
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
});
