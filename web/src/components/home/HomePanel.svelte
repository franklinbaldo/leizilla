<script lang="ts">
  import {
    getCoverageStats,
    getCoverageByEnte,
    getRecentLeis,
    DATASET_PARQUET_URL,
    DATASET_IA_ITEM,
    DATASET_META_URL,
    type CoverageStats,
    type EnteCoverage,
    type LeiRow,
  } from '../../lib/db';
  import {
    leiTitle,
    leiUrl,
    formatEnte,
    formatDate,
    withBase,
    iaDetailsUrl,
  } from '../../lib/format';

  let loading = $state(true);
  let failed = $state(false);
  let stats = $state<CoverageStats | null>(null);
  let porEnte = $state<EnteCoverage[]>([]);
  let recentes = $state<LeiRow[]>([]);

  // DuckDB pode devolver BIGINT → normaliza antes de localizar.
  const fmt = (n: number | bigint) => Number(n).toLocaleString('pt-BR');

  const anos = $derived(
    stats && stats.ano_min != null && stats.ano_max != null
      ? stats.ano_min === stats.ano_max
        ? String(stats.ano_min)
        : `${stats.ano_min}–${stats.ano_max}`
      : null,
  );

  // Dataset publicado porém vazio conta como "ainda não publicado" para o
  // visitante — não exibimos uma vitrine de zeros.
  const empty = $derived(!failed && !loading && (stats == null || stats.leis === 0));

  $effect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, e, r] = await Promise.all([
          getCoverageStats(),
          getCoverageByEnte(),
          getRecentLeis(6),
        ]);
        if (cancelled) return;
        stats = s;
        porEnte = e;
        recentes = r;
      } catch {
        // O island de busca já exibe o painel completo de indisponibilidade
        // (DatasetUnavailable); aqui degradamos para uma linha discreta.
        if (!cancelled) failed = true;
      } finally {
        if (!cancelled) loading = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

{#if loading}
  <section aria-busy="true" aria-label="Carregando panorama do acervo">
    <p><small>Carregando panorama do acervo…</small></p>
  </section>
{:else if failed || empty}
  <p class="fallback">
    <small>
      O primeiro acervo (Rondônia v0) ainda não foi publicado — veja a
      <a href={withBase('cobertura/')}>página de cobertura</a>.
    </small>
  </p>
{:else if stats}
  <section class="panel" aria-label="Panorama do acervo estruturado">
    <h2>O acervo em números</h2>
    <div class="stats">
      <div class="stat">
        <strong>{fmt(stats.leis)}</strong>
        <span>leis estruturadas</span>
      </div>
      <div class="stat">
        <strong>{fmt(stats.dispositivos)}</strong>
        <span>dispositivos</span>
      </div>
      <div class="stat">
        <strong>{fmt(stats.versoes)}</strong>
        <span>versões</span>
      </div>
      {#if anos}
        <div class="stat">
          <strong>{anos}</strong>
          <span>intervalo de anos</span>
        </div>
      {/if}
    </div>
    <p class="stats-note">
      <small>
        Estes números contam apenas o que chegou ao estágio S4 (estruturado);
        compilação vigente em {formatDate(stats.vigente_em_max)}.
        {#each porEnte as e (e.ente)}
          {' '}{formatEnte(e.ente)}: {fmt(e.leis)}
          {e.leis === 1 ? 'lei' : 'leis'}{#if e.ano_min != null && e.ano_max != null}
            &nbsp;· anos {e.ano_min}–{e.ano_max}{/if}.
        {/each}
        <a href={withBase('cobertura/')}>Ver cobertura completa</a>.
      </small>
    </p>
  </section>

  {#if recentes.length > 0}
    <section aria-label="Leis recém-incorporadas">
      <h2>Recém-incorporadas</h2>
      <div class="cards">
        {#each recentes as lei (lei.lei_id)}
          <article class="card">
            <h3><a href={leiUrl(lei.lei_id)}>{leiTitle(lei)}</a></h3>
            <p class="meta">
              <small>{formatEnte(lei.ente)} · {formatDate(lei.data_publicacao)}</small>
            </p>
            {#if lei.texto}
              <p class="excerpt">{lei.texto}</p>
            {/if}
          </article>
        {/each}
      </div>
    </section>
  {/if}

  <section aria-label="Acesso aos dados abertos">
    <article class="card dados">
      <h2>Dados abertos</h2>
      <p>
        Todo o acervo estruturado é um único arquivo Parquet (tabela
        <code>versoes</code>), o mesmo que esta página consulta no navegador.
      </p>
      <ul>
        <li>
          <a href={DATASET_PARQUET_URL} rel="external">versoes.parquet</a>
          — download direto do dataset
        </li>
        {#if DATASET_IA_ITEM}
          <li>
            <a href={iaDetailsUrl(DATASET_IA_ITEM)} rel="external">
              Item do dataset no Internet Archive
            </a>
          </li>
        {/if}
        {#if DATASET_META_URL}
          <li>
            <a href={DATASET_META_URL} rel="external">dataset_meta.json</a>
            — metadados de publicação (contagem de linhas, hash, git SHA)
          </li>
        {/if}
      </ul>
    </article>
  </section>
{/if}

<style>
  .fallback {
    color: var(--pico-muted-color);
    margin-top: 1rem;
  }
  .panel h2,
  section h2 {
    font-size: 1.15rem;
    margin-bottom: 0.75rem;
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
  }
  .stat {
    border: 1px solid var(--pico-muted-border-color);
    border-radius: var(--pico-border-radius);
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .stat strong {
    font-size: 1.4rem;
    line-height: 1.2;
  }
  .stat span {
    font-size: 0.8rem;
    color: var(--pico-muted-color);
  }
  .stats-note {
    margin-top: 0.5rem;
    color: var(--pico-muted-color);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 0.75rem;
  }
  .card {
    margin: 0;
    padding: 1rem;
  }
  .card h3 {
    font-size: 1rem;
    margin-bottom: 0.25rem;
  }
  .card .meta {
    margin-bottom: 0.5rem;
    color: var(--pico-muted-color);
  }
  .excerpt {
    margin: 0;
    font-size: 0.875rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .dados ul {
    margin-bottom: 0;
  }
</style>
