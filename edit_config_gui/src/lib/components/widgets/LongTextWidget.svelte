<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const text = $derived(value == null ? '' : String(value));

  // 只有这 8 段提示词正文是多行键（config.toml 里本来就用 """ 包着）。
  // 单行键必须走 TextWidget：toml_edit 遇到含 \n 的单行键会自动升格成 """ 多行，
  // 那是格式改写，不是用户预期的编辑（见规格 §9.5）。
  const rows = $derived(Math.min(18, Math.max(4, text.split('\n').length + 1)));
</script>

<textarea
  class="w-longtext"
  aria-label={field.title}
  aria-invalid={error ? 'true' : undefined}
  rows={rows}
  spellcheck="false"
  value={text}
  oninput={(e) => onChange(e.currentTarget.value)}
></textarea>

<style>
  .w-longtext {
    width: 100%;
    padding: 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
    line-height: 1.55;
    resize: vertical;
  }

  .w-longtext[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }
</style>
