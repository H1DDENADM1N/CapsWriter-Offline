/**
 * 右下角提示队列。
 *
 * 为什么不用 `window.alert`：保存流程里错误是「按字段」给出的，alert 只能一次性
 * 甩一整段文字，用户还得自己找是哪个输入框。真正的字段级反馈走
 * `configStore.errorOf()`，这里只负责「保存成功」「已复制路径」「重启失败」
 * 这类与具体字段无关的全局消息。
 */

export type ToastKind = 'info' | 'success' | 'warn' | 'error';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

/**
 * 各档位的自动消失时间（毫秒）。
 *
 * `error` 用 0 表示不自动消失：保存失败的提示往往要边看边改，几秒就没了会让人
 * 反复触发同一个错误。用户点掉或下次成功保存时才清。
 */
const DEFAULT_TTL: Record<ToastKind, number> = {
  info: 3000,
  success: 3000,
  warn: 6000,
  error: 0,
};

let items = $state<Toast[]>([]);
let seq = 0;
const timers = new Map<number, ReturnType<typeof setTimeout>>();

function dismiss(id: number): void {
  const t = timers.get(id);
  if (t !== undefined) {
    clearTimeout(t);
    timers.delete(id);
  }
  items = items.filter((x) => x.id !== id);
}

export const toast = {
  items: (): Toast[] => items,

  /** @param ttl 覆盖默认存活时间；传 0 表示常驻直到手动关闭 */
  push(kind: ToastKind, message: string, ttl?: number): number {
    const id = ++seq;
    items = [...items, { id, kind, message }];

    const ms = ttl ?? DEFAULT_TTL[kind];
    if (ms > 0) {
      timers.set(
        id,
        setTimeout(() => dismiss(id), ms),
      );
    }
    return id;
  },

  dismiss,

  clear(): void {
    for (const t of timers.values()) clearTimeout(t);
    timers.clear();
    items = [];
  },

  /** 仅测试用：清空队列并复位自增 id，让断言里的 id 可预测 */
  __resetForTest(): void {
    toast.clear();
    seq = 0;
  },
};
