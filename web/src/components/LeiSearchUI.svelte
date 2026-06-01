<script lang="ts">
  import { writable } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    searchLeisFiltered,
    countLeisFiltered,
    PAGE_SIZE,
    type LeiRow,
  } from '../lib/db.ts';

  // --- Svelte 5 state for UI ---
  let rawTerm = $state('');
  let debouncedTerm = $state('');
  let ente = $state(''); // Padrão: Todos os entes
  let tipoLei = $state(''); // Padrão: Todos os tipos de norma
  let year = $state<number | null>(null);
  let page = $state(0);

  // Debounce: update debouncedTerm 400ms after last keystroke.
  $effect(() => {
    const _raw = rawTerm;
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
  function onTipoLeiChange(e: Event) {
    tipoLei = (e.target as HTMLSelectElement).value;
    page = 0;
  }
  function onYearInput(e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    year = Number.isFinite(v) && v >= 1900 && v <= 2099 ? v : null;
    page = 0;
  }

  // --- Helpers de Formatação ---
  function formatTipoLei(tipo: string): string {
    if (!tipo) return 'Norma';
    const clean = tipo.toLowerCase();
    if (clean === 'lei') return 'Lei Ordinária';
    if (clean === 'lei-complementar') return 'Lei Complementar';
    if (clean === 'decreto') return 'Decreto';
    if (clean === 'resolucao') return 'Resolução';
    if (clean === 'portaria') return 'Portaria';
    return tipo.charAt(0).toUpperCase() + tipo.slice(1);
  }

  function formatEnte(enteCode: string): string {
    if (!enteCode) return '-';
    const clean = enteCode.toLowerCase();
    if (clean === 'ro') return 'Rondônia';
    if (clean === 'sp') return 'São Paulo';
    if (clean === 'federal') return 'Federal';
    return enteCode.toUpperCase();
  }

  function getIaUrl(row: LeiRow): string {
    // Sob o esquema content-addressed (ADR-0010), o item raw é bucketizado por
    // hash e não é derivável da norma no cliente — então linkamos para uma busca
    // no Internet Archive pelo lei_id, que resolve para o(s) item(ns) relevantes.
    return `https://archive.org/search?query=${encodeURIComponent(row.lei_id)}`;
  }

  // --- Bridge: Svelte 5 state → Svelte 4 stores (TanStack Query interface) ---
  const resultsOpts = writable({
    queryKey: ['leis', '', '', '', null, 0] as readonly unknown[],
    queryFn: () => searchLeisFiltered('', {}),
    placeholderData: (prev: LeiRow[] | undefined) => prev,
  });
  const countOpts = writable({
    queryKey: ['leis-count', '', '', '', null] as readonly unknown[],
    queryFn: () => countLeisFiltered('', {}),
    staleTime: 5 * 60 * 1000,
  });

  $effect(() => {
    resultsOpts.set({
      queryKey: ['leis', debouncedTerm, ente, tipoLei, year, page] as readonly unknown[],
      queryFn: () =>
        searchLeisFiltered(debouncedTerm, {
          ente: ente || undefined,
          tipoLei: tipoLei || undefined,
          year: year ?? undefined,
          page,
          pageSize: PAGE_SIZE,
        }),
      placeholderData: (prev: LeiRow[] | undefined) => prev,
    });
  });

  $effect(() => {
    countOpts.set({
      queryKey: ['leis-count', debouncedTerm, ente, tipoLei, year] as readonly unknown[],
      queryFn: () =>
        countLeisFiltered(debouncedTerm, {
          ente: ente || undefined,
          tipoLei: tipoLei || undefined,
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
    placeholder="Buscar no texto das leis (ex: servidores públicos, IPTU, cargos...)"
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

    <select value={tipoLei} onchange={onTipoLeiChange} aria-label="Filtrar por tipo de norma">
      <option value="">Todos os tipos de norma</option>
      <option value="lei">Lei Ordinária</option>
      <option value="lei-complementar">Lei Complementar</option>
      <option value="decreto">Decreto</option>
    </select>

    <input
      type="number"
      placeholder="Ano"
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
      norma{($countQ.data ?? 0) !== 1 ? 's' : ''}
      encontrada{($countQ.data ?? 0) !== 1 ? 's' : ''}
      {#if debouncedTerm}para "<em>{debouncedTerm}</em>"{/if}
    </p>

    <div class="results-table-container">
      <table class="striped responsive">
        <thead>
          <tr>
            <th scope="col">Norma</th>
            <th scope="col" style="width: 90px; text-align: center;">Ano</th>
            <th scope="col">Ementa / Conteúdo</th>
            <th scope="col" style="width: 130px; text-align: center;">Ente</th>
            <th scope="col" style="width: 100px; text-align: center;">Link</th>
          </tr>
        </thead>
        <tbody>
          {#each $resultsQ.data ?? [] as row (row.lei_id + '|' + row.dispositivo_path + '|' + (row.em ?? ''))}
            <tr>
              <td>
                <span class="norma-titulo">
                  {formatTipoLei(row.tipo_lei)} nº {row.numero_lei || 'S/N'}
                </span>
              </td>
              <td style="text-align: center;">
                <span class="norma-ano">{row.ano_lei || '-'}</span>
              </td>
              <td>
                <div class="text-excerpt">
                  {#if row.texto}
                    {row.texto}
                  {:else}
                    <span class="no-text">Sem texto disponível</span>
                  {/if}
                </div>
              </td>
              <td style="text-align: center;">
                <span class="badge {row.ente}">
                  {formatEnte(row.ente)}
                </span>
              </td>
              <td style="text-align: center;">
                <a
                  href={getIaUrl(row)}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn-link"
                >
                  Abrir IA
                </a>
              </td>
            </tr>
          {/each}

          {#if ($resultsQ.data ?? []).length === 0 && !$resultsQ.isFetching}
            <tr>
              <td colspan="5" class="empty-state">
                Nenhum resultado encontrado{debouncedTerm ? ` para "${debouncedTerm}"` : ''}.
              </td>
            </tr>
          {/if}
        </tbody>
      </table>
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
  .results-table-container {
    overflow-x: auto;
    background: var(--pico-card-background-color, #fff);
    border: 1px solid var(--pico-border-color, #e1e1e1);
    border-radius: var(--pico-border-radius, 8px);
    margin-bottom: 1.5rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  }
  table {
    margin-bottom: 0;
    font-size: 0.925rem;
    width: 100%;
  }
  th {
    background: var(--pico-table-border-color, #f9f9f9);
    font-weight: 600;
  }
  td, th {
    padding: 0.75rem 1rem;
    vertical-align: middle;
  }
  .norma-titulo {
    font-weight: 600;
    color: var(--pico-primary, #0056b3);
  }
  .norma-ano {
    font-variant-numeric: tabular-nums;
  }
  .text-excerpt {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.4;
    max-height: 2.8em;
    word-break: break-word;
  }
  .no-text {
    font-style: italic;
    color: var(--pico-muted-color, #888);
  }
  .empty-state {
    text-align: center;
    padding: 2rem;
    color: var(--pico-muted-color, #666);
  }
  .badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    font-size: 0.75rem;
    font-weight: 600;
    border-radius: 4px;
    text-transform: uppercase;
  }
  .badge.ro {
    background-color: #e3f2fd;
    color: #0d47a1;
  }
  .badge.sp {
    background-color: #efebe9;
    color: #3e2723;
  }
  .badge.federal {
    background-color: #e8f5e9;
    color: #1b5e20;
  }
  .btn-link {
    display: inline-block;
    font-size: 0.85rem;
    font-weight: 500;
    text-decoration: none;
    padding: 0.25rem 0.6rem;
    border: 1px solid var(--pico-primary, #0056b3);
    border-radius: 4px;
    transition: all 0.2s ease;
  }
  .btn-link:hover {
    background: var(--pico-primary, #0056b3);
    color: #fff !important;
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
