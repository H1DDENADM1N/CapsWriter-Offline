<script lang="ts">
  import { Button, TextFieldOutlined } from 'm3-svelte';
  import type { JsonValue } from '../../schema/types.ts';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  interface Entry {
    key: string;
    hotkey: string;
    name: string;
  }

  /**
   * `client.additional_special_apps` 是一张「进程名 → { hotkey, name }」的动态表。
   * 进程名是字典键、**大小写敏感精确匹配**（`pause_other_audio.py` 里
   * `if exe_name in special_apps_map`），所以这里绝不把键归一化成小写，
   * 只去掉首尾空白。
   */
  const read = (v: JsonValue | undefined): Entry[] => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return [];
    return Object.entries(v as Record<string, unknown>).map(([key, row]) => {
      const r = (row ?? {}) as Record<string, unknown>;
      return { key, hotkey: String(r.hotkey ?? ''), name: String(r.name ?? '') };
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

    const out: Record<string, { hotkey: string; name: string }> = {};
    for (const r of next) {
      const k = r.key.trim();
      if (!k) continue;
      out[k] = { hotkey: r.hotkey, name: r.name };
    }

    seen = JSON.stringify(read(out));
    // 上报「整表当前值」，由 buildPatches 与基线做差得出 tableRow / delete，
    // 绝不整表替换（那会抹掉每行的行尾注释）
    onChange(out);
  }

  function patch(i: number, part: Partial<Entry>): void {
    emit(rows.map((r, j) => (j === i ? { ...r, ...part } : r)));
  }

  const duplicates = $derived.by(() => {
    const seenKeys = new Set<string>();
    const dup = new Set<string>();
    for (const r of rows) {
      const k = r.key.trim();
      if (!k) continue;
      if (seenKeys.has(k)) dup.add(k);
      seenKeys.add(k);
    }
    return dup;
  });
</script>

<div class="w-table" class:invalid={Boolean(error)}>
  {#if rows.length === 0}
    <p class="empty">暂未添加</p>
  {:else}
    <div class="row head">
      <span>进程名</span>
      <span>全局快捷键</span>
      <span>显示名称</span>
      <span></span>
    </div>
    {#each rows as row, i (i)}
      <div class="row" class:dup={duplicates.has(row.key.trim())}>
        <TextFieldOutlined
          label=""
          type="text"
          aria-label={`进程名 第 ${i + 1} 项`}
          placeholder="vlc.exe"
          error={Boolean(error)}
          value={row.key}
          spellcheck="false"
          oninput={(e) => patch(i, { key: e.currentTarget.value })}
        />
        <TextFieldOutlined
          label=""
          type="text"
          aria-label={`快捷键 第 ${i + 1} 项`}
          placeholder="ctrl + alt + f9"
          error={Boolean(error)}
          value={row.hotkey}
          spellcheck="false"
          oninput={(e) => patch(i, { hotkey: e.currentTarget.value })}
        />
        <TextFieldOutlined
          label=""
          type="text"
          aria-label={`显示名称 第 ${i + 1} 项`}
          placeholder="VLC Media Player"
          error={Boolean(error)}
          value={row.name}
          oninput={(e) => patch(i, { name: e.currentTarget.value })}
        />
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

  <Button variant="tonal" size="s" onclick={() => emit([...rows, { key: '', hotkey: '', name: '' }])}>
    添加一行
  </Button>

  {#if duplicates.size > 0}
    <p class="warn">进程名重复：{Array.from(duplicates).join('、')}——保存时只会保留最后一行。</p>
  {/if}
</div>

<style>
  .w-table {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
    width: 100%;
    min-width: 0;
  }

  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 8px;
    width: 100%;
    align-items: center;
  }

  .row.head {
    color: var(--ecg-muted);
    font-size: 12px;
  }

  .w-table :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-table :global(input) {
    padding: 0 12px;
    font-size: 13px;
  }

  /* 上面那条也命中 Button（同一套 m3-container 类），这里恢复自适应宽度 */
  .w-table :global(button.m3-container) {
    width: auto;
    height: 40px;
    white-space: nowrap;
  }

  /* 重复的进程名保存时会互相覆盖，只把第一列染成警示色，提示落在出错的那格 */
  .row.dup :global(.m3-container .layer) {
    border-color: var(--ecg-warn);
  }

  .empty {
    margin: 0;
    color: var(--ecg-muted);
    font-size: 13px;
  }

  .warn {
    margin: 0;
    color: var(--ecg-warn);
    font-size: 12px;
  }
</style>
