<script lang="ts">
  import { pages } from '../../schema/index.ts';
  import { navStore } from '../../stores/nav.svelte.ts';
  import Section from '../Section.svelte';

  const page = $derived(pages.find((p) => p.id === navStore.current()) ?? pages[0]);
</script>

{#if page}
  <article class="page">
    <header class="head">
      <h1>{page.title}</h1>
    </header>

    {#if page.sections.length === 0}
      <div class="empty">
        <p>这一页没有可修改的配置项。</p>
        <p>
          本工具只负责改写 <code>config.toml</code>；安装、模型下载与运行日志请看仓库里的
          <code>readme.md</code>。
        </p>
      </div>
    {:else}
      {#each page.sections as section (section.id)}
        <Section {section} />
      {/each}
    {/if}
  </article>
{/if}

<style>
  .page {
    max-width: 820px;
    padding: 20px 26px 80px;
  }

  .head {
    margin-bottom: 18px;
  }

  h1 {
    margin: 0;
    font-size: 19px;
    font-weight: 600;
  }

  .empty {
    color: var(--ecg-muted, #888);
    font-size: 13px;
    line-height: 1.8;
  }

  code {
    padding: 1px 4px;
    border-radius: 4px;
    background: var(--ecg-hover, #f3f4f7);
    font-size: 12px;
  }
</style>
