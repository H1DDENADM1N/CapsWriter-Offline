<script lang="ts">
  import { TextFieldOutlined } from 'm3-svelte';
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

<div class="w-num">
  <TextFieldOutlined
    label=""
    type="number"
    {step}
    min={field.min}
    max={field.max}
    inputmode="decimal"
    aria-label={field.title}
    error={Boolean(error)}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    oninput={(e) => (text = e.currentTarget.value)}
    onchange={commit}
  />
</div>

<style>
  .w-num {
    width: 100%;
    min-width: 0;
  }

  .w-num :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-num :global(input) {
    padding: 0 12px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
</style>
