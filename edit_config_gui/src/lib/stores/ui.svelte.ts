/**
 * 纯界面状态（与配置内容无关、也不该进 config.toml 的东西）。
 *
 * 折叠状态存 localStorage：这个偏好属于「这个人怎么用这台机器」，不该写进
 * config.toml（那会被 config_selector 换配置时一起换掉），但要跨重启保留——
 * 否则每次打开都得再折一次。
 */

const KEY = 'ecg.sidebar.collapsed';

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    // 隐私模式 / 禁用存储时 localStorage 会抛；折叠与否不值得让应用起不来。
    return false;
  }
}

let collapsed = $state(loadCollapsed());

export const uiStore = {
  sidebarCollapsed: (): boolean => collapsed,

  toggleSidebar(): void {
    collapsed = !collapsed;
    try {
      localStorage.setItem(KEY, collapsed ? '1' : '0');
    } catch {
      /* 存不住就算了，本次会话内仍然生效 */
    }
  },

  /** 仅测试用：localStorage 在同一个 jsdom 里是跨用例共享的 */
  __resetForTest(): void {
    collapsed = false;
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  },
};
