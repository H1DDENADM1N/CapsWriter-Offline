<script lang="ts">
  import { onMount } from 'svelte';

  import CommandPalette from './lib/components/CommandPalette.svelte';
  import DiffDialog from './lib/components/DiffDialog.svelte';
  import DirtyBar from './lib/components/DirtyBar.svelte';
  import Onboarding from './lib/components/Onboarding.svelte';
  import PageView from './lib/components/pages/PageView.svelte';
  import Sidebar from './lib/components/Sidebar.svelte';
  import StatusBar from './lib/components/StatusBar.svelte';
  import { configStore } from './lib/stores/config.svelte.ts';
  import { saveStore } from './lib/stores/save.svelte.ts';

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

  /**
   * `Ctrl+S` 走的是和底部「保存…」按钮同一条路径：先预览、再确认。
   * 不做「按一下就写盘」——这个程序改的是服务端/客户端共用的配置，一次误触
   * 就可能让别人的调试会话中断。
   */
  function onKeydown(e: KeyboardEvent): void {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      void saveStore.preview();
    }
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
        <main class="content">
          {#if phase === 'loading'}
            <p class="hint">正在读取 config.toml…</p>
          {:else if phase === 'ready'}
            <PageView />
          {:else}
            <div class="hint">
              <p>读取配置失败：</p>
              <pre>{configStore.lastError()}</pre>
              <button type="button" onclick={() => void configStore.load()}>重试</button>
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
  :global(html, body) {
    height: 100%;
    margin: 0;
  }

  :global(body) {
    background: var(--ecg-bg, #fff);
    color: var(--ecg-fg, #1c1f23);
    font-family:
      'Microsoft YaHei UI', 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 13px;
  }

  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
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
  }

  .content {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
  }

  .hint {
    padding: 24px 26px;
    color: var(--ecg-muted, #888);
    font-size: 13px;
    line-height: 1.8;
  }

  pre {
    padding: 10px 12px;
    border-radius: 6px;
    background: var(--ecg-hover, #f3f4f7);
    color: var(--ecg-fg, #1c1f23);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
