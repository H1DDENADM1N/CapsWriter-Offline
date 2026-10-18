<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const text = $derived(value == null ? '' : String(value));

  // label 与真实值可以不同（如日志级别 TRACE=5、model 的 FunASR/Fun-ASR-Nano）
  const options = $derived(field.options ?? []);

  // 磁盘上的值不在候选里时照样要能显示出来，否则下拉框会静默显示成第一项，
  // 用户以为配置变了，实际上没变
  const hasCurrent = $derived(options.some((o) => o.value === text));

  /*
   * 只挂 onchange 不够：键盘上下键改选中项时，Chromium 要等到失焦才派发 change，
   * 用户会在一段时间里既看不到「已修改」标记、也看不到底部保存条，以为没生效。
   * input 事件是立即派发的，两个都挂上；同一个值重复上报在 store 里是幂等的。
   */
</script>

<select
  class="w-enum"
  aria-label={field.title}
  aria-invalid={error ? 'true' : undefined}
  value={text}
  oninput={(e) => onChange(e.currentTarget.value)}
  onchange={(e) => onChange(e.currentTarget.value)}
>
  {#if !hasCurrent && text !== ''}
    <option value={text}>{text}（当前值，不在候选内）</option>
  {/if}
  {#each options as o (o.value)}
    <option value={o.value}>{o.label}</option>
  {/each}
</select>

<style>
  .w-enum {
    width: 100%;
    box-sizing: border-box;
    min-width: 12em;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  .w-enum[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }
</style>
