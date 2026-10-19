/**
 * 系统主题状态：Windows 现在是深色还是浅色、主题色是什么。
 *
 * 为什么是轮询注册表而不是监听事件：Windows 改主题会广播 `WM_SETTINGCHANGE`，
 * 但那条消息要由窗口过程接收才拿得到，WebView2 里的 JS 听不见；Tauri 也没给
 * 「系统主题变了」的事件。注册表读取是一对 `RegGetValueW`，3 秒一次的成本远低于
 * 一次文件 IO，用轮询换来的好处是用户改完设置后几乎立刻能看到界面变色。
 *
 * 为什么不用 `prefers-color-scheme`：那个媒体查询跟随的是 WebView2 自己的主题
 * 来源，在 Tauri 里不保证等于「设置 → 个性化 → 颜色 → 应用模式」。深色一律以
 * 这里读到的布尔值为准，浏览器里预览（`pnpm dev`）才退回媒体查询。
 */

import { bridge } from '../../bridge.ts';
import { DEFAULT_ACCENT, pickAccent, themeCss } from '../theme.ts';

/** 令牌 <style> 的 id。用 id 查而不是缓存节点：重复 start / 热重载时不会留下两份。 */
const STYLE_ID = 'ecg-m3-tokens';
const POLL_MS = 3000;

let dark = $state(false);
let accent = $state(DEFAULT_ACCENT);
/** 是否已经拿到过一次真实外观（失败也算：失败后走媒体查询兜底） */
let ready = $state(false);

let timer: ReturnType<typeof setInterval> | null = null;
let lastCss = '';
let inFlight = false;
let mediaBound = false;

/** 把当前状态落到 DOM：`color-scheme`（决定 light-dark() 取哪套）+ 令牌 CSS。 */
function apply(): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  // 内联 style 优先于样式表里的 `:root { color-scheme: light dark }`（m3 令牌里那条）
  root.style.colorScheme = dark ? 'dark' : 'light';
  // 类名是给「确实需要按深浅色分支」的样式用的；令牌本身已经全部由 color-scheme 驱动
  root.classList.toggle('ecg-dark', dark);

  const css = themeCss(accent);
  if (css === lastCss) return;
  lastCss = css;

  let el = document.getElementById(STYLE_ID);
  if (el === null) {
    el = document.createElement('style');
    el.id = STYLE_ID;
    document.head.append(el);
  }
  el.textContent = css;
}

/** 浏览器里预览 UI 时的兜底：跟随媒体查询，种子用默认蓝。 */
function followMedia(): void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  dark = query.matches;
  accent = DEFAULT_ACCENT;
  if (mediaBound) return;
  mediaBound = true;
  query.addEventListener?.('change', (event) => {
    // 只有读不到注册表时才走在媒体查询上；能读到注册表时这条监听不生效也没关系，
    // 因为 refresh() 的成功分支会把 dark 覆盖回真实值。
    if (!ready || inFlight) return;
    dark = event.matches;
    apply();
  });
}

async function refresh(): Promise<void> {
  // 上一次还没回来就跳过：轮询没必要排队，重叠只会让 IPC 越积越多
  if (inFlight) return;
  inFlight = true;
  try {
    const appearance = await bridge.systemAppearance();
    dark = appearance.dark;
    accent = pickAccent(appearance.accents);
  } catch {
    // 不在 Tauri 窗口里（浏览器预览、jsdom 测试）：退回媒体查询，界面仍然能用
    followMedia();
  } finally {
    inFlight = false;
    ready = true;
    apply();
  }
}

function onFocus(): void {
  // 用户从「设置」切回来时通常已经改完了，立刻问一次比等下一轮轮询更跟手
  void refresh();
}

function start(): void {
  if (timer !== null) return;
  apply();
  void refresh();
  timer = setInterval(() => {
    // 窗口在后台时没必要轮询：用户看不见，主题改了也不会漏——回到前台有 focus 兜底
    if (!document.hidden) void refresh();
  }, POLL_MS);
  window.addEventListener('focus', onFocus);
}

function stop(): void {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
  window.removeEventListener('focus', onFocus);
}

export const themeStore = {
  /** 当前是否深色 */
  isDark: (): boolean => dark,
  /** 当前种子色（`#rrggbb`），生成的整套配色由它决定 */
  accent: (): string => accent,
  /** 是否已经拿到过一次外观（首帧可能仍是默认值） */
  ready: (): boolean => ready,
  start,
  stop,
  refresh,
  /** 仅测试用：清掉定时器、类名和注入的 <style> */
  __resetForTest(): void {
    stop();
    dark = false;
    accent = DEFAULT_ACCENT;
    ready = false;
    lastCss = '';
    inFlight = false;
    mediaBound = false;
    if (typeof document !== 'undefined') {
      document.documentElement.classList.remove('ecg-dark');
      document.getElementById(STYLE_ID)?.remove();
    }
  },
};
