<script lang="ts">
  import { onMount } from 'svelte';

  import CommandPalette from './lib/components/CommandPalette.svelte';
  import PageView from './lib/components/pages/PageView.svelte';
  import Sidebar from './lib/components/Sidebar.svelte';
  import { configStore } from './lib/stores/config.svelte.ts';

  onMount(() => {
    void configStore.load();
  });

  const phase = $derived(configStore.state());
</script>

<div class="shell">
  <Sidebar />

  <main class="content">
    {#if phase === 'loading'}
      <p class="hint">正在读取 config.toml…</p>
    {:else if phase === 'ready'}
      <PageView />
    {:else if phase === 'onboarding'}
      <div class="hint">
        <p>没找到 config.toml。</p>
        <p>请确认本程序放在 CapsWriter-Offline 目录下，或手动选择一个配置文件。</p>
      </div>
    {:else}
      <div class="hint">
        <p>读取配置失败：</p>
        <pre>{configStore.lastError()}</pre>
        <button type="button" onclick={() => void configStore.load()}>重试</button>
      </div>
    {/if}
  </main>
</div>

<CommandPalette />

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

  .shell {
    display: flex;
    height: 100vh;
    overflow: hidden;
  }

  .content {
    flex: 1 1 auto;
    min-width: 0;
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
