<script lang="ts">
  import {
    getCoverageStats,
    getCoverageByEnte,
    type CoverageStats,
    type EnteCoverage,
  } from '../../lib/db';
  import { formatEnte, formatDate } from '../../lib/format';
  import DatasetUnavailable from '../DatasetUnavailable.svelte';

  let loading = $state(true);
  let error = $state<unknown>(null);
  let stats = $state<CoverageStats | null>(null);
  let porEnte = $state<EnteCoverage[]>([]);

  // DuckDB pode devolver BIGINT → normaliza antes de localizar.
  const fmt = (n: number | bigint) => Number(n).toLocaleString('pt-BR');

  const anos = $derived(
    stats && stats.ano_min != null && stats.ano_max != null
      ? stats.ano_min === stats.ano_max
        ? String(stats.ano_min)
        : `${stats.ano_min}–${stats.ano_max}`
      : '—',
  );

  $effect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, e] = await Promise.all([getCoverageStats(), getCoverageByEnte()]);
        if (cancelled) return;
        stats = s;
        porEnte = e;
      } catch (err) {
        if (!cancelled) error = err;
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
  <div aria-busy="true">
    <p><small>Consultando o dataset publicado…</small></p>
  </div>
{:else if error != null}
  <!-- Aqui o painel completo é o conteúdo correto: esta seção EXISTE para
       medir o que está publicado, e "nada publicado" é o estado real. -->
  <DatasetUnavailable {error} />
{:else if stats == null || stats.leis === 0}
  <DatasetUnavailable />
{:else}
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
    <div class="stat">
      <strong>{fmt(stats.leis_revogadas)}</strong>
      <span>leis revogadas</span>
    </div>
    <div class="stat">
      <strong>{fmt(stats.leis_com_divergencia)}</strong>
      <span>leis com divergência entre fontes</span>
    </div>
    <div class="stat">
      <strong>{anos}</strong>
      <span>intervalo de anos</span>
    </div>
  </div>
  <p class="note">
    <small>
      Compilação vigente em {formatDate(stats.vigente_em_max)}. Todos os números
      desta seção são calculados no seu navegador a partir do Parquet publicado —
      são os mesmos dados da busca, sem intermediários.
    </small>
  </p>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th scope="col">Ente</th>
          <th scope="col">Leis</th>
          <th scope="col">Dispositivos</th>
          <th scope="col">Anos</th>
        </tr>
      </thead>
      <tbody>
        {#each porEnte as e (e.ente)}
          <tr>
            <td>{formatEnte(e.ente)}</td>
            <td>{fmt(e.leis)}</td>
            <td>{fmt(e.dispositivos)}</td>
            <td>
              {#if e.ano_min != null && e.ano_max != null}
                {e.ano_min === e.ano_max ? e.ano_min : `${e.ano_min}–${e.ano_max}`}
              {:else}
                —
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    gap: 0.75rem;
    margin-bottom: 0.75rem;
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
  .note {
    color: var(--pico-muted-color);
  }
  .table-wrap {
    overflow-x: auto;
  }
  .table-wrap table {
    margin-bottom: 0;
  }
</style>
