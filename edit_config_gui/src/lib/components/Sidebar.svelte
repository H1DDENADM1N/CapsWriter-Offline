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
  .sidebar {
    display: flex;
    flex: 0 0 200px;
    flex-direction: column;
    width: 200px;
    padding: 14px 10px 10px;
    border-right: 1px solid var(--ecg-line, #eceef2);
    transition:
      width 0.16s ease,
      flex-basis 0.16s ease,
      padding 0.16s ease;
  }

  .sidebar.collapsed {
    flex-basis: 56px;
    width: 56px;
    padding: 14px 6px 10px;
  }

  .list {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 2px;
    min-height: 0;
    overflow-y: auto;
    /* 滚动条不该把图标列挤偏 */
    scrollbar-gutter: stable;
  }

  .foot {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--ecg-line, #eceef2);
  }

  .item {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    padding: 7px 10px;
    border: 0;
    border-radius: 6px;
    background: none;
    color: inherit;
    font: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
  }

  .collapsed .item {
    justify-content: center;
    padding: 8px 0;
  }

  .item:hover {
    background: var(--ecg-hover, #f3f4f7);
  }

  .item.active {
    background: var(--ecg-active, #e8eefb);
    box-shadow: inset 2px 0 0 var(--ecg-accent, #1a56c4);
    font-weight: 600;
    color: var(--ecg-accent, #1a56c4);
  }

  .lead {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .lead :global(svg) {
    flex: 0 0 auto;
    opacity: 0.85;
  }

  .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .collapsed .title {
    display: none;
  }

  .badge {
    min-width: 18px;
    padding: 0 5px;
    border-radius: 9px;
    background: var(--ecg-warn, #e0932f);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    line-height: 18px;
    text-align: center;
  }

  /* 折叠后没有文字，徽标改成右上角的小圆点，否则会把图标挤扁 */
  .collapsed .badge {
    position: absolute;
    top: 2px;
    right: 4px;
    min-width: 14px;
    padding: 0 3px;
    font-size: 10px;
    line-height: 14px;
  }
</style>
