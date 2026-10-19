<script lang="ts">
  import { Button, TextFieldOutlined } from 'm3-svelte';
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

<div class="w-list" class:invalid={Boolean(error)}>
  {#if rows.length === 0}
    <p class="empty">暂未添加</p>
  {:else}
    {#each rows as row, i (i)}
      <div class="row">
        <div class="field">
          <TextFieldOutlined
            label=""
            type="text"
            aria-label={`${field.title} 第 ${i + 1} 项`}
            error={Boolean(error)}
            value={row}
            spellcheck="false"
            oninput={(e) => setId(i, e.currentTarget.value)}
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
  <Button variant="tonal" size="s" onclick={() => emit([...rows, ''])}>添加一项</Button>
</div>

<style>
  .w-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
    width: 100%;
    min-width: 0;
  }

  .row {
    display: flex;
    gap: 8px;
    align-items: center;
    width: 100%;
    min-width: 0;
  }

  /* 基数为 0：输入框吃掉删除按钮之外的全部空间 */
  .field {
    flex: 1 1 0;
    min-width: 0;
  }

  .w-list :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-list :global(input) {
    padding: 0 12px;
    font-size: 13px;
    font-family: var(--ecg-mono);
  }

  /* 上面那条也命中 Button，不恢复自适应宽度会把输入框挤成 0 宽 */
  .w-list :global(button.m3-container) {
    flex: 0 0 auto;
    width: auto;
    height: 40px;
    white-space: nowrap;
  }

  .empty {
    margin: 0;
    color: var(--ecg-muted);
    font-size: 13px;
  }
</style>
