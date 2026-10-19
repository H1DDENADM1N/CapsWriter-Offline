<script lang="ts">
  /**
   * 「没找到 config.toml」的引导页。
   *
   * 旧版 PySide6 程序直接把 `config.toml` 的相对路径交给 tomllib，找不到就抛
   * `FileNotFoundError` 栈，用户看到的是一个 Python traceback。这个页面把同一件
   * 事说成人话，并给出三条可行路径（放同目录 / 命令行指定 / 手动选）。
   */
  import { Button, Card } from 'm3-svelte';

  import { bridge } from '../../bridge.ts';
  import { configStore } from '../stores/config.svelte.ts';

  let choosing = $state(false);
  let error = $state<string | null>(null);

  async function choose(): Promise<void> {
    if (choosing) return;
    choosing = true;
    error = null;
    try {
      const picked = await bridge.pickPath('file', '选择 config.toml');
      if (!picked) return; // 用户取消
      // 走 store 而不是直接调 openConfig：定位、装配、脏状态复位都在这一条路上
      await configStore.load(picked);
    } catch (e) {
      error = typeof e === 'string' ? e : String(e);
    } finally {
      choosing = false;
    }
  }
</script>

<div class="onboarding">
  <Card variant="elevated">
    <h1>未找到 config.toml</h1>
    <p class="lead">本程序需要一个 config.toml 才能工作。可以这样解决：</p>

    <ol>
      <li>
        把 <code>config.toml</code> 放在本程序（<code>edit_config_gui.exe</code>）同一目录下，
        通常是 CapsWriter-Offline 的根目录。
      </li>
      <li>或者用命令行参数指定：<code>edit_config_gui.exe --config "D:\某处\config.toml"</code></li>
      <li>或者点下面的按钮手动选一个。</li>
    </ol>

    <p class="muted">
      注意：这个程序只改配置值，不会创建新文件——路径写错时新建一个空配置，比直接报错更难排查。
    </p>

    {#if error}
      <p class="err">{error}</p>
    {/if}

    <Button variant="filled" disabled={choosing} onclick={() => void choose()}>
      {choosing ? '正在读取…' : '选择 config.toml…'}
    </Button>
  </Card>
</div>

<style>
  /*
   * 居中一张浮起的卡片：这是应用启动失败时唯一的一屏，把说明从整页正文收进
   * 卡片后，视觉焦点会落在「选择 config.toml…」这个唯一的出口上。
   * m3 的 Card 只有 elevated/filled/outlined 三种变体，没有 surface-container-high，
   * 所以借父级作用域覆盖背景，保持与对话框同一档纸面。
   */
  .onboarding {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 32px 24px;
    background: var(--m3c-surface);
  }

  .onboarding > :global(.m3-container) {
    width: min(620px, 100%);
    padding: 32px;
    border-radius: var(--m3-shape-large);
    background: var(--m3c-surface-container-high);
    box-shadow: var(--m3-elevation-2);
  }

  h1 {
    margin: 0 0 12px;
    color: var(--m3c-on-surface);
    font-size: 22px;
    font-weight: 500;
    line-height: 28px;
  }

  .lead {
    margin: 0 0 16px;
    color: var(--m3c-on-surface-variant);
    font-size: 13px;
    line-height: 1.8;
  }

  ol {
    margin: 0 0 16px;
    padding-left: 24px;
    color: var(--m3c-on-surface);
    font-size: 13px;
    line-height: 1.9;
  }

  li {
    margin-bottom: 8px;
  }

  code {
    padding: 1px 6px;
    border-radius: var(--m3-shape-extra-small);
    background: var(--ecg-hover);
    font-family: var(--ecg-mono);
    font-size: 12px;
  }

  .muted {
    margin: 0 0 24px;
    color: var(--m3c-on-surface-variant);
    font-size: 12px;
    line-height: 1.8;
  }

  .err {
    margin: 0 0 16px;
    color: var(--m3c-error);
    font-size: 12px;
  }
</style>
