<script lang="ts">
  import { writable } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    searchLeisFiltered,
    countLeisFiltered,
    PAGE_SIZE,
    type LeiRow,
  } from '../lib/db.ts';
  import LeiCard from './LeiCard.svelte';

  // --- Svelte 5 state for UI ---
  let rawTerm = $state('');
  let debouncedTerm = $state('');
  let ente = $state('');
  let year = $state<number | null>(null);
  let page = $state(0);

  // Debounce: update debouncedTerm 400ms after last keystroke.
  // $effect cleanup cancels the pending timer on rawTerm change or unmount.
  $effect(() => {
    const _raw = rawTerm; // captured for closure
    const timer = setTimeout(() => {
      debouncedTerm = _raw;
      page = 0;
    }, 400);
    return () => clearTimeout(timer);
  });

  function onTermInput(e: Event) {
    rawTerm = (e.target as HTMLInputElement).value;
  }
  function onEnteChange(e: Event) {
    ente = (e.target as HTMLSelectElement).value;
    page = 0;
  }
  function onYearInput(e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    year = Number.isFinite(v) && v >= 1900 && v <= 2099 ? v : null;
    page = 0;
  }

  // --- Bridge: Svelte 5 state → Svelte 4 stores (TanStack Query interface) ---
  const resultsOpts = writable({
    queryKey: ['leis', '', '', null, 0] as readonly unknown[],
    queryFn: () => searchLeisFiltered('', {}),
    placeholderData: (prev: LeiRow[] | undefined) => prev,
  });
  const countOpts = writable({
    queryKey: ['leis-count', '', '', null] as readonly unknown[],
    queryFn: () => countLeisFiltered('', {}),
    staleTime: 5 * 60 * 1000,
  });

  $effect(() => {
    resultsOpts.set({
      queryKey: ['leis', debouncedTerm, ente, year, page] as readonly unknown[],
      queryFn: () =>
        searchLeisFiltered(debouncedTerm, {
          ente: ente || undefined,
          year: year ?? undefined,
          page,
          pageSize: PAGE_SIZE,
        }),
      placeholderData: (prev: LeiRow[] | undefined) => prev,
    });
  });

  $effect(() => {
    countOpts.set({
      queryKey: ['leis-count', debouncedTerm, ente, year] as readonly unknown[],
      queryFn: () =>
        countLeisFiltered(debouncedTerm, {
          ente: ente || undefined,
          year: year ?? undefined,
        }),
      staleTime: 5 * 60 * 1000,
    });
  });

  const resultsQ = createQuery(resultsOpts);
  const countQ = createQuery(countOpts);

  // --- Pagination ---
  function totalPages() {
    return Math.max(1, Math.ceil(($countQ.data ?? 0) / PAGE_SIZE));
  }
</script>

<section>
  <input
    type="search"
    placeholder="Buscar leis (ex: servidores públicos, IPTU, meio ambiente...)"
    value={rawTerm}
    oninput={onTermInput}
    aria-label="Buscar leis"
  />

  <div class="filters">
    <select value={ente} onchange={onEnteChange} aria-label="Filtrar por ente">
      <option value="">Todos os entes</option>
      <option value="ro">Rondônia</option>
      <option value="federal">Federal</option>
      <option value="sp">São Paulo</option>
    </select>

    <input
      type="number"
      placeholder="Ano (ex: 2020)"
      min="1900"
      max="2099"
      value={year ?? ''}
      oninput={onYearInput}
      aria-label="Filtrar por ano de vigência"
    />
  </div>

  {#if $resultsQ.isPending}
    <p aria-busy="true">Carregando...</p>
  {:else if $resultsQ.isError}
    <p class="error">
      {$resultsQ.error instanceof Error ? $resultsQ.error.message : 'Erro ao carregar dados.'}
    </p>
  {:else}
    <p class="stats">
      {$countQ.isPending ? '…' : ($countQ.data ?? 0)}
      resultado{($countQ.data ?? 0) !== 1 ? 's' : ''}
      {#if debouncedTerm}para "<em>{debouncedTerm}</em>"{/if}
    </p>

    <div class="results">
      {#each $resultsQ.data ?? [] as row (row.lei_id + '|' + row.dispositivo_path + '|' + (row.em ?? ''))}
        <LeiCard {row} />
      {/each}

      {#if ($resultsQ.data ?? []).length === 0 && !$resultsQ.isFetching}
        <p>Nenhum resultado{debouncedTerm ? ` para "${debouncedTerm}"` : ''}.</p>
      {/if}
    </div>

    {#if totalPages() > 1}
      <nav class="pagination" aria-label="Paginação de resultados">
        <button
          disabled={page === 0 || $resultsQ.isFetching}
          onclick={() => { page = Math.max(0, page - 1); }}
        >
          ← Anterior
        </button>
        <span>Página {page + 1} de {totalPages()}</span>
        <button
          disabled={page >= totalPages() - 1 || $resultsQ.isFetching}
          onclick={() => { page = Math.min(totalPages() - 1, page + 1); }}
        >
          Próxima →
        </button>
      </nav>
    {/if}
  {/if}
</section>

<style>
  .filters {
    display: flex;
    gap: 0.5rem;
    margin: 0.5rem 0 0.75rem;
  }
  .filters select,
  .filters input[type='number'] {
    flex: 1;
    min-width: 0;
  }
  .stats {
    font-size: 0.875rem;
    color: var(--pico-muted-color, #666);
    margin: 0 0 0.5rem;
  }
  .results {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    margin-top: 1rem;
    flex-wrap: wrap;
  }
  .pagination span {
    white-space: nowrap;
  }
  .error {
    color: var(--pico-color-red-500, #e53e3e);
  }
</style>
