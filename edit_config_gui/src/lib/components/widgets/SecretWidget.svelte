<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  // 明文只存在于这个 state 里；不进 title、不进 aria-label、不进任何日志
  let shown = $state(false);

  const text = $derived(value == null ? '' : String(value));
</script>

<div class="w-secret">
  <input
    type={shown ? 'text' : 'password'}
    aria-label={field.title}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    autocomplete="off"
    spellcheck="false"
    oninput={(e) => onChange(e.currentTarget.value)}
  />
  <button
    type="button"
    class="eye"
    aria-label={shown ? '隐藏内容' : '显示内容'}
    title={shown ? '隐藏内容' : '显示内容'}
    onclick={() => (shown = !shown)}
  >
    {shown ? '隐藏' : '显示'}
  </button>
</div>

<style>
  .w-secret {
    display: flex;
    gap: 6px;
    align-items: stretch;
  }

  .w-secret input {
    flex: 1;
    min-width: 0;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
  }

  .w-secret input[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }

  .eye {
    padding: 0 10px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
  }
</style>
