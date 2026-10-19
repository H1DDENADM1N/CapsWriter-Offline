<script lang="ts">
  import { Button, TextFieldOutlined } from 'm3-svelte';
  import { bridge } from '../../../bridge.ts';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  let busy = $state(false);
  let failure = $state<string | null>(null);

  const text = $derived(value == null ? '' : String(value));

  // 「选目录」还是「选文件」由校验器决定，而不是再给 schema 加一个字段：
  // 挂了 dirExist 的必然是目录，剩下的是文件。
  const mode = $derived<'file' | 'dir'>(
    (field.validators ?? []).includes('dirExist') ? 'dir' : 'file',
  );

  async function browse(): Promise<void> {
    busy = true;
    failure = null;
    try {
      const picked = await bridge.pickPath(mode, field.title);
      if (picked) onChange(picked);
    } catch (e) {
      // 静默失败会让人以为点了没反应，必须把原因显示出来
      failure = String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="w-path">
  <div class="row">
    <div class="field">
      <TextFieldOutlined
        label=""
        type="text"
        aria-label={field.title}
        title={text}
        error={Boolean(error)}
        aria-invalid={error ? 'true' : undefined}
        value={text}
        spellcheck="false"
        oninput={(e) => onChange(e.currentTarget.value)}
      />
    </div>
    <Button variant="tonal" size="s" disabled={busy} onclick={browse}>
      {busy ? '选择中…' : '浏览…'}
    </Button>
  </div>
  {#if failure}
    <p class="failure">{failure}</p>
  {/if}
</div>

<style>
  .w-path {
    width: 100%;
    min-width: 0;
  }

  .row {
    display: flex;
    gap: 8px;
    align-items: center;
    width: 100%;
    min-width: 0;
  }

  /* 基数为 0：输入框吃掉按钮之外的全部空间。用 auto 的话基数取决于内容宽度，
     而 m3 输入框里的 <input> 是绝对定位的，内容宽度约等于 0，整行会被按钮占满。 */
  .field {
    flex: 1 1 0;
    min-width: 0;
  }

  .w-path :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  /* 路径是逐字符读的，等宽字体能让同目录下的一串文件更好对比 */
  .w-path :global(input) {
    padding: 0 12px;
    font-size: 12px;
    font-family: var(--ecg-mono);
  }

  /* 上面那条 .m3-container 规则同样命中 Button（它也带 m3-container 类），
     于是按钮也拿到 width:100%，会把同一行的输入框挤成 0 宽。按钮必须恢复自适应宽度。 */
  .w-path :global(button.m3-container) {
    flex: 0 0 auto;
    width: auto;
    height: 40px;
    white-space: nowrap;
  }

  .failure {
    margin: 4px 0 0;
    color: var(--ecg-danger);
    font-size: 12px;
  }
</style>
