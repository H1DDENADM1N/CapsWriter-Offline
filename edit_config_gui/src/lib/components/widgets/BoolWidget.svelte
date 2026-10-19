<script lang="ts">
  import { Switch } from 'm3-svelte';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const checked = $derived(Boolean(value));
</script>

<!-- m3 的 Switch 要求外层有 <label>（点击文字/轨道都能切换），这里只放轨道，
     标题仍由 Field 的标签列提供；aria-label 保证读屏能念出这是哪个开关。 -->
<label class="w-bool">
  <Switch
    checked={checked}
    aria-label={field.title}
    aria-invalid={error ? 'true' : undefined}
    onchange={(e) => onChange(e.currentTarget.checked)}
  />
</label>

<style>
  .w-bool {
    display: inline-flex;
    align-items: center;
    cursor: pointer;
  }

  /* checked 状态下 m3 的 `input:checked` 会把边框刷成主题色，盖掉全局的
     [aria-invalid] 错误边框；改成外圈描边，错误状态在任何开关状态下都可见。 */
  .w-bool :global(input[aria-invalid='true']) {
    outline: 2px solid var(--ecg-danger);
    outline-offset: 2px;
  }
</style>
