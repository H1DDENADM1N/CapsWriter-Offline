<script lang="ts">
  import { bridge } from '../../../bridge.ts';
  import { configStore } from '../../stores/config.svelte.ts';
  import Icon from '../Icon.svelte';

  /**
   * 「关于」页不放任何可写配置——它只解释这个程序是什么、去哪提问题、当前改的是哪个文件。
   *
   * 链接全部经 Rust 的 `open_url` 打开（只放行 https://）：在 WebView 里直接
   * `window.open` 会被 Tauri 拦掉，而给一个「能打开任意本地程序」的通道又没必要。
   */
  const LINKS = [
    {
      label: '项目主页',
      note: '源码、更新日志与完整使用说明',
      url: 'https://github.com/H1DDENADM1N/CapsWriter-Offline',
    },
    {
      label: '提交问题',
      note: '遇到报错或配置项含义不清，在这里反馈',
      url: 'https://github.com/H1DDENADM1N/CapsWriter-Offline/issues',
    },
    {
      label: '下载发布版',
      note: '打包好的 exe 与模型文件',
      url: 'https://github.com/H1DDENADM1N/CapsWriter-Offline/releases',
    },
  ];

  const CAPABILITIES = [
    '覆盖 config.toml 的全部配置项，包括服务端、客户端、AI 服务商、提示词与快捷键。',
    '写入前先预览 diff；确认后原子替换，原文件自动备份为 config.toml.bak。',
    '写盘后回读校验，文件被别的程序改过会先报冲突，不会覆盖别人的修改。',
    '按「模型路径」页解析派生键的占位符，只读展示真实生效值，避免两处各写一份。',
  ];

  let opening = $state<string | null>(null);
  let error = $state('');

  async function open(url: string): Promise<void> {
    if (opening) return;
    opening = url;
    error = '';
    try {
      await bridge.openUrl(url);
    } catch (e) {
      error = `打开链接失败：${String(e)}`;
    } finally {
      opening = null;
    }
  }

  const configPath = $derived(configStore.path() ?? '（尚未打开）');
</script>

<article class="about">
  <section class="hero">
    <div class="mark" aria-hidden="true">C</div>
    <div class="intro">
      <h2>配置编辑器</h2>
      <p class="tagline">
        CapsWriter-Offline 的图形化配置工具 —— 安全地改写服务端与客户端共用的
        <code>config.toml</code>
      </p>
      <p class="meta">Tauri 2 + Svelte 5 · 写入基于 Rust <code>toml_edit</code></p>
    </div>
  </section>

  <section>
    <h3>它能做什么</h3>
    <ul class="facts">
      {#each CAPABILITIES as item (item)}
        <li>{item}</li>
      {/each}
    </ul>
  </section>

  <section>
    <h3>项目主页</h3>
    <div class="links">
      {#each LINKS as link (link.url)}
        <button
          type="button"
          class="link"
          disabled={opening !== null}
          onclick={() => void open(link.url)}
        >
          <span class="link-main">
            <span class="link-label">
              {link.label}
              <Icon name="link" size={13} />
            </span>
            <span class="link-note">{link.note}</span>
            <code class="link-url">{link.url}</code>
          </span>
        </button>
      {/each}
    </div>
    {#if error}
      <p class="error">{error}</p>
    {/if}
  </section>

  <section>
    <h3>当前配置</h3>
    <dl class="kv">
      <dt>文件</dt>
      <dd><code>{configPath}</code></dd>
      <dt>备份</dt>
      <dd>每次保存前，旧内容会写到同目录的 <code>config.toml.bak</code></dd>
      <dt>生效方式</dt>
      <dd>保存后需重启对应的服务端 / 客户端进程才会读取新配置</dd>
    </dl>
  </section>

  <section>
    <h3>快捷键</h3>
    <dl class="kv">
      <dt><kbd>Ctrl</kbd> + <kbd>K</kbd></dt>
      <dd>全局搜索配置项（支持中文标题、键名、拼音全拼与首字母）</dd>
      <dt><kbd>Ctrl</kbd> + <kbd>S</kbd></dt>
      <dd>预览并保存改动</dd>
      <dt><kbd>Esc</kbd></dt>
      <dd>关闭搜索面板或确认对话框</dd>
    </dl>
  </section>
</article>

<style>
  .about {
    display: flex;
    flex-direction: column;
    gap: 22px;
    width: 100%;
    padding: 20px 26px 80px;
  }

  section > h3 {
    margin: 0 0 10px;
    font-size: 13px;
    font-weight: 600;
    color: var(--ecg-muted-strong, #4b5563);
    letter-spacing: 0.02em;
  }

  .hero {
    display: flex;
    align-items: flex-start;
    gap: 16px;
  }

  .mark {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    width: 46px;
    height: 46px;
    border-radius: 12px;
    background: var(--ecg-accent, #1a56c4);
    color: #fff;
    font-size: 22px;
    font-weight: 700;
  }

  .intro h2 {
    margin: 0 0 4px;
    font-size: 18px;
    font-weight: 600;
  }

  .tagline {
    margin: 0 0 6px;
    color: var(--ecg-fg, #1c1f23);
    font-size: 13px;
    line-height: 1.7;
  }

  .meta {
    margin: 0;
    color: var(--ecg-muted, #888);
    font-size: 12px;
  }

  .facts {
    margin: 0;
    padding-left: 18px;
    color: var(--ecg-fg, #1c1f23);
    font-size: 13px;
    line-height: 1.85;
  }

  .links {
    display: grid;
    gap: 8px;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  }

  .link {
    display: block;
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 8px;
    background: var(--ecg-input-bg, #fff);
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .link:hover:not(:disabled) {
    border-color: var(--ecg-accent, #1a56c4);
  }

  .link:disabled {
    opacity: 0.6;
    cursor: default;
  }

  .link-main {
    display: flex;
    flex-direction: column;
    gap: 3px;
    /*
     * 没有这一行，`.link-url` 的 `white-space: nowrap` 会把卡片的最小内容宽度
     * 撑到整条 URL 那么长，网格只能排下两列、第三张孤零零掉到第二行。
     * 置 0 之后省略号才真的生效。
     */
    min-width: 0;
  }

  .link-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 600;
    color: var(--ecg-accent, #1a56c4);
  }

  .link-note {
    color: var(--ecg-muted, #888);
    font-size: 12px;
    line-height: 1.6;
  }

  .link-url {
    overflow: hidden;
    min-width: 0;
    color: var(--ecg-muted, #888);
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .kv {
    display: grid;
    gap: 8px 16px;
    grid-template-columns: max-content 1fr;
    margin: 0;
    font-size: 13px;
    line-height: 1.7;
  }

  .kv dt {
    color: var(--ecg-muted-strong, #4b5563);
    white-space: nowrap;
  }

  .kv dd {
    min-width: 0;
    margin: 0;
    overflow-wrap: anywhere;
  }

  code {
    padding: 1px 4px;
    border-radius: 4px;
    background: var(--ecg-hover, #f3f4f7);
    font-family: var(--ecg-mono, ui-monospace, Consolas, monospace);
    font-size: 12px;
  }

  kbd {
    padding: 1px 5px;
    border: 1px solid var(--ecg-border, #dcdfe6);
    border-radius: 4px;
    background: var(--ecg-hover, #f3f4f7);
    font-family: inherit;
    font-size: 11px;
  }

  .error {
    margin: 8px 0 0;
    color: var(--ecg-danger, #d33);
    font-size: 12px;
  }
</style>
