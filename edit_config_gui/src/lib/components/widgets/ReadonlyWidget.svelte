<script lang="ts">
  import { Button } from 'm3-svelte';
  import { configStore } from '../../stores/config.svelte.ts';
  import { navStore } from '../../stores/nav.svelte.ts';
  import { fieldById, fieldId } from '../../schema/index.ts';
  import type { JsonValue } from '../../schema/types.ts';
  import type { WidgetProps } from './props.ts';

  let { field }: WidgetProps = $props();

  /**
   * 这 16 个键的值长这样：`${model_paths.funasr_llm_path}`。
   * 全仓没有任何代码解析这种占位符——`util/config.py:249-308` 的
   * FunASRArgs / SenseVoiceArgs / ParaformerArgs 直接读 `model_paths` 段。
   * 所以这里显示的是**真实生效值**，TOML 里那串占位符只作为「不参与读取」的
   * 存在保留在文件里，既不显示成可编辑内容，也永不写回（写回会让配置分叉）。
   */
  const source = $derived(field.derivedFrom ?? null);

  const resolved = $derived.by((): JsonValue | undefined => {
    if (!source) return undefined;
    return configStore.values()[fieldId(source)];
  });

  const sourceTitle = $derived.by(() => {
    if (!source) return '模型路径';
    return fieldById(fieldId(source))?.title ?? source.join('.');
  });

  const shown = $derived(resolved == null || resolved === '' ? '（未设置）' : String(resolved));

  const placeholder = $derived(
    Array.isArray(configStore.doc()?.fields)
      ? (() => {
          const hit = configStore.doc()!.fields.find((f) => fieldId(f.segments) === fieldId(field.segments));
          return hit ? String(hit.value) : '';
        })()
      : '',
  );
</script>

<div class="w-readonly">
  <code class="value" title={shown}>{shown}</code>
  {#if source}
    <Button variant="tonal" size="xs" onclick={() => navStore.focus(source)}>
      跳转到「{sourceTitle}」
    </Button>
  {/if}
  <p class="note">
    此项由「{sourceTitle}」决定，改那里立即生效；本文件里的值为占位符（
    <code>{placeholder}</code>），不参与读取。
  </p>
</div>

<style>
  .w-readonly {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    width: 100%;
    min-width: 0;
  }

  /* 只读值用虚线框 + 只读底色，和可编辑的描边输入框一眼区分开 */
  .value {
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    padding: 8px 10px;
    border: 1px dashed var(--m3c-outline-variant);
    border-radius: var(--m3-shape-small);
    background: var(--ecg-readonly-bg);
    color: var(--ecg-muted-strong);
    font-family: var(--ecg-mono);
    font-size: 12px;
    overflow-wrap: anywhere;
  }

  .w-readonly :global(button.m3-container) {
    height: 32px;
  }

  .note {
    flex-basis: 100%;
    margin: 0;
    color: var(--ecg-muted);
    font-size: 12px;
    line-height: 1.55;
  }

  .note code {
    font-family: var(--ecg-mono);
  }
</style>
