<script lang="ts">
  import { allFields, fieldId, pageOfSegments, pages } from '../schema/index.ts';
  import type { PageMeta } from '../schema/types.ts';
  import { configStore } from '../stores/config.svelte.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import { uiStore } from '../stores/ui.svelte.ts';
  import Icon from './Icon.svelte';

  /**
   * 「关于」不放主列表：它不配置任何东西，混在 12 个配置页里会让人以为也是必填项。
   * 固定到最下方，用分隔线与配置页区分开。
   */
  const aboutPage = $derived(pages.find((p) => p.id === 'about'));
  const configPages = $derived(pages.filter((p) => p.id !== 'about'));
  const collapsed = $derived(uiStore.sidebarCollapsed());

  /**
   * 该页有几个脏字段。
   *
   * 页归属必须靠 `pageOfSegments` 反查，不能用 `segments[0]` 猜：`client.zhipuai`
   * 属于 `aiProviders` 页、`client.prompt_style` 属于 `promptStyles` 页，按段名
   * 算会把它们的脏计数记到「客户端」头上，用户点进去却找不到改过的那一行。
   */
  function dirtyCountOf(pageId: string): number {
    const dirty = configStore.dirtyIds();
    if (dirty.size === 0) return 0;

    let n = 0;
    for (const meta of allFields()) {
      if (meta.widget === 'readonly') continue;
      if (pageOfSegments(meta.segments)?.id !== pageId) continue;
      if (dirty.has(fieldId(meta.segments))) n += 1;
    }
    return n;
  }
</script>

<!--
  `role="tablist"` 这套语义是测试与读屏共用的接口，视觉按 MD3 NavigationRail 做，
  但不换成 m3 的 NavigationRail 组件——它的子项没有 tab/tablist 语义。
-->
{#snippet navItem(page: PageMeta)}
  {@const n = dirtyCountOf(page.id)}
  <button
    type="button"
    role="tab"
    class="item"
    class:active={navStore.current() === page.id}
    aria-selected={navStore.current() === page.id}
    aria-label={page.title}
    title={collapsed ? page.title : undefined}
    onclick={() => navStore.go(page.id)}
  >
    <span class="lead">
      <Icon name={page.icon} />
      <span class="title">{page.title}</span>
    </span>
    {#if n > 0}
      <span class="badge" title={`${n} 项改动尚未保存`}>{n}</span>
    {/if}
  </button>
{/snippet}

<div
  class="sidebar"
  class:collapsed
  role="tablist"
  aria-label="配置页导航"
  aria-orientation="vertical"
>
  <div class="list">
    {#each configPages as page (page.id)}
      {@render navItem(page)}
    {/each}
  </div>

  {#if aboutPage}
    <div class="foot">
      {@render navItem(aboutPage)}
    </div>
  {/if}
</div>

<style>
  /*
   * MD3 NavigationRail：展开时 200px 显示「图标 + 标题」，折叠时 56px 只剩图标。
   * 底色用 surface-container-low，与主内容（surface）拉开一档层级。
   */
  .sidebar {
    display: flex;
    flex: 0 0 200px;
    flex-direction: column;
    width: 200px;
    padding: 12px 8px 8px;
    background: var(--m3c-surface-container-low);
    border-right: 1px solid var(--m3c-outline-variant);
    transition:
      width 0.16s ease,
      flex-basis 0.16s ease,
      padding 0.16s ease;
  }

  .sidebar.collapsed {
    flex-basis: 56px;
    width: 56px;
    padding: 12px 4px 8px;
  }

  .list {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
    overflow-y: auto;
    /* 滚动条不该把图标列挤偏 */
    scrollbar-gutter: stable;
  }

  .foot {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--m3c-outline-variant);
  }

  .item {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    /* 48px 行高保证鼠标/触屏都够按，折叠后同样高度，切换时不会跳 */
    min-height: 48px;
    width: 100%;
    padding: 0 12px;
    border: 0;
    border-radius: var(--m3-shape-full);
    background: transparent;
    color: var(--m3c-on-surface-variant);
    font: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition:
      background-color 0.12s ease,
      color 0.12s ease;
  }

  .collapsed .item {
    justify-content: center;
    padding: 0;
  }

  .item:hover {
    background: var(--ecg-hover);
    color: var(--m3c-on-surface);
  }

  /* 激活项用胶囊指示器 + secondary-container，是 MD3 的「选中」语义；
     不再用左侧 2px 竖条——那是桌面列表的旧语言。 */
  .item.active {
    background: var(--m3c-secondary-container);
    color: var(--m3c-on-secondary-container);
    font-weight: 600;
  }

  .lead {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }

  .lead :global(svg) {
    flex: 0 0 auto;
  }

  .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .collapsed .title {
    display: none;
  }

  /* 未保存数量用 MD3 大徽标（error 色胶囊），比黄底白字更符合状态语义 */
  .badge {
    min-width: 20px;
    padding: 0 6px;
    border-radius: var(--m3-shape-full);
    background: var(--m3c-error);
    color: var(--m3c-on-error);
    font-size: 11px;
    font-weight: 600;
    line-height: 20px;
    text-align: center;
  }

  /* 折叠后没有文字，徽标改成右上角的小圆点，否则会把图标挤扁 */
  .collapsed .badge {
    position: absolute;
    top: 2px;
    right: 2px;
    min-width: 16px;
    padding: 0 4px;
    font-size: 10px;
    line-height: 16px;
  }

  @media (prefers-reduced-motion: reduce) {
    .sidebar {
      transition: none;
    }

    .item {
      transition: none;
    }
  }
</style>
