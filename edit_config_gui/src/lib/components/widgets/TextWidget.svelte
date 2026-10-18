<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const text = $derived(value == null ? '' : String(value));
</script>

<input
  class="w-text"
  type="text"
  aria-label={field.title}
  aria-invalid={error ? 'true' : undefined}
  value={text}
  oninput={(e) => onChange(e.currentTarget.value)}
/>

<style>
  .w-text {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
  }

  .w-text[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }
</style>
