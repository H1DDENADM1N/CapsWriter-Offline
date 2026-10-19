<script lang="ts">
  import { Button, TextFieldOutlined } from 'm3-svelte';
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
  <div class="field">
    <TextFieldOutlined
      label=""
      type="text"
      aria-label={field.title}
      error={Boolean(error)}
      aria-invalid={error ? 'true' : undefined}
      value={text}
      spellcheck="false"
      oninput={(e) => onChange(e.currentTarget.value)}
    />
  </div>
  <Button
    variant={recording ? 'filled' : 'tonal'}
    size="s"
    aria-label={recording ? '取消录制' : '录制快捷键'}
    onclick={start}
  >
    {recording ? '按任意键…' : '录制'}
  </Button>
  {#if recording}
    <span class="hint">按 Esc 取消</span>
  {/if}
</div>

<style>
  .w-hotkey {
    display: flex;
    gap: 8px;
    align-items: center;
    width: 100%;
    min-width: 0;
  }

  /* 基数为 0：输入框吃掉按钮与提示文字之外的全部空间 */
  .field {
    flex: 1 1 0;
    min-width: 0;
  }

  .w-hotkey :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-hotkey :global(input) {
    padding: 0 12px;
    font-size: 13px;
    font-family: var(--ecg-mono);
  }

  /* 录制中把边框切成主题色，用户一眼能看出「现在按的键会被吃掉」 */
  .recording .field :global(.m3-container .layer) {
    border-color: var(--ecg-accent);
    border-width: 2px;
  }

  /* 上面那条 .m3-container 规则也命中 Button，会把按钮撑成整行宽、把输入框挤没 */
  .w-hotkey :global(button.m3-container) {
    flex: 0 0 auto;
    width: auto;
    height: 40px;
  }

  .hint {
    color: var(--ecg-muted);
    font-size: 12px;
    white-space: nowrap;
  }
</style>
