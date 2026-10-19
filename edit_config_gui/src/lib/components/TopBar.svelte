<script lang="ts">
  import { Button } from 'm3-svelte';

  import { pages } from '../schema/index.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import { paletteStore } from '../stores/palette.svelte.ts';
  import { uiStore } from '../stores/ui.svelte.ts';
  import { zoomStore } from '../stores/zoom.svelte.ts';
  import Icon from './Icon.svelte';

  const page = $derived(pages.find((p) => p.id === navStore.current()) ?? pages[0]);
  const collapsed = $derived(uiStore.sidebarCollapsed());
  const zoomed = $derived(!zoomStore.isDefault());
  const zoomPct = $derived(zoomStore.percent());
</script>

<!-- MD3 small top app bar：高 64px、标题 title-large、操作用文字/描边按钮。
     侧栏展开/折叠仍由 uiStore 持久化，和旧版行为一致。 -->
<header class="topbar">
  <Button
    variant="text"
    iconType="full"
    size="s"
    aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
    aria-expanded={!collapsed}
    title={collapsed ? '展开侧边栏' : '折叠侧边栏'}
    onclick={() => uiStore.toggleSidebar()}
  >
    <Icon name="panel" size={20} />
  </Button>

  <h1>{page?.title ?? ''}</h1>

  <span class="spacer"></span>

  <!-- 只在「不是 100%」时出现：还原按钮平时没有信息量，常驻只会挤掉标题。
       按 Ctrl+0 与滚轮缩放回原值同样会让它自己消失，因为判断的是状态不是点击。 -->
  {#if zoomed}
    <div class="zoom">
      <Button
        variant="text"
        size="s"
        title={`当前缩放 ${zoomPct}%（Ctrl + 0 还原）`}
        aria-label={`恢复默认缩放，当前 ${zoomPct}%`}
        onclick={() => zoomStore.reset()}
      >
        <span class="pct">{zoomPct}%</span>
        <span class="text">还原</span>
      </Button>
    </div>
  {/if}

  <div class="search">
    <Button
      variant="outlined"
      iconType="left"
      size="s"
      title="搜索配置项（Ctrl + F）"
      onclick={() => paletteStore.show()}
    >
      <Icon name="search" size={18} />
      <span class="text">搜索配置</span>
      <kbd>Ctrl F</kbd>
    </Button>
  </div>
</header>

<style>
  .topbar {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 8px;
    height: 64px;
    padding: 0 16px 0 8px;
    background: var(--m3c-surface-container-low);
    border-bottom: 1px solid var(--m3c-outline-variant);
  }

  /* 标题是这一行唯一的主信息，22px/500 对应 MD3 title-large 的字重与字号 */
  h1 {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    color: var(--m3c-on-surface);
    font-size: 22px;
    font-weight: 500;
    line-height: 28px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .spacer {
    flex: 1 1 auto;
  }

  /* 百分比用等宽数字：从 110% 变到 125% 时按钮宽度不跳，右侧的搜索按钮不会左右挪 */
  .pct {
    font-variant-numeric: tabular-nums;
  }

  .search :global(kbd) {
    padding: 1px 6px;
    border: 1px solid var(--m3c-outline-variant);
    border-radius: var(--m3-shape-extra-small);
    background: var(--ecg-hover);
    color: var(--m3c-on-surface-variant);
    font-family: inherit;
    font-size: 11px;
  }

  /* 窄窗口下把快捷键提示收起来，先保住按钮本身和标题 */
  @media (max-width: 720px) {
    .search :global(kbd) {
      display: none;
    }
  }

  /* 再窄一档先砍「还原」两个字，百分数留着——它本身就说清了现在多大 */
  @media (max-width: 640px) {
    .zoom .text {
      display: none;
    }
  }

  @media (max-width: 560px) {
    .search .text {
      display: none;
    }
  }
</style>
