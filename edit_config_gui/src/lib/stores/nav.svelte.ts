/**
 * 导航状态：当前页 + 「跳到某个字段」的高亮。
 *
 * 抽出来是为了让三个使用方共用同一份状态，而不是各自 `document.querySelector`：
 * `Sidebar`（切页）、`CommandPalette`（搜索后跳转）、`ReadonlyWidget`
 * （派生只读键 →「去改真正生效的那个键」）。
 */

import { fieldId, pageOfSegments, pages } from '../schema/index.ts';

let current = $state(pages[0]?.id ?? 'server');
let highlight = $state<string | null>(null);

/**
 * 每次 `focus()` 自增的计数器。
 *
 * 高亮本身是个字符串：连着两次跳同一项时它的值不变，`$effect` 不会重跑，
 * 于是「再闪一次」不成立。计数器把「又跳了一次」这个事件单独表达出来，
 * 消费方（`Field`）靠它重播滚动与闪烁动画。
 */
let pulse = $state(0);

/**
 * 高亮持续时间。
 *
 * 1.5 秒是「肉眼能跟上、又不至于挡着看」的折中；太短会以为没跳，太长下一跳会打架。
 */
const HIGHLIGHT_MS = 1500;

let timer: ReturnType<typeof setTimeout> | null = null;

function clearHighlightTimer(): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

export const navStore = {
  current: (): string => current,

  highlight: (): string | null => highlight,

  /** 跳转事件计数：每 `focus()` 一次 +1，见 `pulse` 变量的注释 */
  pulse: (): number => pulse,

  /** 切页并清掉残留高亮（用户主动切页时不该还亮着上一页的字段） */
  go(id: string): void {
    clearHighlightTimer();
    current = id;
    highlight = null;
  },

  /**
   * 切到该字段所在的页并高亮 1.5 秒。
   *
   * 页 id 必须靠 `pageOfSegments` 反查而不能用 `segments[0]` 猜：`server`/`client`
   * 恰好与页 id 同名，但 `client.zhipuai` 属于 `aiProviders` 页、
   * `client.prompt_style` 属于 `promptStyles` 页，靠段名猜会跳错页。
   *
   * 还要先 `clearTimeout`：连续两次 `focus()`（搜索结果连着点两下）时，
   * 上一次的定时器会把新的高亮提前清掉，表现为「第二次搜索没高亮」。
   */
  focus(segments: string[]): void {
    const page = pageOfSegments(segments);
    if (page) current = page.id;

    clearHighlightTimer();
    highlight = fieldId(segments);
    pulse += 1;
    timer = setTimeout(() => {
      highlight = null;
      timer = null;
    }, HIGHLIGHT_MS);
  },

  /** 仅测试用：把状态清回初始页，避免用例之间互相污染 */
  __resetForTest(): void {
    clearHighlightTimer();
    current = pages[0]?.id ?? 'server';
    highlight = null;
    pulse = 0;
  },
};
