<script lang="ts">
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
    <input
      type="text"
      aria-label={field.title}
      title={text}
      aria-invalid={error ? 'true' : undefined}
      value={text}
      spellcheck="false"
      oninput={(e) => onChange(e.currentTarget.value)}
    />
    <button type="button" disabled={busy} onclick={browse}>{busy ? '选择中…' : '浏览…'}</button>
  </div>
  {#if failure}
    <p class="failure">{failure}</p>
  {/if}
</div>

<style>
  .row {
    display: flex;
    gap: 6px;
  }

  .row input {
    flex: 1;
    min-width: 0;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
    font-family: var(--ecg-mono, ui-monospace, Consolas, monospace);
    font-size: 12px;
  }

  .row input[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }

  .row button {
    padding: 6px 10px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    white-space: nowrap;
  }

  .row button:disabled {
    opacity: 0.6;
    cursor: default;
  }

  .failure {
    margin: 4px 0 0;
    color: var(--ecg-danger, #d33);
    font-size: 12px;
  }
</style>
