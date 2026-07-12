<script lang="ts">
  import { writable } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    searchGroupedByLei,
    countLeisGrouped,
    listTiposLei,
    listEntes,
    PAGE_SIZE,
    type GroupedHit,
  } from '../lib/db.ts';
  import {
    leiTitle,
    leiUrl,
    breadcrumb,
    formatTipoLei,
    formatEnte,
    formatDate,
    iaDetailsUrl,
    STAGES,
  } from '../lib/format.ts';
  import DatasetUnavailable from './DatasetUnavailable.svelte';

  // Tudo que chega ao Parquet `versoes` alcançou o estágio S4 por construção
  // (PRD §6) — o badge é o mesmo para toda linha, com a descrição no title.
  const stageS4 = STAGES.find((s) => s.id === 'S4');

  // --- Svelte 5 state for UI ---
  let rawTerm = $state('');
  let debouncedTerm = $state('');
  let ente = $state(''); // Padrão: Todos os entes
  let enteOptions = $state<string[]>([]); // entes realmente presentes no dataset
  let tipoLei = $state(''); // Rótulo selecionado (agrupa aliases); '' = todos
  let tipoOptions = $state<string[]>([]); // valores reais de tipo_lei no dataset
  let year = $state<number | null>(null);
  let page = $state(0);

  // Popula o filtro de tipo a partir dos valores realmente persistidos no
  // dataset (lei.complementar, lc, decreto, ...), evitando slugs hardcoded que
  // poderiam divergir do ETL e filtrar zero resultados. Roda uma vez.
  $effect(() => {
    listTiposLei()
      .then((tipos) => {
        tipoOptions = tipos;
      })
      .catch(() => {});
  });

  // Idem para entes: só oferecemos filtros de cobertura que existe de fato no
  // dataset publicado — nada de anunciar SP/federal antes de haver dados.
  $effect(() => {
    listEntes()
      .then((entes) => {
        enteOptions = entes;
      })
      .catch(() => {});
  });

  // Agrupa valores crus equivalentes sob o mesmo rótulo (lei.complementar e lc
  // → "Lei Complementar"): o dropdown não exibe opções duplicadas e o filtro
  // casa todos os aliases de um tipo de uma vez (tipo_lei IN (...)).
  const tipoGroups = $derived.by(() => {
    const byLabel = new Map<string, string[]>();
    for (const raw of tipoOptions) {
      const label = formatTipoLei(raw);
      const arr = byLabel.get(label) ?? [];
      arr.push(raw);
      byLabel.set(label, arr);
    }
    return [...byLabel.entries()]
      .map(([label, values]) => ({ label, values }))
      .sort((a, b) => a.label.localeCompare(b.label, 'pt'));
  });

  // Rótulo selecionado → todos os valores crus daquele tipo (ou undefined).
  function selectedTipoValues(): string[] | undefined {
    if (!tipoLei) return undefined;
    return tipoGroups.find((g) => g.label === tipoLei)?.values;
  }

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

  // A localização do dispositivo só interessa quando a busca textual casou um
  // trecho que não é a ementa — na navegação a linha representativa é apenas
  // um resumo da norma, não um "match".
  function isDispositivoHit(row: GroupedHit): boolean {
    return Boolean(debouncedTerm.trim()) && row.dispositivo_path !== 'ementa';
  }

  // --- Bridge: Svelte 5 state → Svelte 4 stores (TanStack Query interface) ---
  const resultsOpts = writable({
    queryKey: ['leis', '', '', '', null, 0] as readonly unknown[],
    queryFn: () => searchGroupedByLei('', {}),
    placeholderData: (prev: GroupedHit[] | undefined) => prev,
  });
  const countOpts = writable({
    queryKey: ['leis-count', '', '', '', null] as readonly unknown[],
    queryFn: () => countLeisGrouped('', {}),
    staleTime: 5 * 60 * 1000,
  });

  $effect(() => {
    resultsOpts.set({
      queryKey: ['leis', debouncedTerm, ente, tipoLei, year, page] as readonly unknown[],
      queryFn: () =>
        searchGroupedByLei(debouncedTerm, {
          ente: ente || undefined,
          tipoLei: selectedTipoValues(),
          year: year ?? undefined,
          page,
          pageSize: PAGE_SIZE,
        }),
      placeholderData: (prev: GroupedHit[] | undefined) => prev,
    });
  });

  $effect(() => {
    countOpts.set({
      queryKey: ['leis-count', debouncedTerm, ente, tipoLei, year] as readonly unknown[],
      queryFn: () =>
        countLeisGrouped(debouncedTerm, {
          ente: ente || undefined,
          tipoLei: selectedTipoValues(),
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
      {#each enteOptions as e}
        <option value={e}>{formatEnte(e)}</option>
      {/each}
    </select>

    <select value={tipoLei} onchange={onTipoLeiChange} aria-label="Filtrar por tipo de norma">
      <option value="">Todos os tipos de norma</option>
      {#each tipoGroups as g}
        <option value={g.label}>{g.label}</option>
      {/each}
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
    <DatasetUnavailable error={$resultsQ.error} />
  {:else}
    <p class="stats">
      {$countQ.isPending ? '…' : ($countQ.data ?? 0)}
      norma{($countQ.data ?? 0) !== 1 ? 's' : ''}
      encontrada{($countQ.data ?? 0) !== 1 ? 's' : ''}
      {#if debouncedTerm}para "<em>{debouncedTerm}</em>"{/if}
    </p>

    <div class="results" aria-busy={$resultsQ.isFetching}>
      {#each $resultsQ.data ?? [] as row (row.lei_id)}
        <article class="hit">
          <header class="hit-header">
            <h3 class="hit-title">
              <a href={leiUrl(row.lei_id)}>{leiTitle(row)}</a>
            </h3>
            <span class="badge">{formatEnte(row.ente)}</span>
            {#if stageS4}
              <span class="badge" title={stageS4.description}>
                {stageS4.id} · {stageS4.label}
              </span>
            {/if}
          </header>

          {#if isDispositivoHit(row)}
            <p class="hit-where">{breadcrumb(row.dispositivo_path)}</p>
            <a class="hit-excerpt-link" href={leiUrl(row.lei_id, row.dispositivo_path)}>
              <p class="hit-excerpt">{row.texto || 'Sem texto disponível'}</p>
            </a>
          {:else}
            <p class="hit-excerpt">
              {#if row.texto}
                {row.texto}
              {:else}
                <span class="no-text">Sem texto disponível</span>
              {/if}
            </p>
          {/if}

          {#if row.match_count > 1}
            <p class="hit-more">
              <a href={leiUrl(row.lei_id)}>
                +{row.match_count - 1} outro{row.match_count - 1 !== 1 ? 's' : ''}
                dispositivo{row.match_count - 1 !== 1 ? 's' : ''}
                corresponde{row.match_count - 1 !== 1 ? 'm' : ''}
              </a>
            </p>
          {/if}

          <footer class="hit-meta">
            {#if row.em}
              <span>vigente desde {formatDate(row.em)}</span>
            {/if}
            {#if row.ano_lei}
              <span>{row.ano_lei}</span>
            {/if}
            <!-- O Archive é a evidência de preservação, não a experiência de
                 leitura — por isso o link é secundário, não o CTA do card. -->
            <a
              class="ia-link"
              href={iaDetailsUrl(row.lei_id)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Evidência no IA
            </a>
          </footer>
        </article>
      {/each}

      {#if ($resultsQ.data ?? []).length === 0 && !$resultsQ.isFetching}
        <p class="empty-state">
          Nenhum resultado encontrado{debouncedTerm ? ` para "${debouncedTerm}"` : ''}.
        </p>
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
    color: var(--pico-muted-color);
    margin: 0 0 0.5rem;
  }

  .results {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
  }
  .hit {
    margin: 0;
    padding: 1rem 1.25rem;
  }
  .hit-header {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    padding: 0;
    border: none;
    background: none;
  }
  .hit-title {
    font-size: 1.05rem;
    margin: 0;
    margin-right: auto;
  }
  .hit-title a {
    text-decoration: none;
  }
  .hit-title a:hover {
    text-decoration: underline;
  }
  .badge {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 600;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: var(--pico-border-radius);
    color: var(--pico-muted-color);
    text-transform: uppercase;
    letter-spacing: 0.02em;
    white-space: nowrap;
  }
  .hit-where {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--pico-muted-color);
    margin: 0 0 0.15rem;
  }
  .hit-excerpt-link {
    display: block;
    text-decoration: none;
    color: inherit;
  }
  .hit-excerpt-link:hover .hit-excerpt {
    text-decoration: underline;
    text-decoration-color: var(--pico-muted-border-color);
  }
  .hit-excerpt {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.45;
    max-height: 4.35em;
    word-break: break-word;
    color: var(--pico-color);
    margin: 0 0 0.35rem;
  }
  .no-text {
    font-style: italic;
    color: var(--pico-muted-color);
  }
  .hit-more {
    font-size: 0.85rem;
    margin: 0 0 0.35rem;
  }
  .hit-meta {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.35rem 1rem;
    font-size: 0.8rem;
    color: var(--pico-muted-color);
    margin: 0;
    padding: 0;
    border: none;
    background: none;
  }
  .ia-link {
    margin-left: auto;
    font-size: 0.8rem;
    color: var(--pico-muted-color);
    text-decoration-color: var(--pico-muted-border-color);
  }
  .empty-state {
    text-align: center;
    padding: 2rem;
    color: var(--pico-muted-color);
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
</style>
