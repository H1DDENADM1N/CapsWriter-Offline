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
  import { configStore } from '../stores/config.svelte.ts';
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
    <div
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="save-dialog-title"
      tabindex="-1"
    >
      {#if phase.kind === 'confirm'}
        <h2 id="save-dialog-title">确认保存</h2>
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
          <button type="button" onclick={close}>取消</button>
          <button type="button" class="primary" onclick={() => void saveStore.confirm(false)}>
            写入文件
          </button>
        </div>
      {:else if phase.kind === 'committing'}
        <h2 id="save-dialog-title">正在写入…</h2>
        <p class="lead">正在替换 config.toml，请勿关闭窗口。</p>
      {:else if phase.kind === 'conflict'}
        <h2 id="save-dialog-title">配置文件已被外部修改</h2>
        <p class="lead">
          磁盘上的 config.toml 在你打开之后被改过（可能是 config_selector、其它编辑器
          或上一次会话）。为了避免覆盖别人的改动，这次保存没有执行。
        </p>
        <div class="actions">
          <button type="button" onclick={close}>取消</button>
          <button type="button" onclick={() => void saveStore.reloadAndReset()}>
            重新加载（丢弃我的改动）
          </button>
          <button type="button" class="danger" onclick={() => void saveStore.confirm(true)}>
            强制覆盖
          </button>
        </div>
      {:else if phase.kind === 'done'}
        <h2 id="save-dialog-title">已保存</h2>
        <p class="lead">
          配置已写入并通过回读校验。原文件备份在 <code>{phase.backupPath}</code>。
        </p>
        <p class="lead muted">重启相关的服务进程后新配置才会生效。</p>
        <div class="actions">
          <button type="button" class="primary" onclick={close}>关闭</button>
        </div>
      {:else if phase.kind === 'failed'}
        <h2 id="save-dialog-title">保存失败</h2>
        <p class="lead">config.toml 没有被改动。原始错误：</p>
        <pre class="error">{phase.error}</pre>
        <div class="actions">
          <button type="button" onclick={close}>关闭</button>
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
    background: rgb(0 0 0 / 32%);
    z-index: 40;
  }

  .dialog {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: min(760px, 100%);
    max-height: 100%;
    padding: 18px 20px;
    border-radius: 10px;
    background: var(--ecg-bg, #fff);
    box-shadow: 0 18px 48px rgb(0 0 0 / 22%);
  }

  h2 {
    margin: 0;
    font-size: 15px;
  }

  .lead {
    margin: 0;
    color: var(--ecg-muted, #666);
    font-size: 12px;
    line-height: 1.7;
  }

  .muted {
    color: var(--ecg-muted, #888);
  }

  code {
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--ecg-hover, #f0f1f4);
    font-family: Consolas, 'Cascadia Mono', monospace;
  }

  .diff {
    flex: 1 1 auto;
    min-height: 120px;
    max-height: 46vh;
    padding: 8px 0;
    overflow: auto;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 6px;
    background: var(--ecg-panel, #fafbfc);
    font-family: Consolas, 'Cascadia Mono', monospace;
    font-size: 12px;
    line-height: 1.55;
  }

  .ln {
    padding: 0 12px;
    white-space: pre;
  }

  .ln.add {
    background: var(--ecg-add-bg, rgb(47 158 68 / 12%));
  }

  .ln.del {
    background: var(--ecg-del-bg, rgb(192 57 43 / 10%));
  }

  .ln.hunk {
    color: var(--ecg-hunk-fg, #7c5cbf);
  }

  .ln.meta {
    color: var(--ecg-muted, #888);
  }

  .error {
    max-height: 30vh;
    margin: 0;
    padding: 10px 12px;
    overflow: auto;
    border-radius: 6px;
    background: var(--ecg-hover, #f3f4f7);
    font-family: Consolas, 'Cascadia Mono', monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
  }

  .warn {
    padding: 8px 10px;
    border-radius: 6px;
    background: #fff8e6;
    color: #8a6100;
    font-size: 12px;
  }

  .warn-title {
    margin: 0 0 4px;
  }

  .warn ul {
    margin: 0;
    padding-left: 18px;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  button {
    padding: 6px 14px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 5px;
    background: var(--ecg-bg, #fff);
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  .primary {
    border-color: var(--ecg-accent, #2f6feb);
    background: var(--ecg-accent, #2f6feb);
    color: #fff;
  }

  .danger {
    border-color: var(--ecg-danger, #c0392b);
    background: var(--ecg-danger, #c0392b);
    color: #fff;
  }
</style>
