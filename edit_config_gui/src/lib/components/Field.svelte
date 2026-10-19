<script lang="ts">
  import { fieldId } from '../schema/index.ts';
  import type { FieldMeta } from '../schema/types.ts';
  import { configStore } from '../stores/config.svelte.ts';
  import { navStore } from '../stores/nav.svelte.ts';
  import { widgetFor } from './widgets/index.ts';

  let { field }: { field: FieldMeta } = $props();

  const id = $derived(fieldId(field.segments));
  const value = $derived(configStore.values()[id]);
  const error = $derived(configStore.errorOf(id));
  const dirty = $derived(configStore.dirtyIds().has(id));

  let row = $state<HTMLDivElement | null>(null);

  /**
   * 本行是不是「刚被跳到的目标」。高亮由 `navStore` 在 1.5s 后自己清掉，
   * 所以这个类会自动消失，不需要在这里管定时器。
   *
   * 一定要用它来挂 `.flash`，不能 `classList.add()`：本行的 `class` 属性里有
   * `class:wide` / `class:bool` 两个动态指令，Svelte 会在后续更新时整串重写
   * class 属性，手加上的类会被抹掉（真机上表现为「闪一下都没有」）。
   */
  const flashing = $derived(navStore.highlight() === id && navStore.pulse() > 0);

  /**
   * 跳转定位：搜索结果与只读键的「跳转到『…』」都走 `navStore.focus()`，
   * 由这里把目标行滚进视野。
   *
   * 为什么读 `pulse()` 而不只读 `highlight()`：连着跳同一项时 highlight
   * 的值不变，`$effect` 不会重跑，滚动就停在上一轮。
   */
  $effect(() => {
    const pulse = navStore.pulse();
    const target = navStore.highlight();
    const node = row;

    if (!node || pulse === 0 || target !== id) return;

    // 滚动用 smooth，但尊重系统「减少动画」设置
    const reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    node.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
  });

  /**
   * 显隐用 `{#if}` 而不是 CSS `display:none`：被藏起来的输入框仍能被 Tab 聚焦、
   * 仍会被读屏软件念出来，用户会对着一个看不见的控件打字。
   */
  const visible = $derived.by(() => {
    const w = field.visibleWhen;
    if (!w) return true;

    const current = configStore.values()[fieldId(w.segments)];
    if (w.equals !== undefined) return current === w.equals;
    if (w.in !== undefined) return w.in.includes(current as never);
    return true;
  });

  /*
   * 只读派生键的「来源 + 跳转」由 ReadonlyWidget 负责：它知道真实生效值长什么样、
   * 也知道占位符不该被当成内容。Field 这里不再重复画一遍，否则同一行会出现两个
   * 语义相同的跳转按钮。
   */
</script>

