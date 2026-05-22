<script lang="ts">
  import type { LeiRow } from '../lib/db.ts';

  let { row }: { row: LeiRow } = $props();

  const iaUrl = `https://archive.org/details/${row.lei_id}`;
  const isRevogado = row.ate != null;
  const dateStr = row.ate instanceof Date
    ? row.ate.toISOString().slice(0, 10)
    : row.ate;
</script>

<article style={isRevogado ? 'opacity: 0.6' : ''}>
  <header>
    <a href={iaUrl} target="_blank" rel="noopener noreferrer">
      <strong>{row.lei_id}</strong>
    </a>
    {#if row.dispositivo_path !== 'ementa'}
      <small>&nbsp;§ {row.dispositivo_path}</small>
    {/if}
    {#if isRevogado}
      <small class="revogado">&nbsp;(revogado em {dateStr})</small>
    {/if}
  </header>
  <p>{row.texto_normalizado ?? '(sem texto)'}</p>
</article>

<style>
  .revogado {
    color: var(--pico-color-red-500, #e53e3e);
  }
</style>
