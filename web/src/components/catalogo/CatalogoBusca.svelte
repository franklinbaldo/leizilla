<script lang="ts">
  // Busca da página inicial sobre o catálogo oficial inteiro (ADR-0017): cada norma do
  // índice da Casa Civil de Rondônia é encontrável pela ementa, pelo título ou pelo
  // número, mesmo sem PDF preservado. O selo mostra, com honestidade, até onde o Leizilla
  // chegou com a norma (só catálogo → preservada → legível → estruturada).
  import { writable } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    ESTAGIO_DESCRICAO,
    ESTAGIO_ROTULO,
    SITUACAO_DESCRICAO,
    estagioDe,
    situacaoRotulo,
    tipoRotulo,
    truncar,
  } from '../../lib/catalogo';
  import {
    listDecadasCatalogo,
    listTiposCatalogoOficial,
    searchCatalogo,
    type PaginaCatalogo,
  } from '../../lib/catalogoDb';
  import { PAGE_SIZE, searchGroupedByLei, type GroupedHit } from '../../lib/db';
  import { breadcrumb, formatDate, leiTitle, leiUrl } from '../../lib/format';

  const initialTerm = new URLSearchParams(location.search).get('q')?.trim() ?? '';

  let rawTerm = $state(initialTerm);
  let debouncedTerm = $state(initialTerm);
  let tipo = $state('');
  let decada = $state<number | null>(null);
  let ano = $state<number | null>(null);
  let page = $state(0);
  let tipoOptions = $state<string[]>([]);
  let decadaOptions = $state<number[]>([]);

  $effect(() => {
    listTiposCatalogoOficial()
      .then((t) => (tipoOptions = t))
      .catch(() => {});
    listDecadasCatalogo()
      .then((d) => (decadaOptions = d))
      .catch(() => {});
  });

  $effect(() => {
    const raw = rawTerm;
    const timer = setTimeout(() => {
      debouncedTerm = raw;
      page = 0;
    }, 300);
    return () => clearTimeout(timer);
  });

  function onYearInput(e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    ano = Number.isFinite(v) && v >= 1900 && v <= 2099 ? v : null;
    page = 0;
  }

  // O ano, quando preenchido, já delimita a década.
  const filtros = $derived({
    tipo: tipo || undefined,
    ano: ano ?? undefined,
    decada: ano == null ? (decada ?? undefined) : undefined,
  });

  const resultsOpts = writable({
    queryKey: ['catalogo', '', '', null, null, 0] as readonly unknown[],
    queryFn: () => searchCatalogo('', {}),
    placeholderData: (prev: PaginaCatalogo | undefined) => prev,
  });
  const corpoOpts = writable({
    queryKey: ['catalogo-corpo', ''] as readonly unknown[],
    queryFn: (): Promise<GroupedHit[]> => Promise.resolve([]),
    enabled: false,
  });

  $effect(() => {
    const term = debouncedTerm;
    const f = filtros;
    const p = page;
    resultsOpts.set({
      queryKey: ['catalogo', term, f.tipo ?? '', f.decada ?? null, f.ano ?? null, p] as readonly unknown[],
      queryFn: () => searchCatalogo(term, f, { page: p, pageSize: PAGE_SIZE }),
      placeholderData: (prev: PaginaCatalogo | undefined) => prev,
    });
    // Também no corpo das normas estruturadas (dispositivos): só com termo e sem filtros
    // do catálogo, é uma busca complementar de poucas linhas.
    corpoOpts.set({
      queryKey: ['catalogo-corpo', term] as readonly unknown[],
      queryFn: () => searchGroupedByLei(term, { pageSize: 5 }),
      enabled: term.trim().length >= 3,
    });
  });

  const resultsQ = createQuery(resultsOpts);
  const corpoQ = createQuery(corpoOpts);

  const total = $derived($resultsQ.data?.total ?? 0);

  function totalPages() {
    return Math.max(1, Math.ceil(total / PAGE_SIZE));
  }

  // Cada resultado leva à página da norma pelo id do catálogo (o raw_id legado).
  function normaUrl(row: { norma_id: string }): string {
    return leiUrl(row.norma_id);
  }
</script>

