<script lang="ts">
  /**
   * 底部保存条。
   *
   * 只在真的有改动时出现——常驻一个灰掉的「保存」按钮，会让人误以为程序随时
   * 准备写盘；而把所有改动都攒到「关闭窗口时弹一个『要保存吗』」，则是另一类
   * 灾难（关窗口前根本看不到自己改了什么）。
   */
  import { configStore } from '../stores/config.svelte.ts';
  import { saveStore } from '../stores/save.svelte.ts';

  const count = $derived(configStore.dirtyCount());
  const busy = $derived(saveStore.busy());
  const problems = $derived(Object.keys(configStore.errors()).length);
</script>

{#if count > 0}
  <footer class="bar">
    <span class="count">{count} 项未保存</span>
    {#if problems > 0}
      <span class="err">{problems} 项有错误</span>
    {/if}
    <span class="spacer"></span>
    <button type="button" onclick={() => saveStore.discardAll()}>全部还原</button>
    <button
      type="button"
      class="primary"
      disabled={busy}
      onclick={() => void saveStore.preview()}
    >
      {busy ? '处理中…' : '保存…'}
    </button>
  </footer>
{/if}

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 0 0 auto;
    padding: 10px 18px;
    border-top: 1px solid var(--ecg-border, #dcdfe6);
    background: var(--ecg-panel, #fafbfc);
  }

  .count {
    font-size: 13px;
    font-weight: 600;
  }

  .err {
    font-size: 12px;
    color: var(--ecg-danger, #c0392b);
  }

  .spacer {
    flex: 1 1 auto;
  }

  button {
    padding: 6px 14px;
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
