<script lang="ts">
  import { SEARCH_LIMIT, landingSegments, searchAll } from '../search.ts';
  import type { SearchHit } from '../search.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import { paletteStore } from '../stores/palette.svelte.ts';

  const result = $derived(searchAll(paletteStore.query()));
  const hits = $derived(result.hits);

  /**
   * 选中项。
   *
   * 每次查询变化后 `selectedIndex` 会被重置为 0，所以这里只做防御性夹取：
   * 结果集比下标短时（删到只剩两条）不能取到 undefined。
   */
  const selected = $derived(hits[Math.min(paletteStore.selectedIndex(), Math.max(hits.length - 1, 0))]);

  const badgeText = (h: SearchHit): string | null => {
    if (h.badge === 'hidden') return '当前隐藏';
    if (h.badge === 'readonly') return '只读';
    return null;
  };

  function choose(hit: SearchHit | undefined): void {
    if (!hit) return;
    paletteStore.pushRecent(hit.fieldId);
    navStore.focus(landingSegments(hit));
    paletteStore.hide();
  }

  /**
   * 打开即聚焦输入框。
   *
   * 不用 `autofocus` 属性：Svelte 会报 a11y_autofocus，而且真实 Tauri 窗口里
   * autofocus 与 WebView2 的首次焦点竞争时偶发不生效；用动作在挂载后主动 focus
   * 更可控（面板每次打开都是新挂载的节点）。
   */
  function focusOnMount(node: HTMLInputElement): void {
    queueMicrotask(() => node.focus());
  }

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'k' && (e.ctrlKey || e.metaKey) && !e.altKey) {
      e.preventDefault();
      paletteStore.show();
      return;
    }

    if (!paletteStore.open()) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      paletteStore.hide();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      paletteStore.move(1, hits.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      paletteStore.move(-1, hits.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(selected);
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if paletteStore.open()}
  <div
    class="backdrop"
    role="presentation"
    onclick={(e) => {
      // 只有点到遮罩本身才关；点面板内部不该关。用 target === currentTarget 判断，
      // 就不必在面板上再挂一个只为 stopPropagation 的 click 处理器（那个空处理器
      // 会触发 a11y_click_events_have_key_events，而它确实没有键盘语义）。
      if (e.target === e.currentTarget) paletteStore.hide();
    }}
    onkeydown={(e) => {
      if (e.key === 'Escape') paletteStore.hide();
    }}
  >
    <div
      class="panel"
      role="dialog"
      aria-modal="true"
      tabindex="-1"
      aria-label="搜索配置项"
    >
      <input
        class="query"
        type="text"
        use:focusOnMount
        placeholder="搜配置项：中文、键名、拼音全拼或首字母"
        value={paletteStore.query()}
        oninput={(e) => paletteStore.setQuery(e.currentTarget.value)}
      />

      {#if paletteStore.query().trim() === ''}
        {#if paletteStore.recent().length > 0}
          <p class="hint">这次打开改过的项：{paletteStore.recent().length} 个</p>
        {:else}
          <p class="hint">输入关键词开始搜索，↑↓ 选择，回车跳转，Esc 关闭。</p>
        {/if}
      {:else if hits.length === 0}
        <p class="hint">没有匹配的配置项。</p>
      {:else}
        <ul class="list" role="listbox" aria-label="搜索结果">
          {#each hits as hit (hit.fieldId)}
            <li
              class="row"
              class:active={selected?.fieldId === hit.fieldId}
              role="option"
              aria-selected={selected?.fieldId === hit.fieldId}
              tabindex="-1"
              onmousedown={(e) => {
                e.preventDefault();
                choose(hit);
              }}
            >
              <span class="title">{hit.title}</span>
              <span class="path">{hit.segments.join('.')}</span>
              {#if badgeText(hit)}
                <span class="badge">{badgeText(hit)}</span>
              {/if}
              <span class="page">{hit.page}</span>
            </li>
          {/each}
        </ul>

        {#if result.truncated}
          <p class="hint">只显示前 {SEARCH_LIMIT} 条，请再补充几个字。</p>
        {/if}
      {/if}

      {#if selected?.badge === 'hidden' && selected.dependOn}
        <p class="hint">
          该项当前被隐藏，取决于 <code>{selected.dependOn.join('.')}</code>；回车会跳到那个开关。
        </p>
      {:else if selected?.badge === 'readonly' && selected.derivedFrom}
        <p class="hint">
          该项是占位符，程序只会读 <code>{selected.derivedFrom.join('.')}</code>；回车会跳到那里。
        </p>
      {/if}
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    justify-content: center;
    padding-top: 12vh;
    background: rgb(0 0 0 / 25%);
  }

  .panel {
    width: min(620px, 88vw);
    max-height: 60vh;
    padding: 10px;
    border-radius: 10px;
    background: var(--ecg-bg, #fff);
    box-shadow: 0 12px 40px rgb(0 0 0 / 22%);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .query {
    width: 100%;
    padding: 9px 10px;
    border: 1px solid var(--ecg-line, #dfe2e8);
    border-radius: 7px;
    background: none;
    color: inherit;
    font: inherit;
    font-size: 14px;
    outline: none;
  }

  .query:focus {
    border-color: var(--ecg-accent, #1a56c4);
  }

  .list {
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
    overflow-y: auto;
  }

  .row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 7px 9px;
    border-radius: 6px;
    cursor: pointer;
  }

  .row.active {
    background: var(--ecg-active, #e8eefb);
  }

  .title {
    flex: 0 1 auto;
    font-size: 13px;
  }

  .path {
    flex: 1 1 auto;
    min-width: 0;
    color: var(--ecg-muted, #888);
    font-family: ui-monospace, Consolas, monospace;
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .badge {
    flex: 0 0 auto;
    padding: 0 5px;
    border-radius: 4px;
    background: var(--ecg-hover, #f3f4f7);
    color: var(--ecg-muted, #888);
    font-size: 11px;
  }

  .page {
    flex: 0 0 auto;
    color: var(--ecg-muted, #888);
    font-size: 11px;
  }

  .hint {
    margin: 8px 2px 2px;
    color: var(--ecg-muted, #888);
    font-size: 12px;
    line-height: 1.6;
  }

  code {
    font-family: ui-monospace, Consolas, monospace;
  }
</style>
