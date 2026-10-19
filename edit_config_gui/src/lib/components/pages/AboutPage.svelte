<script lang="ts">
  /*
   * 图标直接用 `src-tauri/icons/icon.ico`：它与仓库根的 `assets/icon/config-icon.ico`
   * 字节一致（SHA256 相同），也是 exe 与窗口的图标。再往 `src/assets` 拷一份的话，
   * 将来换图标必然漏掉其中一处——关于页显示旧图标比显示不出图标更难发现。
   * 该目录在 Vite root（edit_config_gui/）之内，构建时会被当成资源打包进 dist。
   */
  import appIcon from '../../../../src-tauri/icons/icon.ico';
  import { Card, Divider, ListItem } from 'm3-svelte';

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

{#snippet linkIcon()}
  <!-- 本地 Icon 是 stroke + currentColor，会跟着 ListItem 的 on-surface-variant 走 -->
  <Icon name="link" size={16} />
{/snippet}

<article class="about">
  <Card variant="elevated">
    <div class="hero">
      <img class="mark" src={appIcon} alt="" width="52" height="52" aria-hidden="true" />
      <div class="intro">
        <h2>配置编辑器</h2>
        <p class="tagline">
          CapsWriter-Offline 的图形化配置工具 —— 安全地改写服务端与客户端共用的
          <code>config.toml</code>
        </p>
        <p class="meta">Tauri 2 + Svelte 5 · 写入基于 Rust <code>toml_edit</code></p>
      </div>
    </div>
  </Card>

  <section>
    <h3>它能做什么</h3>
    <Card variant="outlined">
      <ul class="facts">
        {#each CAPABILITIES as item (item)}
          <li>{item}</li>
        {/each}
      </ul>
    </Card>
  </section>

  <section class="links-section">
    <h3>项目主页</h3>
    <Card variant="outlined">
      <ul class="links">
        {#each LINKS as link, i (link.url)}
          {#if i > 0}
            <li class="sep" aria-hidden="true"><Divider /></li>
          {/if}
          <ListItem
            headline={link.label}
            supporting={`${link.note} · ${link.url}`}
            trailing={linkIcon}
            lines={3}
            disabled={opening !== null}
            onclick={() => void open(link.url)}
          />
        {/each}
      </ul>
    </Card>
    {#if error}
      <p class="error">{error}</p>
    {/if}
  </section>

  <section>
    <h3>当前配置</h3>
    <Card variant="outlined">
      <dl class="kv">
        <dt>文件</dt>
        <dd><code>{configPath}</code></dd>
        <dt>备份</dt>
        <dd>每次保存前，旧内容会写到同目录的 <code>config.toml.bak</code></dd>
        <dt>生效方式</dt>
        <dd>保存后需重启对应的服务端 / 客户端进程才会读取新配置</dd>
      </dl>
    </Card>
  </section>

  <section>
    <h3>快捷键</h3>
    <Card variant="outlined">
      <dl class="kv">
        <dt><kbd>Ctrl</kbd> + <kbd>K</kbd></dt>
        <dd>全局搜索配置项（支持中文标题、键名、拼音全拼与首字母）</dd>
        <dt><kbd>Ctrl</kbd> + <kbd>S</kbd></dt>
        <dd>预览并保存改动</dd>
        <dt><kbd>Esc</kbd></dt>
        <dd>关闭搜索面板或确认对话框</dd>
      </dl>
    </Card>
  </section>
</article>

<style>
  .about {
    display: flex;
    flex-direction: column;
    gap: 24px;
    width: 100%;
    padding: 24px 32px 96px;
  }

  /* m3 的 Card 默认 16px 内边距 + medium 圆角；hero 里有 52px 图标，给大一号
     的圆角与内边距，才和 MD3 里「主卡片」的比例对上。
     不用 class 传参覆盖：Card 把 {...extra} 展开在静态 class 之后，传 class 会把
     m3-container / elevated 整套样式顶掉。 */
  .about > :global(.m3-container) {
    padding: 24px;
    border-radius: var(--m3-shape-large);
  }

  .about section > :global(.m3-container) {
    padding: 16px 20px;
    border-radius: var(--m3-shape-large);
  }

  /* 列表卡片让 ListItem 的通栏 hover 一直到卡片边缘 */
  .about section.links-section > :global(.m3-container) {
    padding: 8px;
  }

  section > h3 {
    margin: 0 0 12px;
    color: var(--m3c-on-surface-variant);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  .hero {
    display: flex;
    align-items: flex-start;
    gap: 16px;
  }

  .mark {
    flex: 0 0 auto;
    width: 52px;
    height: 52px;
    /*
     * ico 里带 256/128/64/48/32/24/16 七种尺寸，浏览器会挑最合适的一档，
     * 52px 下不会糊；`image-rendering` 保持默认的平滑插值即可。
     */
    border-radius: var(--m3-shape-medium);
  }

  .intro h2 {
    margin: 0 0 4px;
    color: var(--m3c-on-surface);
    font-size: 22px;
    font-weight: 500;
    line-height: 28px;
  }

  .tagline {
    margin: 0 0 6px;
    color: var(--m3c-on-surface);
    font-size: 13px;
    line-height: 1.7;
  }

  .meta {
    margin: 0;
    color: var(--m3c-on-surface-variant);
    font-size: 12px;
  }

  .facts {
    margin: 0;
    padding-left: 20px;
    color: var(--m3c-on-surface);
    font-size: 13px;
    line-height: 1.85;
  }

  .facts li + li {
    margin-top: 4px;
  }

  .links {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .sep {
    padding: 0 8px;
  }

  /* ListItem 自带 ripple 但没有 hover 底色与禁用态：补齐这两项，否则鼠标移
     上去只有指针变化，而打开链接期间（opening）看不出「暂时点不动」。 */
  .links :global(li > button:hover:not(:disabled)) {
    background: var(--ecg-hover);
  }

  .links :global(li > button:disabled) {
    opacity: 0.6;
    cursor: default;
  }

  .error {
    margin: 12px 0 0;
    color: var(--m3c-error);
    font-size: 12px;
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
    color: var(--m3c-on-surface-variant);
    white-space: nowrap;
  }

  .kv dd {
    min-width: 0;
    margin: 0;
    overflow-wrap: anywhere;
  }

  code {
    padding: 1px 4px;
    border-radius: var(--m3-shape-extra-small);
    background: var(--ecg-hover);
    font-family: var(--ecg-mono);
  }

  kbd {
    display: inline-block;
    min-width: 20px;
    padding: 0 6px;
    border: 1px solid var(--m3c-outline-variant);
    border-radius: var(--m3-shape-extra-small);
    background: var(--ecg-hover);
    color: var(--m3c-on-surface);
    font-family: var(--ecg-mono);
    font-size: 11px;
    line-height: 18px;
    text-align: center;
  }
</style>
