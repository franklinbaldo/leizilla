<script lang="ts">
  import { DATASET_PARQUET_URL, probeDatasetAccess, type DatasetAccessProbe } from '../lib/db';
  import { withBase } from '../lib/format';

  let { error = null }: { error?: unknown } = $props();

  const detail = $derived(
    error instanceof Error ? error.message : error ? String(error) : null,
  );

  // ADR-0014: o DuckDB-WASM lê um espelho same-origin do Parquet (publicado
  // junto do site a cada deploy), não o item do Internet Archive diretamente
  // — archive.org não envia Access-Control-Allow-Origin para .parquet (issue
  // #223), então um fetch() cross-origin do navegador nunca conseguiria ler o
  // arquivo de lá, independentemente da conexão. Um navegador nunca expõe
  // essa distinção no texto do erro (sempre um NetworkError/TypeError
  // genérico) — por isso a sonda ativa. Se o espelho falhar mas
  // dataset_meta.json (servido direto pelo IA, com CORS confirmado) carregar
  // normalmente, a causa é local a este arquivo (ex.: deploy ainda não
  // sincronizou o espelho) — mirror-unreachable. Sonda roda uma vez por
  // montagem; nunca refaz a query.
  let probe = $state<DatasetAccessProbe | null>(null);

  $effect(() => {
    let cancelled = false;
    probeDatasetAccess().then((result) => {
      if (!cancelled) probe = result;
    });
    return () => {
      cancelled = true;
    };
  });

  const mirrorUnreachable = $derived(probe === 'mirror-unreachable');
</script>

<!--
  Estado público de indisponibilidade: uma falha ao carregar o Parquet prova
  somente que este acesso falhou. Não atribuímos a causa nem inferimos que o
  acervo deixou de existir ou ainda não foi publicado — exceto no caso
  mirror-unreachable, onde a sonda confirma uma causa específica deste arquivo.
-->
<article class="unavailable">
  <header>
    <strong>Não foi possível acessar o acervo agora</strong>
  </header>
  {#if mirrorUnreachable}
    <p>
      O espelho do Parquet publicado junto com o site não respondeu, embora os metadados do
      Internet Archive (<code>dataset_meta.json</code>) estejam acessíveis normalmente — a
      causa é específica deste arquivo (por exemplo, um deploy ainda não sincronizou o
      espelho mais recente), não a sua conexão. Tentar de novo mais tarde pode resolver.
      <a href="https://github.com/franklinbaldo/leizilla/issues/223" rel="external"
        >Acompanhar issue #223</a
      >.
    </p>
  {:else}
    <p>
      A busca depende do arquivo Parquet público configurado pelo Leizilla. Neste
      acesso, o navegador não conseguiu carregá-lo. Isso pode ser temporário e não
      permite concluir que o acervo esteja ausente ou não publicado.
    </p>
  {/if}
  <p>
    Você pode tentar abrir o
    <a href={DATASET_PARQUET_URL} rel="external">arquivo do dataset diretamente</a>,
    conferir a <a href={withBase('cobertura/')}>página de cobertura</a> ou consultar o
    <a href="https://github.com/franklinbaldo/leizilla#roadmap" rel="external">roadmap do projeto</a>.
  </p>
  {#if detail}
    <details>
      <summary>Detalhe técnico</summary>
      <p><small>Falha ao carregar <code>{DATASET_PARQUET_URL}</code>: {detail}</small></p>
    </details>
  {/if}
</article>

<style>
  .unavailable {
    border-left: 4px solid var(--pico-primary, #0056b3);
  }
  .unavailable code {
    word-break: break-all;
  }
</style>
