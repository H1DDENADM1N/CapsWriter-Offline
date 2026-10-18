<script lang="ts">
  import type { JsonValue } from '../../schema/types.ts';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  /** 磁盘上的 `[""]` 和 `[]` 都表示「空列表」，界面上没有区别 */
  const read = (v: JsonValue | undefined): string[] => {
    const arr = Array.isArray(v) ? (v as JsonValue[]).map((x) => String(x)) : [];
    return arr.filter((s) => s !== '');
  };

  // 初值刻意只取一次（后续变化由下面的 $effect 同步），放进闭包避免
  // state_referenced_locally 警告
  const initial = (): string[] => read(value);

  let rows = $state<string[]>(initial());
  let seen = JSON.stringify(initial());

  $effect(() => {
    const next = read(value);
    const key = JSON.stringify(next);
    if (key !== seen) {
      seen = key;
      rows = next;
    }
  });

  /**
   * 上报时丢掉纯空白行：`disable_exe_list` 里的空串在 Rust 侧会被当成
   * 「匹配所有进程名」的陷阱（`util/check_process.py` 用 `in` 判断），
   * 保留一行空串比删掉它危险得多。
   */
  function emit(next: string[]): void {
    rows = next;
    const real = next.filter((s) => s.trim() !== '');
    seen = JSON.stringify(real);
    onChange(real);
  }

  function setId(i: number, v: string): void {
    emit(rows.map((r, j) => (j === i ? v : r)));
  }
</script>

<div class="w-list" class:invalid={error}>
  {#if rows.length === 0}
    <p class="empty">暂未添加</p>
  {:else}
    {#each rows as row, i (i)}
      <div class="row">
        <input
          type="text"
          aria-label={`${field.title} 第 ${i + 1} 项`}
          value={row}
          spellcheck="false"
          oninput={(e) => setId(i, e.currentTarget.value)}
        />
        <button type="button" aria-label={`删除第 ${i + 1} 项`} onclick={() => emit(rows.filter((_, j) => j !== i))}>
          删除
        </button>
      </div>
    {/each}
  {/if}
  <button type="button" class="add" onclick={() => emit([...rows, ''])}>添加一项</button>
</div>

<style>
  .w-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: flex-start;
  }

  .row {
    display: flex;
    gap: 6px;
    width: 100%;
  }

  .row input {
    flex: 1;
    min-width: 0;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
  }

  .invalid .row input {
    border-color: var(--ecg-danger, #d33);
  }

  button {
    padding: 6px 10px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    white-space: nowrap;
  }

  .empty {
    margin: 0;
    color: var(--ecg-muted, #888);
    font-size: 13px;
  }
</style>
