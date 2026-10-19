<script lang="ts">
  import { Divider } from 'm3-svelte';
  import type { SectionMeta } from '../schema/types.ts';
  import Field from './Field.svelte';

  let { section }: { section: SectionMeta } = $props();
</script>

<section class="section" id={`section-${section.id}`}>
  <div class="head">
    <h2>{section.title}</h2>
    {#if section.note}
      <p class="note">{section.note}</p>
    {/if}
  </div>

  <!-- 分区标题和字段之间用一条 MD3 分隔线划开，比给整个列表加边框更轻 -->
  <div class="rule">
    <Divider />
  </div>

  <div class="fields">
    {#each section.fields as field (field.path)}
      <Field {field} />
    {/each}
  </div>
</section>

<style>
  .section {
    margin: 0 0 32px;
    scroll-margin-top: 16px;
  }

  .head {
    margin-bottom: 8px;
  }

  /* titleLarge：20px/500。分区标题是页面里最高一级的视觉锚点，
     再大就会和顶栏抢层级 */
  h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 500;
    line-height: 28px;
    letter-spacing: 0;
    color: var(--m3c-on-surface);
  }

  .note {
    margin: 4px 0 0;
    color: var(--m3c-on-surface-variant);
    font-size: 12px;
    line-height: 1.6;
  }

  .rule {
    margin-bottom: 4px;
  }

  .fields {
    display: flex;
    flex-direction: column;
  }
</style>
