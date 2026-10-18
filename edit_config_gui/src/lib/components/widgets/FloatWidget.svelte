<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const step = $derived(field.step ?? 0.1);

  // 与 IntWidget 同样的取舍：编辑中不改写，change 时才夹取上报，首次渲染不夹取。
  // threshold 是 0.5 秒这种小数量级，默认步长给 0.1。
  // 同 IntWidget：初值刻意只取一次，后续由 $effect 同步
  const initialText = (): string => (value == null ? '' : String(value));

  let text = $state(initialText());
  let seen = initialText();

  $effect(() => {
    const next = String(value ?? '');
    if (next !== seen) {
      seen = next;
      text = next;
    }
  });

  function commit(e: Event): void {
    const el = e.currentTarget as HTMLInputElement;
    const raw = el.value.trim();
    const n = Number(raw);

    if (raw === '' || !Number.isFinite(n)) {
      el.value = String(value ?? '');
      text = el.value;
      return;
    }

    let v = n;
    if (field.min !== undefined && v < field.min) v = field.min;
    if (field.max !== undefined && v > field.max) v = field.max;

    text = String(v);
    seen = String(v);
    el.value = text;

    onChange(field.type === 'string' ? String(v) : v);
  }
</script>

<input
  class="w-mono"
  type="number"
  {step}
  min={field.min}
  max={field.max}
  aria-label={field.title}
  aria-invalid={error ? 'true' : undefined}
  value={text}
  oninput={(e) => (text = e.currentTarget.value)}
  onchange={commit}
/>

<style>
  .w-mono {
    width: 100%;
    box-sizing: border-box;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
    font-variant-numeric: tabular-nums;
  }

  .w-mono[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }
</style>
