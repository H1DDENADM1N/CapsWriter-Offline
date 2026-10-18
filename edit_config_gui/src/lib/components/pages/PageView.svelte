<script lang="ts">
  import { pages } from '../../schema/index.ts';
  import { navStore } from '../../stores/nav.svelte.ts';
  import Section from '../Section.svelte';
  import AboutPage from './AboutPage.svelte';

  const page = $derived(pages.find((p) => p.id === navStore.current()) ?? pages[0]);
</script>

{#if page}
  {#if page.id === 'about'}
    <AboutPage />
  {:else}
    <article class="page">
      {#if page.sections.length === 0}
        <div class="empty">
          <p>这一页没有可修改的配置项。</p>
        </div>
      {:else}
        {#each page.sections as section (section.id)}
          <Section {section} />
        {/each}
      {/if}
    </article>
  {/if}
{/if}

<style>
  /*
   * 不再限制最大宽度：大屏上右侧会留出一大片空白，而且长路径（模型路径动辄
   * 80+ 字符）被压成一条 13em 宽的输入框后基本没法读。字段行本身是
   * `minmax(13em, 26%) 1fr`，窗口越宽输入框越长，正好用上。
   */
  .page {
    width: 100%;
    padding: 18px 26px 80px;
  }

  .empty {
    color: var(--ecg-muted, #888);
    font-size: 13px;
    line-height: 1.8;
  }
</style>
