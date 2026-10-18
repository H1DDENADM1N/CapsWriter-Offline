<script lang="ts">
  import { fieldById, fieldId } from '../schema/index.ts';
  import type { FieldMeta } from '../schema/types.ts';
  import { configStore } from '../stores/config.svelte.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import { widgetFor } from './widgets/index.ts';

  let { field }: { field: FieldMeta } = $props();

  const id = $derived(fieldId(field.segments));
  const value = $derived(configStore.values()[id]);
  const error = $derived(configStore.errorOf(id));
  const dirty = $derived(configStore.dirtyIds().has(id));

  /**
   * 显隐用 `{#if}` 而不是 CSS `display:none`：被藏起来的输入框仍能被 Tab 聚焦、
   * 仍会被读屏软件念出来，用户会对着一个看不见的控件打字。
   */
  const visible = $derived.by(() => {
    const w = field.visibleWhen;
    if (!w) return true;

    const current = configStore.values()[fieldId(w.segments)];
    if (w.equals !== undefined) return current === w.equals;
    if (w.in !== undefined) return w.in.includes(current as never);
    return true;
  });

  /** 表名 → 中文，用于只读字段的「来源」面包屑 */
  const TABLE_LABELS: Record<string, string> = {
    model_paths: '模型路径',
    funasr_args: 'FunASR 参数',
    sensevoice_args: 'SenseVoice 参数',
    paraformer_args: 'Paraformer 参数',
    client: '客户端',
    server: '服务端',
  };

  const breadcrumb = $derived.by(() => {
    const src = field.derivedFrom;
    if (!src) return '';

    return src
      .map((seg, i) => {
        if (TABLE_LABELS[seg]) return TABLE_LABELS[seg];
        // 叶子段用该字段自己的标题（「模型路径」页里那个字段的 title），
        // 中间层不是字段，退回原始段名
        const hit = fieldById(fieldId(src.slice(0, i + 1)));
        return hit?.title ?? seg;
      })
      .join(' › ');
  });
</script>

{#if visible}
  {@const Widget = widgetFor(field.widget)}

  <div class="field" class:wide={field.widget === 'longText' || field.widget === 'dynamicTable'}>
    <div class="label">
      <span class="row">
        <span class="title">{field.title}</span>
        {#if dirty}
          <span class="dirty">已修改</span>
        {/if}
      </span>
      {#if field.note}
        <p class="note">{field.note}</p>
      {/if}
    </div>

    <div class="control">
      <Widget {field} {value} {error} onChange={(v) => configStore.setValue(id, v)} />

      {#if field.derivedFrom}
        <p class="source">
          <span>来源：{breadcrumb}</span>
          <button type="button" onclick={() => navStore.focus(field.derivedFrom!)}>跳转到来源</button>
        </p>
      {/if}
    </div>

    {#if error}
      <p class="error">{error}</p>
    {/if}
  </div>
{/if}

<style>
  .field {
    display: grid;
    grid-template-columns: minmax(13em, 26%) 1fr;
    gap: 4px 16px;
    padding: 10px 0;
    border-bottom: 1px solid var(--ecg-line, #eceef2);
    align-items: start;
  }

  .field:last-child {
    border-bottom: none;
  }

  .field.wide {
    grid-template-columns: 1fr;
  }

  .label {
    min-width: 0;
  }

  .row {
    display: flex;
    gap: 8px;
    align-items: baseline;
  }

  .title {
    font-weight: 500;
  }

  .dirty {
    padding: 0 6px;
    border-radius: 999px;
    background: var(--ecg-accent-weak, #3b82f622);
    color: var(--ecg-accent, #3b82f6);
    font-size: 11px;
    line-height: 18px;
    white-space: nowrap;
  }

  .note {
    margin: 4px 0 0;
    color: var(--ecg-muted, #888);
    font-size: 12px;
    line-height: 1.55;
    white-space: pre-line;
  }

  .control {
    min-width: 0;
  }

  .source {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 6px 0 0;
    color: var(--ecg-muted, #888);
    font-size: 12px;
  }

  .source button {
    padding: 2px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 999px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    font-size: 12px;
  }

  .error {
    grid-column: 1 / -1;
    margin: 4px 0 0;
    color: var(--ecg-danger, #d33);
    font-size: 12px;
  }

  @media (max-width: 760px) {
    .field {
      grid-template-columns: 1fr;
    }
  }
</style>
