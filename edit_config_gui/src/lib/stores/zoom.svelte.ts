/**
 * 页面缩放。
 *
 * 缩放是「这个人怎么用这台机器」的观看状态，和 config.toml 无关，所以不写盘；
 * 每次打开都从 100% 开始，也就没有「上次缩放留在 200%、一开机以为界面坏了」这类问题。
 *
 * 三处入口共用同一份状态：键盘（Ctrl+= / Ctrl+- / Ctrl+0）、Ctrl+滚轮、
 * 顶栏的「还原」按钮。缩放本身交给 Rust 的 `set_zoom`（webview 缩放），
 * 不用 CSS `zoom`——后者不参与媒体查询与 `vw`/`vh` 计算，缩到 125% 时断点行为会和
 * 浏览器里不一致。
 */

import { bridge } from '../../bridge.ts';

/** 档位。两端都是「还能看」的极限：50% 仍能读清 13px 正文，200% 仍能点开下拉。 */
export const ZOOM_STEPS = [0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2] as const;

export const DEFAULT_ZOOM = 1;

/** 一次滚轮手势里连续事件的合并窗口（毫秒）。触控板会一次手势连发几十个 wheel。 */
const WHEEL_THROTTLE_MS = 100;

/**
 * 取下一个档位。
 *
 * 当前值不在档位上（例如未来从别处设进来 1.05）时，按大小关系落到相邻档，
 * 而不是回退到 100%——否则「放大」按键会让页面突然变小。
 */
export function nextZoom(current: number, dir: 1 | -1): number {
  if (dir > 0) {
    for (const step of ZOOM_STEPS) {
      if (step > current + 1e-6) return step;
    }
    return ZOOM_STEPS[ZOOM_STEPS.length - 1];
  }
  for (let i = ZOOM_STEPS.length - 1; i >= 0; i -= 1) {
    if (ZOOM_STEPS[i] < current - 1e-6) return ZOOM_STEPS[i];
  }
  return ZOOM_STEPS[0];
}

/** 顶栏上显示的百分比：整数，四舍五入到能看清的程度（0.67 → 67%） */
export function zoomPercent(scale: number): number {
  return Math.round(scale * 100);
}

let zoom = $state(DEFAULT_ZOOM);
let started = false;
let lastWheel = 0;

/**
 * 把比例交给 webview。
 *
 * 失败只影响「这一下有没有真的缩」，不影响状态机：`bridge` 在浏览器里
 * （jsdom、`pnpm dev`）会直接抛「不在 Tauri 窗口中」，那里本来就没得缩，
 * 让它冒到上层会把整个应用搞崩。
 */
function pushZoom(next: number): void {
  try {
    void bridge.setZoom(next).catch(() => {
      /* 非 Tauri 环境没有这个命令，忽略 */
    });
  } catch {
    /* 同上：同步抛出的 ensureTauri 也吞掉 */
  }
}

function set(next: number): void {
  const value = Math.round(next * 100) / 100;
  if (value === zoom) return;
  zoom = value;
  pushZoom(value);
}

export const zoomStore = {
  current: (): number => zoom,
  percent: (): number => zoomPercent(zoom),
  isDefault: (): boolean => Math.abs(zoom - DEFAULT_ZOOM) < 1e-6,

  zoomIn(): void {
    set(nextZoom(zoom, 1));
  },

  zoomOut(): void {
    set(nextZoom(zoom, -1));
  },

  reset(): void {
    set(DEFAULT_ZOOM);
  },

  /**
   * 装上全局监听。幂等：`main.ts` 在挂载前调用一次。
   *
   * 滚轮必须用 `passive: false`：Chromium 对 window 级 wheel 默认走 passive，
   * 那样 `preventDefault()` 不生效，页面在缩放的同时还会滚动。
   */
  start(): void {
    if (started || typeof window === 'undefined') return;
    started = true;

    window.addEventListener('keydown', (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      // 小键盘与主键盘上的加号在 key 里分别是 '+' 与 '='，两个都收
      if (e.key === '=' || e.key === '+') {
        e.preventDefault();
        zoomStore.zoomIn();
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        zoomStore.zoomOut();
      } else if (e.key === '0') {
        e.preventDefault();
        zoomStore.reset();
      }
    });

    window.addEventListener(
      'wheel',
      (e: WheelEvent) => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        const now = Date.now();
        if (now - lastWheel < WHEEL_THROTTLE_MS) return;
        lastWheel = now;
        // 双指捏合在 Chromium 里也是带 ctrlKey 的 wheel，方向以 deltaY 为准
        if (e.deltaY < 0) zoomStore.zoomIn();
        else if (e.deltaY > 0) zoomStore.zoomOut();
      },
      { passive: false },
    );
  },

  __resetForTest(): void {
    zoom = DEFAULT_ZOOM;
    lastWheel = 0;
  },
};
