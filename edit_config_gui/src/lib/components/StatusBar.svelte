<script lang="ts">
  /**
   * 底部进程状态栏。
   *
   * 5 秒轮询检查服务端/客户端是否在跑：改完配置后最需要的信息是「我现在重启
   * 哪个进程才会生效」，而这个答案在配置文件里是看不出来的。
   *
   * 页面隐藏时停表：Tauri 窗口最小化后没人看这行字，继续每 5 秒枚举一次全系统
   * 进程纯属浪费（`sysinfo` 枚举在没有缓存的机器上要几十毫秒）。
   */
  import { onMount } from 'svelte';

  import { bridge } from '../../bridge.ts';
  import type { RunningInfo, ServiceTarget } from '../../bridge.ts';

  const POLL_MS = 5000;

  let info = $state<RunningInfo | null>(null);
  let pending = $state<ServiceTarget | null>(null);
  /** true 表示停在确认框里等用户点「以管理员权限重启」（restartService 返回 needsElevation）。 */
  let elevating = $state(false);
  let notice = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | null = null;

  async function refresh(): Promise<void> {
    try {
      const next = await bridge.runningProcesses();
      if (next) info = next;
    } catch {
      // 检测失败不该打断编辑：保留上一次结果，下一个周期再试
    }
  }

  function startPolling(): void {
    if (timer !== null) return;
    timer = setInterval(() => void refresh(), POLL_MS);
  }

  function stopPolling(): void {
    if (timer === null) return;
    clearInterval(timer);
    timer = null;
  }

  function onVisibility(): void {
    if (document.hidden) {
      stopPolling();
    } else {
      void refresh();
      startPolling();
    }
  }

  onMount(() => {
    void refresh();
    startPolling();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  });

  function targetLabel(target: ServiceTarget): string {
    return target === 'server' ? '服务端' : '客户端';
  }

  /** 降权启动失败（degraded）时的提示文案；两个阶段共用。 */
  function degradeNotice(target: ServiceTarget): string {
    return target === 'server'
      ? '未能以普通权限启动服务端，可能无法被客户端连接；请用非管理员方式启动服务端。'
      : '未能以普通权限启动客户端，可能无法输入到目标程序；请用非管理员方式启动客户端。';
  }

  function askRestart(target: ServiceTarget): void {
    pending = target;
    elevating = false;
  }

  function closeDialog(): void {
    pending = null;
    elevating = false;
  }

  async function doRestart(target: ServiceTarget): Promise<void> {
    notice = null;
    try {
      const outcome = await bridge.restartService(target);
      if (outcome?.needsElevation === true) {
        // 普通权限结束不了它：停在确认框里改走提权路径，尚未调用 restartServiceElevated
        elevating = true;
        return;
      }
      if (outcome?.degraded) notice = degradeNotice(target);
      closeDialog();
      await refresh();
    } catch (e) {
      closeDialog();
      notice = `重启失败：${typeof e === 'string' ? e : String(e)}`;
    }
  }

  async function doRestartElevated(target: ServiceTarget): Promise<void> {
    notice = null;
    try {
      const outcome = await bridge.restartServiceElevated(target);
      if (outcome?.degraded) notice = degradeNotice(target);
      closeDialog();
      await refresh();
    } catch (e) {
      closeDialog();
      notice = `重启失败：${typeof e === 'string' ? e : String(e)}`;
    }
  }
</script>

<footer class="status">
  <span
    class="dot"
    class:on={info?.server === true}
    class:admin={info?.server === true && info?.serverAdmin === true}
    aria-label={info?.server
      ? info?.serverAdmin === true
        ? '服务端以管理员权限运行'
        : '服务端运行中'
      : '服务端未运行'}
  ></span>
  <span class="label">服务端</span>
  <span
    class="dot"
    class:on={info?.client === true}
    class:admin={info?.client === true && info?.clientAdmin === true}
    aria-label={info?.client
      ? info?.clientAdmin === true
        ? '客户端以管理员权限运行'
        : '客户端运行中'
      : '客户端未运行'}
  ></span>
  <span class="label">客户端</span>
  {#if info?.isAdmin}
    <span class="tag">管理器以管理员身份运行</span>
  {/if}

  <span class="spacer"></span>

  {#if notice}
    <span class="notice">{notice}</span>
  {/if}

  {#if info?.server}
    <button type="button" onclick={() => askRestart('server')}>重启服务端</button>
  {/if}
  {#if info?.client}
    <button type="button" onclick={() => askRestart('client')}>重启客户端</button>
  {/if}
</footer>

{#if pending}
  {@const target = pending}
  <div class="backdrop" role="presentation">
    <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="restart-title">
      <h2 id="restart-title">
        {elevating
          ? `需要管理员权限重启${targetLabel(target)}`
          : `确认重启${targetLabel(target)}？`}
      </h2>
      {#if elevating}
        <p class="hint">
          结束{targetLabel(target)}需要管理员权限，下一步会弹出 UAC 确认；请在弹窗中允许后继续。
        </p>
        <div class="actions">
          <button type="button" onclick={closeDialog}>取消</button>
          <button type="button" class="primary" onclick={() => void doRestartElevated(target)}>
            以管理员权限重启
          </button>
        </div>
      {:else}
        <p>
          重启会中断正在进行的语音输入；如果此刻正在录音，这段语音会丢失。请确认当前没有在录音。
        </p>
        {#if !info?.isAdmin && (target === 'server' ? info?.serverAdmin : info?.clientAdmin) === true}
          <p class="hint">{targetLabel(target)}以管理员权限运行，重启需要提权（会弹出 UAC 确认）</p>
        {/if}
        <div class="actions">
          <button type="button" onclick={closeDialog}>取消</button>
          <button type="button" class="primary" onclick={() => void doRestart(target)}>
            确认重启
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .status {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
    padding: 6px 14px;
    border-top: 1px solid var(--ecg-border, #dcdfe6);
    background: var(--ecg-panel, #fafbfc);
    color: var(--ecg-muted, #666);
    font-size: 12px;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ecg-border, #b8bcc4);
  }

  .dot.on {
    background: var(--ecg-ok, #2f9e44);
  }

  /* 服务端/客户端以管理员权限运行时用紫色，与普通权限的绿色区分开 */
  .dot.admin {
    background: var(--ecg-elevated, #8e44ad);
  }

  .label + .dot {
    margin-left: 8px;
  }

  .tag {
    margin-left: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: var(--ecg-tag-bg, #fff3cd);
    color: var(--ecg-tag-fg, #7a5a00);
  }

  .spacer {
    flex: 1 1 auto;
  }

  .notice {
    max-width: 46ch;
    color: var(--ecg-warn, #8a6100);
    line-height: 1.5;
  }

  button {
    padding: 3px 10px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 4px;
    background: var(--ecg-bg, #fff);
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  .backdrop {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgb(0 0 0 / 32%);
    z-index: 50;
  }

  .dialog {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: min(460px, 92vw);
    padding: 18px 20px;
    border-radius: 10px;
    background: var(--ecg-bg, #fff);
    box-shadow: 0 18px 48px rgb(0 0 0 / 22%);
  }

  h2 {
    margin: 0;
    font-size: 15px;
  }

  p {
    margin: 0;
    color: var(--ecg-muted, #666);
    font-size: 12px;
    line-height: 1.8;
  }

  /* 提权相关提示比普通说明更需要被看见，借 notice 同一枚警示色 */
  .hint {
    color: var(--ecg-warn, #8a6100);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  .primary {
    border-color: var(--ecg-accent, #2f6feb);
    background: var(--ecg-accent, #2f6feb);
    color: #fff;
  }
</style>
