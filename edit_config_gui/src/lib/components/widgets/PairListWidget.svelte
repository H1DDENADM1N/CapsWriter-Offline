<script lang="ts">
  import { Button, TextFieldOutlined } from 'm3-svelte';
  import type { JsonValue } from '../../schema/types.ts';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  interface Entry {
    name: string;
    delay: string;
  }

  /**
   * `enter_apps` 的结构是 `[["进程名", 延迟秒数], ...]`。
   * 延迟用字符串存：输入过程中 `0.` 这种半成品不该被 `Number()` 抹成 0。
   */
  const read = (v: JsonValue | undefined): Entry[] => {
    if (!Array.isArray(v)) return [];
    return (v as JsonValue[]).map((p) => {
      const pair = p as JsonValue[];
      return { name: String(pair?.[0] ?? ''), delay: String(pair?.[1] ?? '') };
    });
  };

  // 初值刻意只取一次（后续变化由下面的 $effect 同步）
  const initial = (): Entry[] => read(value);

  let rows = $state<Entry[]>(initial());
  let seen = JSON.stringify(initial());

  $effect(() => {
    const next = read(value);
    const key = JSON.stringify(next);
    if (key !== seen) {
      seen = key;
      rows = next;
    }
  });

  function emit(next: Entry[]): void {
    rows = next;
    // 进程名留空的行整行丢弃，延迟非法时回落到 0（上游对 0 的处理是「不延迟」）
    const real = next
      .filter((r) => r.name.trim() !== '')
      .map((r) => [r.name.trim(), Number(r.delay) || 0] as [string, number]);
    seen = JSON.stringify(read(real as unknown as JsonValue));
    onChange(real as unknown as JsonValue);
  }

  function patch(i: number, part: Partial<Entry>): void {
    emit(rows.map((r, j) => (j === i ? { ...r, ...part } : r)));
  }
</script>

<div class="w-pairs" class:invalid={Boolean(error)}>
  {#if rows.length === 0}
    <p class="empty">暂未添加</p>
  {:else}
    <div class="row head">
      <span>进程名</span>
      <span>延迟（秒）</span>
      <span></span>
    </div>
    {#each rows as row, i (i)}
      <div class="row">
        <div class="field">
          <TextFieldOutlined
            label=""
            type="text"
            aria-label={`进程名 第 ${i + 1} 项`}
            placeholder="happ.exe"
            error={Boolean(error)}
            value={row.name}
            spellcheck="false"
            oninput={(e) => patch(i, { name: e.currentTarget.value })}
          />
        </div>
        <div class="field delay">
          <TextFieldOutlined
            label=""
            type="number"
            min="0"
            step="0.1"
            inputmode="decimal"
            aria-label={`延迟 第 ${i + 1} 项`}
            error={Boolean(error)}
            value={row.delay}
            oninput={(e) => patch(i, { delay: e.currentTarget.value })}
          />
        </div>
        <Button
          variant="text"
          size="s"
          aria-label={`删除第 ${i + 1} 项`}
          style="color: var(--ecg-danger)"
          onclick={() => emit(rows.filter((_, j) => j !== i))}
        >
          删除
        </Button>
      </div>
    {/each}
  {/if}
  <Button variant="tonal" size="s" onclick={() => emit([...rows, { name: '', delay: '0.5' }])}>
    添加一项
  </Button>
  <p class="note">进程名要和任务管理器里看到的一致（小写）；留空数组则不启用。</p>
</div>

<style>
  .w-pairs {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
    width: 100%;
    min-width: 0;
  }

  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 8em auto;
    gap: 8px;
    width: 100%;
    align-items: center;
  }

  .row.head {
    color: var(--ecg-muted);
    font-size: 12px;
  }

  .w-pairs :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-pairs :global(input) {
    padding: 0 12px;
    font-size: 13px;
  }

  /* 上面那条也命中 Button（同一套 m3-container 类），这里恢复自适应宽度 */
  .w-pairs :global(button.m3-container) {
    width: auto;
    height: 40px;
    white-space: nowrap;
  }

  .empty {
    margin: 0;
    color: var(--ecg-muted);
    font-size: 13px;
  }

  .note {
    margin: 0;
    color: var(--ecg-muted);
    font-size: 12px;
  }
</style>
