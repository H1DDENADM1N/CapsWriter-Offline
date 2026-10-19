<script lang="ts">
  import { TextFieldOutlinedMultiline } from 'm3-svelte';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  const text = $derived(value == null ? '' : String(value));

  // 只有这 8 段提示词正文是多行键（config.toml 里本来就用 """ 包着）。
  // 单行键必须走 TextWidget：toml_edit 遇到含 \n 的单行键会自动升格成 """ 多行，
  // 那是格式改写，不是用户预期的编辑（见规格 §9.5）。
</script>

<div class="w-longtext">
  <TextFieldOutlinedMultiline
    label=""
    aria-label={field.title}
    error={Boolean(error)}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    spellcheck="false"
    oninput={(e) => onChange(e.currentTarget.value)}
  />
</div>

<style>
  .w-longtext {
    width: 100%;
    min-width: 0;
  }

  /* m3 的多行框会按内容自动长高（内部 scrollHeight），所以这里只需要给一个
     下限防止空内容时塌成一条线；上限压住超长提示词，避免把整页顶走。 */
  .w-longtext :global(.m3-container) {
    width: 100%;
    min-width: 0;
    min-height: 96px;
    max-height: 480px;
  }

  .w-longtext :global(textarea) {
    padding: 12px;
    font-size: 13px;
    line-height: 1.6;
  }
</style>
