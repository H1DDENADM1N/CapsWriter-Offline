<script lang="ts">
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  let recording = $state(false);
  let teardown: (() => void) | null = null;

  const text = $derived(value == null ? '' : String(value));

  /**
   * 浏览器按键名 → Python `keyboard` 的规范名。
   *
   * 两边名字并不一致，直接 `key.toLowerCase()` 会把方向键写成 `arrowup`、
   * 空格写成 `" "`、翻页写成 `pageup`，Rust 侧照着 `keyboard.parse_hotkey`
   * 一比一对拍（841 例零差异）会判它们非法。录出来的值要能直接被
   * `util/client/shortcut_handler.py` 解析，所以这里必须翻译。
   */
  const NAMED: Record<string, string> = {
    ' ': 'space',
    ArrowUp: 'up',
    ArrowDown: 'down',
    ArrowLeft: 'left',
    ArrowRight: 'right',
    PageUp: 'page up',
    PageDown: 'page down',
    Escape: 'esc',
    Enter: 'enter',
    Tab: 'tab',
    Backspace: 'backspace',
    Delete: 'delete',
    Home: 'home',
    End: 'end',
    Insert: 'insert',
    CapsLock: 'caps lock',
  };

  const MODIFIERS = new Set(['Control', 'Alt', 'Shift', 'Meta']);

  function comboOf(e: KeyboardEvent): string | null {
    // 只按下修饰键时不算录制完成，继续等真正的那个键
    if (MODIFIERS.has(e.key)) return null;

    const parts: string[] = [];
    if (e.ctrlKey) parts.push('ctrl');
    if (e.altKey) parts.push('alt');
    if (e.shiftKey) parts.push('shift');
    if (e.metaKey) parts.push('windows');

    const name = NAMED[e.key] ?? e.key.toLowerCase();
    if (!name) return null;

    parts.push(name);
    return parts.join(' + ');
  }

  function stop(): void {
    recording = false;
    teardown?.();
    teardown = null;
  }

  function start(): void {
    if (recording) {
      stop();
      return;
    }

    recording = true;

    // 监听器必须在 click 处理器里同步挂上，不能放进 $effect：
    // effect 是微任务，用户（和测试里的 fireEvent.keyDown）紧接着就按键，
    // 那时监听器还没注册，录不到任何东西。
    const onKey = (e: KeyboardEvent): void => {
      e.preventDefault();
      e.stopPropagation();

      // Esc 只退出录制，不写值——否则用户想取消时反而被写进一个 esc
      if (e.key === 'Escape') {
        stop();
        return;
      }

      const combo = comboOf(e);
      if (combo === null) return;

      onChange(combo);
      stop();
    };

    window.addEventListener('keydown', onKey, true);
    teardown = () => window.removeEventListener('keydown', onKey, true);
  }

  $effect(() => () => teardown?.());
</script>

<div class="w-hotkey" class:recording>
  <input
    type="text"
    aria-label={field.title}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    spellcheck="false"
    oninput={(e) => onChange(e.currentTarget.value)}
  />
  <button type="button" class="rec" aria-label={recording ? '取消录制' : '录制快捷键'} onclick={start}>
    {recording ? '按任意键…' : '录制'}
  </button>
  {#if recording}
    <span class="hint">按 Esc 取消</span>
  {/if}
</div>

<style>
  .w-hotkey {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .w-hotkey input {
    flex: 1 1 auto;
    width: 100%;
    min-width: 0;
    padding: 6px 8px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
  }

  .w-hotkey input[aria-invalid='true'] {
    border-color: var(--ecg-danger, #d33);
  }

  .w-hotkey.recording input {
    border-color: var(--ecg-accent, #3b82f6);
    box-shadow: 0 0 0 3px var(--ecg-accent-weak, #3b82f633);
  }

  .rec {
    padding: 6px 10px;
    border: 1px solid var(--ecg-border, #c8ccd4);
    border-radius: 6px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    white-space: nowrap;
  }

  .recording .rec {
    border-color: var(--ecg-accent, #3b82f6);
    color: var(--ecg-accent, #3b82f6);
  }

  .hint {
    color: var(--ecg-muted, #888);
    font-size: 12px;
    white-space: nowrap;
  }
</style>
