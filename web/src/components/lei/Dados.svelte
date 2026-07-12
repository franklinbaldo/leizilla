<script lang="ts">
  // Reuso: exporta as linhas já buscadas (JSON/CSV) e aponta para o dataset
  // completo — o mesmo Parquet que esta página consulta no navegador.
  import type { LeiRow } from '../../lib/db';
  import { DATASET_IA_ITEM, DATASET_META_URL, DATASET_PARQUET_URL } from '../../lib/db';
  import { iaDetailsUrl } from '../../lib/format';
  import { downloadBlob, rowsToCsv, rowsToJson } from './model';

  let { rows, leiId }: { rows: LeiRow[]; leiId: string } = $props();

  const urnLex = $derived(rows[0]?.urn_lex_lei ?? null);

  function baixarJson() {
    downloadBlob(`${leiId}.json`, rowsToJson(rows), 'application/json');
  }
  function baixarCsv() {
    downloadBlob(`${leiId}.csv`, rowsToCsv(rows), 'text/csv;charset=utf-8');
  }
</script>

<h4>Esta norma</h4>
<p>
  {rows.length} linha{rows.length !== 1 ? 's' : ''} (dispositivo × versão),
  exatamente como consultadas do dataset por este navegador:
</p>
<div class="downloads">
  <button type="button" onclick={baixarJson}>Baixar JSON</button>
  <button type="button" onclick={baixarCsv}>Baixar CSV</button>
</div>

<h4>Dataset completo</h4>
<ul>
  <li>
    <a href={DATASET_PARQUET_URL} target="_blank" rel="noopener noreferrer">
      Parquet <code>versoes</code>
    </a>
    — o arquivo único que alimenta toda esta interface (DuckDB-WASM).
  </li>
  {#if DATASET_IA_ITEM}
    <li>
      <a href={iaDetailsUrl(DATASET_IA_ITEM)} target="_blank" rel="noopener noreferrer">
        Item do dataset no Internet Archive
      </a>
      — <code>{DATASET_IA_ITEM}</code>
    </li>
  {/if}
  {#if DATASET_META_URL}
    <li>
      <a href={DATASET_META_URL} target="_blank" rel="noopener noreferrer">
        dataset_meta.json
      </a>
      — contagem de linhas, hash e SHA do commit gerador.
    </li>
  {/if}
</ul>

<h4>Identificadores</h4>
{#if urnLex}
  <p>
    URN-LEX da norma: <code>{urnLex}</code>
  </p>
{:else}
  <p>Esta norma ainda não tem URN-LEX atribuída no dataset (data de publicação desconhecida).</p>
{/if}
<p>
  <small>
    Cada dispositivo tem <code>urn_dispositivo</code> = URN-LEX da norma +
    <code>"!"</code> + caminho do dispositivo (ex.:
    <code>…!art-5-par-2</code>) — um identificador estável e citável por
    artigo, parágrafo, inciso ou alínea.
  </small>
</p>

<style>
  h4 {
    margin: 1.25rem 0 0.5rem;
    font-size: 1.05em;
  }
  .downloads {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .downloads button {
    width: auto;
    margin: 0;
  }
  code {
    word-break: break-all;
  }
</style>
