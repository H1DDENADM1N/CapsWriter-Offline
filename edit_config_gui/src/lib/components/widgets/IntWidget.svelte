<script lang="ts">
  import { TextFieldOutlined } from 'm3-svelte';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  // 输入过程中不改写用户正在打的字：只在 change（失焦/回车）时才夹取并上报。
  // 首次渲染也**不**夹取既有值——磁盘上本来就可能存着超范围的历史值
  // （比如有人手改过 config.toml），一打开就被静默改成别的数字是数据损坏。
  // 放在闭包里取初值：直接在 $state(...) 里写 value 会被编译器判成
  // 「只捕获初始值」的可疑写法并给出 state_referenced_locally 警告；
  // 这里就是**刻意**只取一次的初值，后续变化由下面的 $effect 同步。
  const initialText = (): string => (value == null ? '' : String(value));

  let text = $state(initialText());
  let seen = initialText();

  $effect(() => {
    const next = String(value ?? '');
    if (next !== seen) {
      seen = next;
      text = next;
    }
  });

  function commit(e: Event): void {
    const el = e.currentTarget as HTMLInputElement;
    const raw = el.value.trim();
    const n = Number(raw);

    if (raw === '' || !Number.isFinite(n)) {
      // 清空或打了非数字：还原显示，不上报任何值
      el.value = String(value ?? '');
      text = el.value;
      return;
    }

    let v = Math.trunc(n);
    if (field.min !== undefined && v < field.min) v = field.min;
    if (field.max !== undefined && v > field.max) v = field.max;

    text = String(v);
    seen = String(v);
    el.value = text;

    // start_music_volume / speech_recognition_port 这类键在 TOML 里是字符串，
    // 必须按原类型写回，否则 core_*.py 读到整数会抛类型错误
    onChange(field.type === 'string' ? String(v) : v);
  }
</script>

<!-- type=number 保留原生步进与 spinbutton 语义；m3 的 outlined 只负责外观 -->
<div class="w-num">
  <TextFieldOutlined
    label=""
    type="number"
    step="1"
    min={field.min}
    max={field.max}
    inputmode="numeric"
    aria-label={field.title}
    error={Boolean(error)}
    aria-invalid={error ? 'true' : undefined}
    value={text}
    oninput={(e) => (text = e.currentTarget.value)}
    onchange={commit}
  />
</div>

<style>
  .w-num {
    width: 100%;
    min-width: 0;
  }

  .w-num :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-num :global(input) {
    padding: 0 12px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
</style>
