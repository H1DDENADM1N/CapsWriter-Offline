<script lang="ts">
  import { allFields, fieldId, pageOfSegments, pages } from '../schema/index.ts';
  import { configStore } from '../stores/config.svelte.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import Icon from './Icon.svelte';

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

<div class="sidebar" role="tablist" aria-label="配置页导航">
  {#each pages as page (page.id)}
    {@const n = dirtyCountOf(page.id)}
    <button
      type="button"
      role="tab"
      class="item"
      class:active={navStore.current() === page.id}
      aria-selected={navStore.current() === page.id}
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
  {/each}
</div>

<style>
  .sidebar {
    display: flex;
    flex: 0 0 200px;
    flex-direction: column;
    gap: 2px;
    width: 200px;
    padding: 14px 10px;
    border-right: 1px solid var(--ecg-line, #eceef2);
    overflow-y: auto;
  }

  .item {
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
</style>
