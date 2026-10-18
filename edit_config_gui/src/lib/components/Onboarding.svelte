<script lang="ts">
  /**
   * 「没找到 config.toml」的引导页。
   *
   * 旧版 PySide6 程序直接把 `config.toml` 的相对路径交给 tomllib，找不到就抛
   * `FileNotFoundError` 栈，用户看到的是一个 Python traceback。这个页面把同一件
   * 事说成人话，并给出三条可行路径（放同目录 / 命令行指定 / 手动选）。
   */
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

  <button type="button" class="primary" disabled={choosing} onclick={() => void choose()}>
    {choosing ? '正在读取…' : '选择 config.toml…'}
  </button>
</div>

<style>
  .onboarding {
    max-width: 620px;
    margin: 0 auto;
    padding: 56px 26px;
    line-height: 1.9;
  }

  h1 {
    margin: 0 0 12px;
    font-size: 19px;
  }

  .lead {
    margin: 0 0 14px;
    color: var(--ecg-muted, #666);
    font-size: 13px;
  }

  ol {
    margin: 0 0 14px;
    padding-left: 22px;
    font-size: 13px;
  }

  li {
    margin-bottom: 6px;
  }

  code {
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--ecg-hover, #f0f1f4);
    font-family: Consolas, 'Cascadia Mono', monospace;
    font-size: 12px;
  }

  .muted {
    margin: 0 0 18px;
    color: var(--ecg-muted, #888);
    font-size: 12px;
  }

  .err {
    margin: 0 0 14px;
    color: var(--ecg-danger, #c0392b);
    font-size: 12px;
  }

  button {
    padding: 7px 16px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 5px;
    background: var(--ecg-bg, #fff);
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .primary {
    border-color: var(--ecg-accent, #2f6feb);
    background: var(--ecg-accent, #2f6feb);
    color: #fff;
  }
</style>
