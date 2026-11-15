<script lang="ts">
  import { COMPLETENESS_JSON_URL, COMPLETENESS_PARQUET_URL } from '../../lib/db';
  import { formatDate } from '../../lib/format';
  import {
    decadaLabel,
    fmtCount,
    fmtPct,
    headline,
    missingList,
    parseCompletude,
    scopeNote,
    unmeasuredStages,
    type CompletudeReport,
  } from '../../lib/completude';

  let loading = $state(true);
  let report = $state<CompletudeReport | null>(null);

  $effect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!COMPLETENESS_JSON_URL) return;
        const res = await fetch(COMPLETENESS_JSON_URL);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const parsed = parseCompletude(await res.json());
        if (!cancelled) report = parsed;
      } catch {
        // Fail-open: sem o resumo, a seção diz que ainda não foi publicado.
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
    <p><small>Consultando o livro-razão de completude…</small></p>
  </div>
{:else if report == null}
  <p>
    <small>
      O livro-razão de completude ainda não foi publicado para este acervo — ele
      é montado no pipeline (<code>leizilla completeness --upload</code>) e fica
      disponível a partir da próxima release agendada.
    </small>
  </p>
{:else}
  {#if !report.catalogo.completo}
    <p class="aviso" role="note">
      <strong>Índice oficial lido em parte:</strong>
      {fmtCount(report.catalogo.paginas_lidas)} de {fmtCount(report.catalogo.paginas)}
      listas anuais. Os números abaixo valem só para os anos já lidos; um ano
      não lido é desconhecido, não "zero normas".
    </p>
  {/if}
  {#if unmeasuredStages(report.medicao)}
    <p class="aviso" role="note">
      <strong>Não medido nesta rodada:</strong>
      {unmeasuredStages(report.medicao)}. Onde aparece <code>?</code>, leia "não
      foi possível medir", nunca zero.
    </p>
  {/if}

  <div class="tipos">
    {#each report.tipos as t (t.tipo)}
      {@const faltantes = missingList(t)}
      <article data-tipo={t.tipo}>
        <h3>{headline(t)}</h3>
        {#if t.pct_preservadas != null}
          <progress
            value={t.pct_preservadas}
            max="100"
            aria-label={`${t.rotulo}: ${fmtPct(t.pct_preservadas)} preservadas`}
          ></progress>
        {/if}
        <p class="resumo">
          {fmtPct(t.pct_preservadas)} preservadas · {fmtCount(t.com_texto)} com texto ·
          {fmtCount(t.estruturadas)} estruturadas ·
          <strong>{fmtCount(t.faltantes)} faltando</strong>
        </p>
        <p class="escopo"><small>{scopeNote(t)}</small></p>

        <details>
          <summary>Por década</summary>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Década</th>
                  <th scope="col">Listadas</th>
                  <th scope="col">Preservadas</th>
                  <th scope="col">%</th>
                  <th scope="col">Com texto</th>
                  <th scope="col">Legíveis</th>
                  <th scope="col">Estruturadas</th>
                  <th scope="col">Faltando</th>
                  <th scope="col">Anos lidos</th>
                </tr>
              </thead>
              <tbody>
                {#each t.por_decada as d (d.decada)}
                  <tr>
                    <th scope="row">{decadaLabel(d.decada)}</th>
                    <td>{fmtCount(d.listadas)}</td>
                    <td>{fmtCount(d.preservadas)}</td>
                    <td>{fmtPct(d.pct_preservadas)}</td>
                    <td>{fmtCount(d.com_texto)}</td>
                    <td>{fmtCount(d.legiveis)}</td>
                    <td>{fmtCount(d.estruturadas)}</td>
                    <td>{fmtCount(d.faltantes)}</td>
                    <td>{d.anos - d.anos_desconhecidos} de {d.anos}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </details>

        {#if t.faltantes != null && t.faltantes > 0}
          <details>
            <summary>Quais faltam ({fmtCount(t.faltantes)})</summary>
            <p class="numeros">
              {faltantes.text}{#if faltantes.omitted > 0}
                … e mais {fmtCount(faltantes.omitted)}{/if}
            </p>
            <p>
              <small>
                Números das normas listadas no índice oficial e ainda sem arquivo
                preservado. A lista completa, com data e ementa de cada uma, está
                no
                {#if COMPLETENESS_PARQUET_URL}
                  <a href={COMPLETENESS_PARQUET_URL} rel="external">completeness.parquet</a>
                {:else}
                  completeness.parquet
                {/if}
                (<code>situacao = 'listada' AND NOT preservada</code>).
              </small>
            </p>
          </details>
        {/if}

        {#if t.fora_do_indice > 0 || t.indice_incompleto > 0}
          <p class="escopo">
            <small>
              {#if t.fora_do_indice > 0}
                {fmtCount(t.fora_do_indice)} norma(s) no acervo não constam do índice
                oficial.
              {/if}
              {#if t.indice_incompleto > 0}
                {fmtCount(t.indice_incompleto)} norma(s) do acervo ainda não puderam
                ser conferidas (estão em anos do índice não lidos).
              {/if}
            </small>
          </p>
        {/if}
      </article>
    {/each}
  </div>

  <p class="note">
    <small>
      Denominador: as listas anuais oficiais da Casa Civil de Rondônia
      (Consulegis), fonte <code>{report.fonte}</code>. "Preservada" = arquivo no
      Internet Archive; "legível" = texto publicado na camada de texto do portal.
      Medido em {formatDate(report.generated_at)}; <code>?</code> significa "não
      foi possível medir", nunca zero.
      {#if report.tipos_sem_indice.length > 0}
        Tipos sem lista anual oficial (fora deste quadro):
        {report.tipos_sem_indice
          .map((s) => `${s.tipo} (${fmtCount(s.preservadas)})`)
          .join(', ')}.
      {/if}
      {#if COMPLETENESS_PARQUET_URL}
        Uma linha por norma em
        <a href={COMPLETENESS_PARQUET_URL} rel="external">completeness.parquet</a>.
      {/if}
      Reproduza com <code>leizilla completeness --ente {report.ente}</code>.
    </small>
  </p>
{/if}

<style>
  .tipos {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem;
  }
  article {
    margin: 0;
    min-width: 0;
  }
  article h3 {
    font-size: 1.1rem;
    margin-bottom: 0.5rem;
  }
  progress {
    margin-bottom: 0.5rem;
  }
  .resumo,
  .escopo {
    margin-bottom: 0.5rem;
  }
  .escopo,
  .note {
    color: var(--pico-muted-color);
  }
  .aviso {
    border-left: 0.25rem solid var(--pico-primary);
    padding: 0.5rem 0.75rem;
    font-size: 0.9rem;
  }
  details {
    margin-bottom: 0.5rem;
  }
  .table-wrap {
    overflow-x: auto;
  }
  .table-wrap table {
    margin-bottom: 0;
    font-size: 0.875rem;
  }
  .numeros {
    font-size: 0.875rem;
    overflow-wrap: anywhere;
    max-height: 14rem;
    overflow-y: auto;
  }
</style>