{#if visible}
  {@const Widget = widgetFor(field.widget)}

  <div class="field" bind:this={row} class:wide={field.widget === 'longText' || field.widget === 'dynamicTable'} class:bool={field.widget === 'bool'} class:flash={flashing}>
    <div class="label">
      <span class="row">
        <span class="title">{field.title}</span>
        {#if dirty}
          <span class="dirty">已修改</span>
        {/if}
      </span>
      {#if field.note}
        <p class="note">{field.note}</p>
      {/if}
    </div>

    <div class="control">
      <Widget {field} {value} {error} onChange={(v) => configStore.setValue(id, v)} />
    </div>

    {#if error}
      <p class="error">{error}</p>
    {/if}
  </div>
{/if}

<style>
  /*
   * 两列：标签占剩余空间，控件列贴住内容区右边缘。
   *
   * 控件列用 clamp 而不是百分比或 1fr：纯百分比在 2560 宽的窗口上会把下拉框
   * 拉到一千多像素，纯 1fr 又会把控件挤到标签旁边、右边留一大片空白。clamp 让
   * 它在窄窗口下仍有 320px 可用、宽窗口下最多 620px，且**永远右对齐**——
   * 每一行的输入框右边缘都落在同一条竖线上，右边不会再有空档。
   */
  .field {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(320px, 52%, 620px);
    gap: 4px 20px;
    padding: 8px 0;
    border-bottom: 1px solid var(--m3c-outline-variant);
    align-items: center;
  }

  .field:last-child {
    border-bottom: none;
  }

  /*
   * 跳转后的那一次闪烁：只改背景与描边，不做位移和缩放。
   * 一来「移一下」会把正在读的行推走，二来系统开了「减少动画」时
   * 颜色过渡仍然保留，用户还是能看出跳到了哪一行。
   */
  @keyframes ecg-jump-flash {
    0% {
      background-color: color-mix(in oklab, var(--m3c-primary) 0%, transparent);
      box-shadow: 0 0 0 2px color-mix(in oklab, var(--m3c-primary) 55%, transparent);
    }

    16% {
      background-color: color-mix(in oklab, var(--m3c-primary) 16%, transparent);
      box-shadow: 0 0 0 2px color-mix(in oklab, var(--m3c-primary) 70%, transparent);
    }

    100% {
      background-color: color-mix(in oklab, var(--m3c-primary) 0%, transparent);
      box-shadow: 0 0 0 2px transparent;
    }
  }

  /*
   * 这个类由模板上的 `class:flash={flashing}` 挂上去，编译器看得见，
   * 所以能写成普通选择器（不用 :global，也不会被判成未使用的选择器）。
   * 动画只播一次就停：`flashing` 为真期间类一直挂着，1.4s 后动画自然结束；
   * `navStore` 在 1.5s 后清掉 highlight，类随之消失，下次跳转重新开始。
   */
  .field.flash {
    animation: ecg-jump-flash 1.4s ease-out;
    border-radius: var(--m3-shape-small, 8px);
  }

  .field.wide {
    grid-template-columns: 1fr;
    gap: 8px;
    align-items: start;
  }

  .label {
    min-width: 0;
    /* 说明文字不要跟着宽窗口拉成一整行，读起来会串行 */
    max-width: 46em;
  }

  .row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  /* titleSmall：13px/500，是 MD3 表单里字段标签的层级 */
  .title {
    font-size: 13px;
    font-weight: 500;
    line-height: 20px;
    color: var(--m3c-on-surface);
  }

  /* 脏标记用胶囊：它是一枚状态徽章，不该和标签正文争抢注意力 */
  .dirty {
    padding: 2px 8px;
    border-radius: var(--m3-shape-full);
    background: var(--ecg-tag-bg);
    color: var(--ecg-tag-fg);
    font-size: 11px;
    font-weight: 500;
    line-height: 16px;
    white-space: nowrap;
  }

  .note {
    margin: 4px 0 0;
    color: var(--m3c-on-surface-variant);
    font-size: 12px;
    line-height: 1.55;
    white-space: pre-line;
  }

  .control {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-width: 0;
    /* 输入框容器高度由各控件自己压到 40px（app.css 的 --m3-density 只是兜住
       m3 组件的默认高度）；浮动标签的底色要跟行底色一致，否则空 label 会在边框上留一块色斑 */
    --m3v-background: var(--m3c-surface);
  }

  /* m3 的 outlined 输入框总会渲染一个浮动 label；这里标题由左列提供，
     label 传的是空串。空的 label 仍带 4px 左右内边距，会遮住顶部边框一小段，
     看起来像描边断了个口子，所以直接不渲染它（无障碍名由 aria-label 提供）。 */
  .control :global(.m3-container > label) {
    display: none;
  }

  /* 开关本身没有宽度可拉伸，靠右放，右边缘才和别的控件对齐 */
  .field.bool .control {
    align-items: flex-end;
  }

  .error {
    grid-column: 1 / -1;
    margin: 4px 0 0;
    color: var(--ecg-danger);
    font-size: 12px;
    line-height: 1.5;
  }

  @media (max-width: 760px) {
    .field {
      grid-template-columns: 1fr;
    }

    .field.bool .control {
      align-items: flex-start;
    }
  }
</style>
