<script lang="ts">
  /**
   * 保存确认对话框。
   *
   * 这个对话框存在的唯一理由是「让人看见将要发生什么」：展示 unified diff、
   * 列出只警告不阻断的问题（模型文件缺失之类），确认后才允许写盘。
   *
   * 四个非常驻状态各有自己的按钮组：
   * - conflict：磁盘被外部改过 → 只有「重新加载」与「强制覆盖」两条路，
   *   不提供「取消并继续用内存值保存」，那等于掩饰一次数据竞争；
   * - committing：写盘中，禁掉一切交互（连 Esc 也不响应，避免用户以为取消了、
   *   实际 ReplaceFileW 已经发生）；
   * - done：告知备份路径 —— 这是用户唯一的后悔药入口；
   * - failed：原样显示后端文案（Rust 的错误消息带文件名和失败原因）。
   */
  import { Button, Divider, LoadingIndicator } from 'm3-svelte';

  import { saveStore } from '../stores/save.svelte.ts';

  const phase = $derived(saveStore.phase());

  /** idle / previewing 不占屏幕：预览是毫秒级动作，闪一下遮罩反而碍眼 */
  const open = $derived(
    phase.kind === 'confirm' ||
      phase.kind === 'committing' ||
      phase.kind === 'conflict' ||
      phase.kind === 'done' ||
      phase.kind === 'failed',
  );

  const closable = $derived(phase.kind !== 'committing');

  const diffLines = $derived(
    phase.kind === 'confirm' ? phase.result.diff.replace(/\n$/, '').split('\n') : [],
  );

  /**
   * 行首标记决定底色。`+++` / `---` 是文件头、`@@` 是 hunk 头，都不能当成
   * 增删行来染色——否则 diff 的第一行永远是绿的，看多了就没人信这个颜色。
   */
  function lineKind(line: string): string {
    if (line.startsWith('+++') || line.startsWith('---')) return 'meta';
    if (line.startsWith('@@')) return 'hunk';
    if (line.startsWith('+')) return 'add';
    if (line.startsWith('-')) return 'del';
    return '';
  }

  function close(): void {
    if (closable) saveStore.cancel();
  }

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }

  function onBackdrop(e: MouseEvent): void {
    if (e.target === e.currentTarget) close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
  <div class="backdrop" role="presentation" onclick={onBackdrop}>
    <!--
      继续用自定义遮罩 + 面板，而不是 m3 `Dialog`：Dialog 自带居中、进出场动画与
      焦点陷阱，会和这里的窗口级 Esc、`e.target === e.currentTarget` 的遮罩点击
      关闭语义抢事件（尤其在 committing 态，Esc 是被刻意禁掉的）。
    -->
    <div
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="save-dialog-title"
      tabindex="-1"
    >
      {#if phase.kind === 'confirm'}
        <h2 id="save-dialog-title">确认保存</h2>
        <Divider />
        <p class="lead">以下改动将写入 config.toml（原文件会备份为 .bak）：</p>
        <section class="diff" aria-label="配置差异">
          {#each diffLines as line, i (i)}
            <div class="ln {lineKind(line)}">{line || ' '}</div>
          {/each}
        </section>

        {#if phase.result.warnings.length > 0}
          <div class="warn">
            <p class="warn-title">以下问题只警告，不阻止保存：</p>
            <ul>
              {#each phase.result.warnings as w (w.segments.join('\u0000'))}
                <li>{w.message}</li>
              {/each}
            </ul>
          </div>
        {/if}

        <div class="actions">
          <Button variant="text" onclick={close}>取消</Button>
          <Button variant="filled" onclick={() => void saveStore.confirm(false)}>
            写入文件
          </Button>
        </div>
      {:else if phase.kind === 'committing'}
        <h2 id="save-dialog-title">正在写入…</h2>
        <Divider />
        <div class="committing">
          <LoadingIndicator size={36} aria-label="正在写入配置文件" />
          <p class="lead">正在替换 config.toml，请勿关闭窗口。</p>
        </div>
      {:else if phase.kind === 'conflict'}
        <h2 id="save-dialog-title">配置文件已被外部修改</h2>
        <Divider />
        <p class="lead">
          磁盘上的 config.toml 在你打开之后被改过（可能是 config_selector、其它编辑器
          或上一次会话）。为了避免覆盖别人的改动，这次保存没有执行。
        </p>
        <div class="actions">
          <Button variant="text" onclick={close}>取消</Button>
          <Button variant="tonal" onclick={() => void saveStore.reloadAndReset()}>
            重新加载（丢弃我的改动）
          </Button>
          <!--
            危险操作用 MD3 的 filled 按钮形状，但把 primary 这组令牌在按钮内部
            改指向 error 色：比写死一个红色背景更稳，hover/disabled 等状态仍由
            Button 自己算。
          -->
          <Button
            variant="filled"
            style="--m3c-primary: var(--ecg-danger); --m3c-on-primary: var(--m3c-on-error);"
            onclick={() => void saveStore.confirm(true)}
          >
            强制覆盖
          </Button>
        </div>
      {:else if phase.kind === 'done'}
        <h2 id="save-dialog-title">已保存</h2>
        <Divider />
        <p class="lead">
          配置已写入并通过回读校验。原文件备份在 <code>{phase.backupPath}</code>。
        </p>
        <p class="lead muted">重启相关的服务进程后新配置才会生效。</p>
        <div class="actions">
          <Button variant="filled" onclick={close}>关闭</Button>
        </div>
      {:else if phase.kind === 'failed'}
        <h2 id="save-dialog-title">保存失败</h2>
        <Divider />
        <p class="lead">config.toml 没有被改动。原始错误：</p>
        <pre class="error">{phase.error}</pre>
        <div class="actions">
          <Button variant="text" onclick={close}>关闭</Button>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: color-mix(in oklab, var(--m3c-scrim) 32%, transparent);
    z-index: 40;
  }

  /* MD3 对话框：28px 圆角、24px 内边距、surface-container-high + elevation-3 */
  .dialog {
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: min(760px, 100%);
    max-height: 100%;
    padding: 24px;
    border-radius: var(--m3-shape-extra-large);
    background: var(--m3c-surface-container-high);
    box-shadow: var(--m3-elevation-3);
    overflow: auto;
  }

  h2 {
    margin: 0;
    color: var(--m3c-on-surface);
    font-size: 24px;
    font-weight: 400;
    line-height: 1.33;
  }

  .lead {
    margin: 0;
    color: var(--m3c-on-surface-variant);
    font-size: 14px;
    line-height: 1.7;
  }

  .muted {
    color: var(--ecg-muted);
  }

  code {
    padding: 1px 6px;
    border-radius: var(--m3-shape-extra-small);
    background: var(--ecg-hover);
    font-family: var(--ecg-mono);
  }

  /* diff 是这屏的主角：等宽、紧凑、行与行之间不留缝，才看得出真正的增删 */
  .diff {
    flex: 1 1 auto;
    min-height: 120px;
    max-height: 46vh;
    padding: 8px 0;
    overflow: auto;
    border: 1px solid var(--m3c-outline-variant);
    border-radius: var(--m3-shape-medium);
    background: var(--m3c-surface-container);
    font-family: var(--ecg-mono);
    font-size: 12px;
    line-height: 1.55;
  }

  .ln {
    padding: 0 16px;
    white-space: pre;
  }

  .ln.add {
    background: var(--ecg-add-bg);
  }

  .ln.del {
    background: var(--ecg-del-bg);
  }

  .ln.hunk {
    color: var(--ecg-hunk-fg);
  }

  .ln.meta {
    color: var(--ecg-muted);
  }

  .error {
    max-height: 30vh;
    margin: 0;
    padding: 12px 16px;
    overflow: auto;
    border: 1px solid color-mix(in oklab, var(--ecg-danger) 35%, transparent);
    border-radius: var(--m3-shape-medium);
    background: color-mix(in oklab, var(--ecg-danger) 10%, transparent);
    color: var(--ecg-danger);
    font-family: var(--ecg-mono);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
  }

  .warn {
    padding: 12px 16px;
    border: 1px solid color-mix(in oklab, var(--ecg-warn) 30%, transparent);
    border-radius: var(--m3-shape-medium);
    background: var(--ecg-warn-bg);
    color: var(--ecg-warn-fg);
    font-size: 12px;
  }

  .warn-title {
    margin: 0 0 4px;
  }

  .warn ul {
    margin: 0;
    padding-left: 20px;
  }

  .committing {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .committing .lead {
    flex: 1 1 auto;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }

  /* 按钮高度固定成 MD3 的 2.5rem（40px，等于 --m3-density 的 s 号按钮），
     保证同一行里的实心/描边按钮高低完全一致。 */
  .actions :global(.m3-container) {
    height: 40px;
  }
</style>
