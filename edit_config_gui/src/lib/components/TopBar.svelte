<script lang="ts">
  import { pages } from '../schema/index.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import { paletteStore } from '../stores/palette.svelte.ts';
  import { uiStore } from '../stores/ui.svelte.ts';
  import Icon from './Icon.svelte';

  const page = $derived(pages.find((p) => p.id === navStore.current()) ?? pages[0]);
  const collapsed = $derived(uiStore.sidebarCollapsed());
</script>

<header class="topbar">
  <button
    type="button"
    class="icon-btn"
    aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
    aria-expanded={!collapsed}
    title={collapsed ? '展开侧边栏' : '折叠侧边栏'}
    onclick={() => uiStore.toggleSidebar()}
  >
    <Icon name="panel" size={17} />
  </button>

  <h1>{page?.title ?? ''}</h1>

  <span class="spacer"></span>

  <button
    type="button"
    class="search-btn"
    title="搜索配置项（Ctrl + K）"
    onclick={() => paletteStore.show()}
  >
    <Icon name="search" size={15} />
    <span class="text">搜索配置</span>
    <kbd>Ctrl K</kbd>
  </button>
</header>

<style>
  .topbar {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 10px;
    padding: 10px 18px 10px 12px;
    border-bottom: 1px solid var(--ecg-line, #eceef2);
  }

  h1 {
    margin: 0;
    font-size: 19px;
    font-weight: 600;
    white-space: nowrap;
  }

  .spacer {
    flex: 1 1 auto;
  }

  .icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 6px;
    background: none;
    color: var(--ecg-muted-strong, #4b5563);
    cursor: pointer;
  }

  .icon-btn:hover {
    border-color: var(--ecg-border, #dcdfe6);
    background: var(--ecg-hover, #f3f4f7);
  }

  .search-btn {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 10px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 7px;
    background: var(--ecg-input-bg, #fff);
    color: var(--ecg-muted-strong, #4b5563);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }

  .search-btn:hover {
    border-color: var(--ecg-accent, #1a56c4);
    color: var(--ecg-accent, #1a56c4);
  }

  kbd {
    padding: 1px 5px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 4px;
    background: var(--ecg-hover, #f3f4f7);
    font-family: inherit;
    font-size: 11px;
    color: var(--ecg-muted, #888);
  }

  /* 窄窗口下把快捷键提示收起来，先保住按钮本身和标题 */
  @media (max-width: 720px) {
    kbd {
      display: none;
    }
  }

  @media (max-width: 560px) {
    .search-btn .text {
      display: none;
    }
  }
</style>
