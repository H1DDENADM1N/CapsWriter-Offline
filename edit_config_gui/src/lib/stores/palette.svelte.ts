/**
 * 命令面板的可变状态。
 *
 * 放在 store 而不是组件里，是为了三件事共用同一份状态：`App.svelte` 的全局
 * `Ctrl+F`、`DiffDialog` 打开时的屏蔽、以及测试（直接驱动 store，不必挂载面板）。
 *
 * `recent` 只在内存里：不落盘、不读 localStorage。这是一份「这次打开改过什么」
 * 的临时清单，落盘会带来「上个月搜的密钥名字还留在列表里」这类意外。
 */

const RECENT_MAX = 8;

let open = $state(false);
let query = $state('');
let selectedIndex = $state(0);
let recent = $state<string[]>([]);

export const paletteStore = {
  open: (): boolean => open,
  query: (): string => query,
  selectedIndex: (): number => selectedIndex,
  recent: (): string[] => recent,

  show(): void {
    open = true;
    query = '';
    selectedIndex = 0;
  },

  hide(): void {
    open = false;
    query = '';
    selectedIndex = 0;
  },

  setQuery(q: string): void {
    query = q;
    // 查询一变，旧的下标指向别的东西了
    selectedIndex = 0;
  },

  move(delta: number, count: number): void {
    if (count <= 0) {
      selectedIndex = 0;
      return;
    }
    // 越界回卷：在最后一项再按 ↓ 应该回到第一项，而不是卡住
    selectedIndex = (selectedIndex + delta + count) % count;
  },

  setIndex(i: number, count: number): void {
    if (count <= 0) {
      selectedIndex = 0;
      return;
    }
    selectedIndex = Math.min(Math.max(i, 0), count - 1);
  },

  pushRecent(id: string): void {
    recent = [id, ...recent.filter((x) => x !== id)].slice(0, RECENT_MAX);
  },

  __resetForTest(): void {
    open = false;
    query = '';
    selectedIndex = 0;
    recent = [];
  },
};
