<script lang="ts">
  import { COVERAGE_JSON_URL } from '../../lib/db';
  import { formatDate } from '../../lib/format';

  interface TipoCoverage {
    tipo: string;
    s1_arquivadas: number;
    s2_identificadas: number;
    s3_com_texto: number;
    s4_estruturadas: number;
  }

  interface FonteCoverage {
    fonte: string;
    ok: boolean;
    unidentified_arquivadas: number;
    s1_arquivadas: number | null;
    s2_identificadas: number | null;
    s3_com_texto: number | null;
    s4_estruturadas: number | null;
    por_tipo: TipoCoverage[];
  }

  interface CoverageReport {
    ente: string;
    generated_at: string;
    git_sha: string | null;
    fontes: FonteCoverage[];
  }

  let loading = $state(true);
  let unavailable = $state(false);
  let report = $state<CoverageReport | null>(null);

  const fmt = (n: number | null) => (n == null ? '?' : n.toLocaleString('pt-BR'));

  $effect(() => {
    let cancelled = false;
    (async () => {
      if (!COVERAGE_JSON_URL) {
        if (!cancelled) {
          unavailable = true;
          loading = false;
        }
        return;
      }
      try {
        const res = await fetch(COVERAGE_JSON_URL);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as CoverageReport;
        if (cancelled) return;
        report = data;
      } catch {
        if (!cancelled) unavailable = true;
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
    <p><small>Consultando o funil S1–S4…</small></p>
  </div>
{:else if unavailable || report == null}
  <p>
    <small>
      O funil S1–S4 ainda não foi publicado para este acervo — a medição roda no
      pipeline (<code>leizilla coverage --upload</code>) e fica disponível a
      partir da próxima release agendada.
    </small>
  </p>
{:else}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th scope="col">Fonte</th>
          <th scope="col">Tipo</th>
          <th scope="col">S1 arquivado</th>
          <th scope="col">S2 identificado</th>
          <th scope="col">S3 com texto</th>
          <th scope="col">S4 estruturado</th>
        </tr>
      </thead>
      <tbody>
        {#each report.fontes as f (f.fonte)}
          {#if !f.ok}
            <tr>
              <td>{f.fonte}</td>
              <td colspan="5"><em>medição incompleta nesta rodada (erro de rede) — não contar como zero</em></td>
            </tr>
          {:else if f.por_tipo.length === 0}
            <tr>
              <td>{f.fonte}</td>
              <td colspan="5">
                <em>
                  {f.unidentified_arquivadas > 0
                    ? `${fmt(f.unidentified_arquivadas)} arquivadas, ainda não identificadas`
                    : 'nada arquivado ainda'}
                </em>
              </td>
            </tr>
          {:else}
            {#each f.por_tipo as t, i (t.tipo)}
              <tr>
                {#if i === 0}
                  <td rowspan={f.por_tipo.length}>{f.fonte}</td>
                {/if}
                <td>{t.tipo}</td>
                <td>{fmt(t.s1_arquivadas)}</td>
                <td>{fmt(t.s2_identificadas)}</td>
                <td>{fmt(t.s3_com_texto)}</td>
                <td>{fmt(t.s4_estruturadas)}</td>
              </tr>
            {/each}
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
  <p class="note">
    <small>
      Medido em {formatDate(report.generated_at)} direto do Internet Archive
      (não do Parquet) — <code>?</code> significa "não foi possível medir nesta
      rodada", nunca um zero real. Reproduza com
      <code>leizilla coverage --ente {report.ente}</code>.
    </small>
  </p>
{/if}

<style>
  .table-wrap {
    overflow-x: auto;
  }
  .table-wrap table {
    margin-bottom: 0;
  }
  .note {
    color: var(--pico-muted-color);
  }
</style>
