<script lang="ts">
  import { fieldId } from '../schema/index.ts';
  import type { FieldMeta } from '../schema/types.ts';
  import { configStore } from '../stores/config.svelte.ts';
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

  /*
   * 只读派生键的「来源 + 跳转」由 ReadonlyWidget 负责：它知道真实生效值长什么样、
   * 也知道占位符不该被当成内容。Field 这里不再重复画一遍，否则同一行会出现两个
   * 语义相同的跳转按钮。
   */
</script>

{#if visible}
  {@const Widget = widgetFor(field.widget)}

  <div class="field" class:wide={field.widget === 'longText' || field.widget === 'dynamicTable'} class:bool={field.widget === 'bool'}>
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
    </div>

    {#if error}
      <p class="error">{error}</p>
    {/if}
  </div>
{/if}

<style>
  /*
   * 两列：标签占剩余空间，控件列贴住内容区右边缘。
   *
   * 控件列用 clamp 而不是百分比或 1fr：纯百分比在 2560 宽的窗口上会把下拉框
   * 拉到一千多像素，纯 1fr 又会把控件挤到标签旁边、右边留一大片空白。clamp 让
   * 它在窄窗口下仍有 300px 可用、宽窗口下最多 560px，且**永远右对齐**——
   * 每一行的输入框右边缘都落在同一条竖线上，右边不会再有空档。
   */
  .field {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(320px, 52%, 620px);
    gap: 4px 20px;
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
    /* 说明文字不要跟着宽窗口拉成一整行，读起来会串行 */
    max-width: 46em;
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
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  /* 开关本身没有宽度可拉伸，靠右放，右边缘才和别的控件对齐 */
  .field.bool .control {
    align-items: flex-end;
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

    .field.bool .control {
      align-items: flex-start;
    }
  }
</style>
