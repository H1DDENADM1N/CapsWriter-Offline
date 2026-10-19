<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from 'm3-svelte';

  import CommandPalette from './lib/components/CommandPalette.svelte';
  import DiffDialog from './lib/components/DiffDialog.svelte';
  import DirtyBar from './lib/components/DirtyBar.svelte';
  import Onboarding from './lib/components/Onboarding.svelte';
  import PageView from './lib/components/pages/PageView.svelte';
  import Sidebar from './lib/components/Sidebar.svelte';
  import StatusBar from './lib/components/StatusBar.svelte';
  import TopBar from './lib/components/TopBar.svelte';
  import { configStore } from './lib/stores/config.svelte.ts';
  import { paletteStore } from './lib/stores/palette.svelte.ts';
  import { saveStore } from './lib/stores/save.svelte.ts';
  import { applyScrollKey } from './lib/scrollKeys.ts';

  /**
   * `__forceState` 仅测试用。
   *
   * 「没找到 config.toml」这一态在 jsdom 里没法自然走到（要么真的让 IPC 失败，
   * 要么去 mock Tauri internals 的拒绝路径），而它恰好是用户第一次运行时唯一会
   * 看到的页面——最该被测试盯住的一屏，反而最容易没人测。
   */
  let { __forceState }: { __forceState?: 'onboarding' } = $props();

  onMount(() => {
    if (__forceState) return;
    void configStore.load();
  });

  const phase = $derived(__forceState ?? configStore.state());

  /** 主内容区（唯一的长滚动容器）。翻页键要滚的就是它。 */
  let contentEl = $state<HTMLElement | null>(null);

  /** 这些阶段下屏幕被对话框占着，方向键另有含义，不能拿去滚页面。 */
  const SAVE_DIALOG_PHASES = new Set(['confirm', 'committing', 'conflict', 'done', 'failed']);

  /**
   * 翻页 / 方向键滚动主内容区。
   *
   * 「该不该接管」的规则（焦点在输入框、按住修饰键、面板/对话框开着）都在
   * `scrollKeys.ts` 里，这里只负责把当前状态喂给它——那部分逻辑在 jsdom 里也能测。
   *
   * 用 `behavior: 'auto'` 而不是动画：连按方向键时平滑滚动会排队，手停了页面还在飘。
   */
  function scrollOnKey(e: KeyboardEvent): void {
    const modalOpen = paletteStore.open() || SAVE_DIALOG_PHASES.has(saveStore.phase().kind);
    applyScrollKey(e, contentEl, modalOpen);
  }

  /**
   * `Ctrl+S` 走的是和底部「保存…」按钮同一条路径：先预览、再确认。
   * 不做「按一下就写盘」——这个程序改的是服务端/客户端共用的配置，一次误触
   * 就可能让别人的调试会话中断。
   */
  function onKeydown(e: KeyboardEvent): void {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      void saveStore.preview();
      return;
    }
    scrollOnKey(e);
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if phase === 'onboarding'}
  <Onboarding />
{:else}
  <div class="app">
    <div class="shell">
      <Sidebar />

      <div class="main">
        <TopBar />

        <main class="content" bind:this={contentEl}>
          {#if phase === 'loading'}
            <p class="hint">正在读取 config.toml…</p>
          {:else if phase === 'ready'}
            <PageView />
          {:else}
            <div class="hint">
              <p class="err-title">读取配置失败：</p>
              <pre>{configStore.lastError()}</pre>
              <Button variant="tonal" onclick={() => void configStore.load()}>重试</Button>
            </div>
          {/if}
        </main>

        <DirtyBar />
      </div>
    </div>

    {#if phase === 'ready'}
      <StatusBar />
    {/if}
  </div>
{/if}

<CommandPalette />
<DiffDialog />

<style>
  /*
   * 窗口底色统一用 surface：侧栏/顶栏/状态栏各自是 surface-container-low，
   * 主内容留在 surface 上，层级靠色板而不是靠 1px 描边拼接出来。
   * html/body 的基础样式在 app.css 里，这里不重复定义，避免出现两套字体与底色。
   */
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    background: var(--m3c-surface);
    color: var(--m3c-on-surface);
  }

  .shell {
    display: flex;
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
  }

  .main {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-width: 0;
    background: var(--m3c-surface);
  }

  .content {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
  }

  .hint {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
    max-width: 72ch;
    padding: 24px 32px;
    color: var(--m3c-on-surface-variant);
    font-size: 13px;
    line-height: 1.8;
  }

  .hint p {
    margin: 0;
  }

  .err-title {
    color: var(--m3c-error);
    font-weight: 600;
  }

  /* 错误详情可能是一整段 Rust 报错，等宽字体比正文更容易逐字对照 */
  pre {
    align-self: stretch;
    margin: 0;
    padding: 12px 16px;
    border-radius: var(--m3-shape-medium);
    background: var(--m3c-surface-container-high);
    color: var(--m3c-on-surface);
    font-family: var(--ecg-mono);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
