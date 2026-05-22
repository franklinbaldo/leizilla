<script lang="ts">
  import { searchLeis, type LeiRow } from '../lib/db.ts';
  import LeiCard from './LeiCard.svelte';

  let query = $state('');
  let results = $state<LeiRow[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let initialized = $state(false);

  let debounceTimer: ReturnType<typeof setTimeout>;
  let searchSeq = 0;

  async function doSearch(q: string) {
    const seq = ++searchSeq;
    loading = true;
    error = null;
    try {
      const rows = await searchLeis(q);
      if (seq !== searchSeq) return;
      results = rows;
      initialized = true;
    } catch (e) {
      if (seq !== searchSeq) return;
      error = e instanceof Error ? e.message : String(e);
      results = [];
    } finally {
      if (seq === searchSeq) loading = false;
    }
  }

  function onInput(e: Event) {
    query = (e.target as HTMLInputElement).value;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => doSearch(query), 400);
  }
</script>

<section>
  <input
    type="search"
    placeholder="Buscar leis (ex: servidores públicos, IPTU, meio ambiente...)"
    value={query}
    oninput={onInput}
    aria-label="Buscar leis"
  />

  {#if loading}
    <p aria-busy="true">Carregando...</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else if initialized && results.length === 0}
    <p>Nenhum resultado{query ? ` para "${query}"` : ''}.</p>
  {:else}
    <div class="results">
      {#each results as row (row.lei_id + '|' + row.dispositivo_path + '|' + (row.em ?? ''))}
        <LeiCard {row} />
      {/each}
    </div>
  {/if}
</section>
