<script lang="ts">
  import { Button, TextFieldOutlined } from 'm3-svelte';
  import type { WidgetProps } from './props.ts';

  let { field, value, error, onChange }: WidgetProps = $props();

  // 明文只存在于这个 state 里；不进 title、不进 aria-label、不进任何日志
  let shown = $state(false);

  const text = $derived(value == null ? '' : String(value));
</script>

<div class="w-secret">
  <div class="field">
    <TextFieldOutlined
      label=""
      type={shown ? 'text' : 'password'}
      aria-label={field.title}
      error={Boolean(error)}
      aria-invalid={error ? 'true' : undefined}
      value={text}
      autocomplete="off"
      spellcheck="false"
      oninput={(e) => onChange(e.currentTarget.value)}
    />
  </div>
  <!-- 可见文案保持「显示 / 隐藏」，读屏名称带上宾语说明点的是什么 -->
  <Button
    variant="text"
    size="s"
    aria-label={shown ? '隐藏内容' : '显示内容'}
    title={shown ? '隐藏内容' : '显示内容'}
    onclick={() => (shown = !shown)}
  >
    {shown ? '隐藏' : '显示'}
  </Button>
</div>

<style>
  .w-secret {
    display: flex;
    gap: 8px;
    align-items: center;
    width: 100%;
    min-width: 0;
  }

  /* 基数为 0：输入框吃掉按钮之外的全部空间（m3 输入框里的 <input> 是绝对定位的，
     基数用 auto 会算成约 0 宽，整行就被按钮占满）。 */
  .field {
    flex: 1 1 0;
    min-width: 0;
  }

  .w-secret :global(.m3-container) {
    width: 100%;
    min-width: 0;
    height: 40px;
  }

  .w-secret :global(input) {
    padding: 0 12px;
    font-size: 13px;
    font-family: var(--ecg-mono);
  }

  /* 上面那条 .m3-container 规则同样命中 Button（它也带 m3-container 类），
     按钮会拿到 width:100% 把输入框挤成 0 宽；这里恢复自适应宽度，
     高度给 40px 是为了和输入框底边对齐（m3 的 s 号按钮主要靠 density 定高）。 */
  .w-secret :global(button.m3-container) {
    flex: 0 0 auto;
    width: auto;
    height: 40px;
  }
</style>
