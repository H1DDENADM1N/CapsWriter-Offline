<script lang="ts">
  import type { SectionMeta } from '../schema/types.ts';
  import Field from './Field.svelte';

  let { section }: { section: SectionMeta } = $props();
</script>

<section class="section" id={`section-${section.id}`}>
  <h2>{section.title}</h2>
  {#if section.note}
    <p class="note">{section.note}</p>
  {/if}

  <div class="fields">
    {#each section.fields as field (field.path)}
      <Field {field} />
    {/each}
  </div>
</section>

<style>
  .section {
    margin: 0 0 28px;
    scroll-margin-top: 16px;
  }

  h2 {
    margin: 0 0 4px;
    font-size: 15px;
    font-weight: 600;
  }

  .note {
    margin: 0 0 8px;
    color: var(--ecg-muted, #888);
    font-size: 12px;
    line-height: 1.6;
  }

  .fields {
    border-top: 1px solid var(--ecg-line, #eceef2);
  }
</style>
