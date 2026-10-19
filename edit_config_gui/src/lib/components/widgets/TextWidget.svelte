<script lang="ts">
  import { TextFieldOutlined } from 'm3-svelte';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const text = $derived(value == null ? '' : String(value));
</script>

<!--
  字段标题已经在 Field 的左侧标签列展示，这里不再给 m3 输入框传 label，
  否则同一行会出现两遍标题；无障碍名称仍由 aria-label 提供。
  值仍以「受控」方式回传：输入 → onChange → store → value → text。
-->
<div class="w-text">
  <TextFieldOutlined
    label=""
    type="text"
    aria-label={field.title}
    title={text}
    error={Boolean(error)}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    oninput={(e) => onChange(e.currentTarget.value)}
  />
</div>

<style>
  /*
   * m3 的 outlined 输入框自带 56px 高、15rem 最小宽，是按移动端触摸目标做的。
   * 这里是密集表单，统一压到 40px 并把宽度交给字段栅格决定；否则每个输入框
   * 都自己撑一个最小宽度，窄窗口下会把两列布局顶坏。
   */
  .w-text {
    width: 100%;
    min-width: 0;
  }

  .w-text :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-text :global(input) {
    padding: 0 12px;
    font-size: 13px;
  }
</style>
