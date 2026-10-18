<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const checked = $derived(Boolean(value));
</script>

<input
  class="w-bool"
  type="checkbox"
  aria-label={field.title}
  aria-invalid={error ? 'true' : undefined}
  checked={checked}
  onchange={(e) => onChange(e.currentTarget.checked)}
/>

<style>
  .w-bool {
    width: 18px;
    height: 18px;
    accent-color: var(--ecg-accent, #3b82f6);
    cursor: pointer;
  }

  .w-bool[aria-invalid='true'] {
    outline: 1px solid var(--ecg-danger, #d33);
    outline-offset: 1px;
  }
</style>
