/**
 * 翻页键的判定逻辑（纯函数，便于测试）。
 *
 * 这里只回答两个问题：**这个键要滚多远**，以及**现在该不该接管它**。
 * 真正的滚动动作留在 `App.svelte`，因为只有它拿着滚动容器的引用。
 */

/** 方向键一次滚动的距离。80px ≈ 三行正文，够看清「刚才停在哪一行」。 */
export const ARROW_SCROLL = 80;

/** 翻页按一屏的 90% 滚：留一条重叠带，跨页时不会漏掉停在边界上的那一行。 */
export const PAGE_RATIO = 0.9;

/**
 * 这个键对应滚动多少像素；不是翻页键则返回 null。
 *
 * @param viewportHeight 滚动容器的可视高度（`clientHeight`）
 */
export function scrollDeltaForKey(key: string, viewportHeight: number): number | null {
  const page = Math.max(0, viewportHeight) * PAGE_RATIO;
  switch (key) {
    case 'PageDown':
      return page;
    case 'PageUp':
      return -page;
    case 'ArrowDown':
      return ARROW_SCROLL;
    case 'ArrowUp':
      return -ARROW_SCROLL;
    default:
      return null;
  }
}

const TEXT_INPUT_TYPES = new Set([
  'text',
  'search',
  'password',
  'number',
  'email',
  'url',
  'tel',
  'date',
  'datetime-local',
  'month',
  'week',
  'time',
]);

/**
 * 焦点是否落在「方向键另有含义」的地方。
 *
 * 输入框里 ↑/↓ 要移动光标、`<select>` 里要换选项、可编辑区域里要挪行——
 * 这些场景下抢走按键，用户会以为程序卡了。按钮不在其列：按钮上的方向键
 * 本来就什么也不做。
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== 'object') return false;
  const el = target as {
    tagName?: string;
    type?: string;
    isContentEditable?: boolean;
  };
  const tag = (el.tagName ?? '').toLowerCase();
  if (tag === 'textarea' || tag === 'select') return true;
  if (tag === 'input') {
    // checkbox / radio 的方向键同样没有默认行为，但一律让开更省心：
    // 漏接管只会少滚一下，接管错了会吞掉表单里的方向键
    return TEXT_INPUT_TYPES.has((el.type ?? 'text').toLowerCase()) || !el.type;
  }
  return el.isContentEditable === true;
}

/** 滚动容器只要这两样东西，测试里就不用造一个真 DOM 节点 */
export interface ScrollTarget {
  clientHeight: number;
  scrollBy(options: { top: number }): void;
}

/** 一次按键里与滚动有关的部分，方便测试直接构造 */
export interface ScrollKeyEvent {
  key: string;
  target: EventTarget | null;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  preventDefault(): void;
}

/**
 * 处理一次翻页键，返回是否接管了。
 *
 * @param modalOpen 是否有对话框/命令面板占着屏幕（它们要自己用方向键）
 */
export function applyScrollKey(
  e: ScrollKeyEvent,
  scroller: ScrollTarget | null,
  modalOpen: boolean,
): boolean {
  // 修饰键按下的方向键多半是快捷键的一部分（Ctrl+↑ 之类），不当翻页用
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  if (!scroller) return false;
  if (modalOpen) return false;
  if (isTypingTarget(e.target)) return false;

  const delta = scrollDeltaForKey(e.key, scroller.clientHeight);
  if (delta === null) return false;

  e.preventDefault();
  scroller.scrollBy({ top: delta });
  return true;
}
