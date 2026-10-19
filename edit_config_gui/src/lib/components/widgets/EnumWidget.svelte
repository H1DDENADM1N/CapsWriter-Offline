<script lang="ts">
  import { SelectOutlined } from 'm3-svelte';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const text = $derived(value == null ? '' : String(value));

  // label 与真实值可以不同（如日志级别 TRACE=5、model 的 FunASR/Fun-ASR-Nano）
  const options = $derived(field.options ?? []);

  // 磁盘上的值不在候选里时照样要能显示出来，否则下拉框会静默显示成第一项，
  // 用户以为配置变了，实际上没变
  const hasCurrent = $derived(options.some((o) => o.value === text));

  // SelectOutlined 的 options 是普通数组，动态加一项即可；兜底项放最前面，
  // 和原来原生 <select> 的顺序一致
  const shownOptions = $derived.by(() => {
    const list = options.map((o) => ({ value: o.value, text: o.label }));
    if (!hasCurrent && text !== '') {
      list.unshift({ value: text, text: `${text}（当前值，不在候选内）` });
    }
    return list;
  });

  /*
   * 只挂 onchange 不够：键盘上下键改选中项时，Chromium 要等到失焦才派发 change，
   * 用户会在一段时间里既看不到「已修改」标记、也看不到底部保存条，以为没生效。
   * input 事件是立即派发的，两个都挂上；同一个值重复上报在 store 里是幂等的。
   */
</script>

<div class="w-enum" class:invalid={Boolean(error)}>
  <SelectOutlined
    label=""
    width="100%"
    options={shownOptions}
    aria-label={field.title}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    oninput={(e) => onChange(e.currentTarget.value)}
    onchange={(e) => onChange(e.currentTarget.value)}
  />
</div>

<style>
  .w-enum {
    width: 100%;
    min-width: 0;
  }

  .w-enum :global(.m3-container) {
    width: 100%;
    min-width: 0;
  }

  /* SelectOutlined 的容器高度走 --m3-density（3.5rem），在密集表单里偏高；
     这里显式定 40px，和同行的文本框、按钮落在同一条基线上。 */
  .w-enum :global(select) {
    height: 40px;
    padding-inline: 12px;
    font-size: 13px;
  }

  /* SelectOutlined 没有 error 属性，错误态只能由外层给边框上色；
     多带一层 .m3-container 是为了压过组件自带的 focus-within 规则 */
  .w-enum.invalid :global(.m3-container .layer) {
    border-color: var(--ecg-danger);
  }
</style>