<section>
  <input
    type="search"
    placeholder="Buscar por assunto, título ou número (ex.: crédito suplementar, plano de carreira, lei 80)"
    value={rawTerm}
    oninput={(e) => (rawTerm = (e.target as HTMLInputElement).value)}
    aria-label="Buscar normas"
  />

  <div class="filters">
    <select
      value={tipo}
      onchange={(e) => {
        tipo = (e.target as HTMLSelectElement).value;
        page = 0;
      }}
      aria-label="Filtrar por tipo de norma"
    >
      <option value="">Todos os tipos de norma</option>
      {#each tipoOptions as t}
        <option value={t}>{tipoRotulo(t)}</option>
      {/each}
    </select>

    <select
      value={decada ?? ''}
      disabled={ano != null}
      onchange={(e) => {
        const v = parseInt((e.target as HTMLSelectElement).value, 10);
        decada = Number.isFinite(v) ? v : null;
        page = 0;
      }}
      aria-label="Filtrar por década"
    >
      <option value="">Todas as décadas</option>
      {#each decadaOptions as d}
        <option value={d}>Anos {d}</option>
      {/each}
    </select>

    <input
      type="number"
      placeholder="Ano"
      min="1900"
      max="2099"
      value={ano ?? ''}
      oninput={onYearInput}
      aria-label="Filtrar por ano da norma"
    />
  </div>

  {#if $resultsQ.isPending}
    <p aria-busy="true">Carregando o catálogo…</p>
  {:else if $resultsQ.isError}
    <p class="empty-state" role="alert">Não foi possível consultar o catálogo oficial.</p>
  {:else}
    <p class="stats" data-testid="catalogo-total">
      {total.toLocaleString('pt-BR')}
      norma{total !== 1 ? 's' : ''}
      encontrada{total !== 1 ? 's' : ''}
      {#if debouncedTerm}para "<em>{debouncedTerm}</em>"{/if}
      {#if !debouncedTerm}· mais recentes primeiro{/if}
    </p>

    <div class="results" aria-busy={$resultsQ.isFetching}>
      {#each $resultsQ.data?.rows ?? [] as row (row.norma_id)}
        {@const estagio = estagioDe(row)}
        {@const situacao = situacaoRotulo(row.situacao_norma)}
        <article class="hit">
          <header class="hit-header">
            <h3 class="hit-title">
              <a href={normaUrl(row)}>{row.titulo}</a>
            </h3>
            <span class="badge badge-estagio" title={ESTAGIO_DESCRICAO[estagio]}>
              {ESTAGIO_ROTULO[estagio]}
            </span>
            {#if situacao}
              <span class="badge badge-situacao" title={SITUACAO_DESCRICAO[row.situacao_norma ?? ''] ?? ''}>
                {situacao}
              </span>
            {/if}
          </header>
          <p class="hit-excerpt">
            {#if row.ementa}
              {truncar(row.ementa)}
            {:else}
              <span class="no-text">Sem ementa no índice oficial</span>
            {/if}
          </p>
          <footer class="hit-meta">
            <span>{tipoRotulo(row.tipo)}</span>
            {#if row.data}<span>{formatDate(row.data)}</span>{/if}
            {#if row.identidade_incerta}<span>identidade incerta no índice</span>{/if}
          </footer>
        </article>
      {/each}

      {#if ($resultsQ.data?.rows ?? []).length === 0 && !$resultsQ.isFetching}
        <p class="empty-state">
          Nenhuma norma do índice oficial encontrada{debouncedTerm ? ` para "${debouncedTerm}"` : ''}.
        </p>
      {/if}
    </div>

    {#if totalPages() > 1}
      <nav class="pagination" aria-label="Paginação de resultados">
        <button
          disabled={page === 0 || $resultsQ.isFetching}
          onclick={() => {
            page = Math.max(0, page - 1);
          }}
        >
          ← Anterior
        </button>
        <span>Página {page + 1} de {totalPages()}</span>
        <button
          disabled={page >= totalPages() - 1 || $resultsQ.isFetching}
          onclick={() => {
            page = Math.min(totalPages() - 1, page + 1);
          }}
        >
          Próxima →
        </button>
      </nav>
    {/if}

    {#if ($corpoQ.data ?? []).length > 0}
      <aside class="corpo" aria-labelledby="titulo-corpo">
        <h3 id="titulo-corpo">Também no texto de normas estruturadas</h3>
        <ul>
          {#each $corpoQ.data ?? [] as hit (hit.lei_id)}
            <li>
              <a href={`${leiUrl(hit.lei_id)}&q=${encodeURIComponent(debouncedTerm.trim())}`}>{leiTitle(hit)}</a>
              <small>{breadcrumb(hit.dispositivo_path)}</small>
            </li>
          {/each}
        </ul>
      </aside>
    {/if}
  {/if}

  <p class="aviso-catalogo">
    <small>
      A lista vem do índice oficial da Casa Civil de Rondônia. Título, data, ementa e a marca
      de revogação são do índice; o selo indica até onde o Leizilla chegou com cada norma.
    </small>
  </p>
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
    overflow-wrap: anywhere;
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
  .badge-estagio {
    border-color: var(--pico-primary);
    color: var(--pico-primary);
  }
  .badge-situacao {
    border-color: var(--pico-del-color);
    color: var(--pico-del-color);
  }
  .hit-excerpt {
    line-height: 1.45;
    margin: 0 0 0.35rem;
    color: var(--pico-color);
  }
  .no-text {
    font-style: italic;
    color: var(--pico-muted-color);
  }
  .hit-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1rem;
    font-size: 0.8rem;
    color: var(--pico-muted-color);
    margin: 0;
    padding: 0;
    border: none;
    background: none;
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
  .corpo {
    margin-top: 1.5rem;
  }
  .corpo h3 {
    font-size: 1.05rem;
  }
  .corpo li {
    overflow-wrap: anywhere;
  }
  .aviso-catalogo {
    color: var(--pico-muted-color);
    margin-top: 1rem;
  }
</style>
