<script lang="ts">
  /**
   * 底部保存条。
   *
   * 只在真的有改动时出现——常驻一个灰掉的「保存」按钮，会让人误以为程序随时
   * 准备写盘；而把所有改动都攒到「关闭窗口时弹一个『要保存吗』」，则是另一类
   * 灾难（关窗口前根本看不到自己改了什么）。
   */
  import { Button } from 'm3-svelte';

  import { configStore } from '../stores/config.svelte.ts';
  import { saveStore } from '../stores/save.svelte.ts';

  const count = $derived(configStore.dirtyCount());
  const busy = $derived(saveStore.busy());
  const problems = $derived(Object.keys(configStore.errors()).length);
</script>

{#if count > 0}
  <!-- 浮动在内容底部之上、但不遮住最后一行字段：圆角 + elevation-2 让它从
       surface 上浮起来，和状态栏（surface-container-low）形成两层。 -->
  <footer class="bar">
    <span class="count">{count} 项未保存</span>
    {#if problems > 0}
      <span class="err">{problems} 项有错误</span>
    {/if}
    <span class="spacer"></span>
    <Button variant="text" size="s" onclick={() => saveStore.discardAll()}>全部还原</Button>
    <Button
      variant="filled"
      size="s"
      disabled={busy}
      onclick={() => void saveStore.preview()}
    >
      {busy ? '处理中…' : '保存…'}
    </Button>
  </footer>
{/if}

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 0 0 auto;
    margin: 0 16px 16px;
    padding: 8px 8px 8px 20px;
    border-radius: var(--m3-shape-large);
    background: var(--m3c-surface-container-high);
    box-shadow: var(--m3-elevation-2);
  }

  .count {
    color: var(--m3c-on-surface);
    font-size: 13px;
    font-weight: 600;
  }

  .err {
    color: var(--m3c-error);
    font-size: 12px;
  }

  .spacer {
    flex: 1 1 auto;
  }
</style>
