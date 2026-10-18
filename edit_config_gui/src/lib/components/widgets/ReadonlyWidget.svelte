<script lang="ts">
  import { configStore } from '../../stores/config.svelte.ts';
  import { navStore } from '../../stores/nav.svelte.ts';
  import { fieldById, fieldId } from '../../schema/index.ts';
  import type { JsonValue } from '../../schema/types.ts';
  import type { WidgetProps } from './props.ts';

  let { field }: WidgetProps = $props();

  /**
   * 这 9 个键的值长这样：`${model_paths.funasr_llm_path}`。
   * 全仓没有任何代码解析这种占位符——`util/config.py:241-278` 的
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
    <button type="button" onclick={() => navStore.focus(source)}>跳转到「{sourceTitle}」</button>
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
  }

  .value {
    padding: 5px 8px;
    border: 1px dashed var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-readonly-bg, #f4f5f7);
    color: var(--ecg-muted-strong, #555);
    font-family: var(--ecg-mono, ui-monospace, Consolas, monospace);
    font-size: 12px;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    overflow-wrap: anywhere;
  }

  button {
    padding: 5px 10px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: transparent;
    color: var(--ecg-accent, #3b82f6);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
  }

  .note {
    flex-basis: 100%;
    margin: 0;
    color: var(--ecg-muted, #888);
    font-size: 12px;
  }

  .note code {
    font-family: var(--ecg-mono, ui-monospace, Consolas, monospace);
  }
</style>
