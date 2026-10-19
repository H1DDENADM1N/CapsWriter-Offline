<script lang="ts">
  import { Icon, TextField } from 'm3-svelte';

  import { ICONS } from '../fieldIcons.ts';
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
   *
   * 输入框改由 m3 `TextField` 渲染后，本组件拿不到那个 `<input>` 的引用，所以动作
   * 挂在字段容器上，挂载后往里找唯一的 input。仍然只 focus 一次，不订阅任何状态。
   */
  function focusOnMount(node: HTMLElement): void {
    queueMicrotask(() => node.querySelector('input')?.focus());
  }

  function onKeydown(e: KeyboardEvent): void {
    // Ctrl+F：和浏览器「页内查找」同一个手指记忆，正好也是「找配置项」
    if (e.key === 'f' && (e.ctrlKey || e.metaKey) && !e.altKey) {
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
    <div class="panel" role="dialog" aria-modal="true" tabindex="-1" aria-label="搜索配置项">
      <div class="field" use:focusOnMount>
        <!--
          键盘事件仍然由窗口级处理器统一接管：输入框里的 ↑↓/回车/Esc 会冒泡到
          window，选中与跳转逻辑只有一份，不会因为换成组件而分裂成两套。
        -->
        <TextField
          class="query"
          label="搜索配置项"
          placeholder="搜配置项：中文、键名、拼音全拼或首字母"
          aria-label="搜索配置项"
          autocomplete="off"
          value={paletteStore.query()}
          oninput={(e) => paletteStore.setQuery(e.currentTarget.value)}
        />
      </div>

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
              <Icon class="mark" icon={ICONS[hit.icon] ?? ICONS.info} size={16} aria-hidden="true" />
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
  /* 遮罩用 MD3 的 scrim 令牌调透明度，而不是写死的半透明黑：深浅主题下
     scrim 本身就是「浮层之后的暗色」，不会出现深色主题里遮罩反而发灰的问题。 */
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    justify-content: center;
    padding-top: 12vh;
    background: color-mix(in oklab, var(--m3c-scrim) 32%, transparent);
  }

  .panel {
    width: min(620px, 88vw);
    max-height: 60vh;
    padding: 24px;
    border-radius: var(--m3-shape-extra-large);
    background: var(--m3c-surface-container-high);
    box-shadow: var(--m3-elevation-3);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* TextField 的容器是 inline-flex 且带 min-width，不撑满面板会在宽面板里显得很窄。
     高度取 MD3 单行字段的 3.5rem（56px，与 --m3-density 的标准值一致），
     这样即使 app.css 的 density 函数被改动，搜索框也保持单行字段的标准高度。 */
  .field :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 56px;
  }

  /* 去掉 app.css 给原生 input 的 2px 焦点描边：m3 TextField 有自己的聚焦指示
     （标签与底线变主色），两套叠在一起会像输入框套了个框。 */
  .field :global(input:focus-visible) {
    outline: none;
  }

  .list {
    flex: 1 1 auto;
    min-height: 0;
    margin: 0;
    padding: 0;
    list-style: none;
    overflow-y: auto;
  }

  /* MD3 单行 list item：56px 高、左右 16px。hover 用状态层颜色，选中用
     secondary-container —— 与 m3 组件自身的选中态是同一个语义。 */
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 56px;
    padding: 0 16px;
    border-radius: var(--m3-shape-medium);
    cursor: pointer;
  }

  .row:hover {
    background: var(--ecg-hover);
  }

  .row.active {
    background: var(--ecg-active);
    color: var(--m3c-on-secondary-container);
  }

  .title {
    flex: 0 1 auto;
    color: var(--m3c-on-surface);
    font-size: 13px;
  }

  /* 结果行前面的图形标志：和配置项行上的是同一个图标，找起来对得上号 */
  .row :global(.mark) {
    flex: 0 0 auto;
    color: var(--m3c-on-surface-variant);
    fill: currentColor;
  }

  .row.active :global(.mark) {
    color: var(--m3c-on-secondary-container);
  }

  .path {
    flex: 1 1 auto;
    min-width: 0;
    color: var(--ecg-muted);
    font-family: var(--ecg-mono);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .badge {
    flex: 0 0 auto;
    padding: 2px 8px;
    border-radius: var(--m3-shape-full);
    background: var(--ecg-tag-bg);
    color: var(--ecg-tag-fg);
    font-size: 11px;
  }

  .page {
    flex: 0 0 auto;
    color: var(--ecg-muted);
    font-size: 11px;
  }

  .row.active .title,
  .row.active .path,
  .row.active .page {
    color: var(--m3c-on-secondary-container);
  }

  .hint {
    margin: 0;
    color: var(--m3c-on-surface-variant);
    font-size: 12px;
    line-height: 1.6;
  }

  code {
    padding: 0 4px;
    border-radius: var(--m3-shape-extra-small);
    background: var(--ecg-hover);
    font-family: var(--ecg-mono);
  }
</style>
