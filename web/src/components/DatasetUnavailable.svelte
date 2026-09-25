<script lang="ts">
  import { DATASET_PARQUET_URL, probeDatasetAccess, type DatasetAccessProbe } from '../lib/db';
  import { withBase } from '../lib/format';

  let { error = null }: { error?: unknown } = $props();

  const detail = $derived(
    error instanceof Error ? error.message : error ? String(error) : null,
  );

  // issue #167/#223: um navegador nunca expõe "bloqueado por CORS" como um
  // erro distinto de "rede fora do ar" (a mensagem em `detail` é sempre um
  // NetworkError/TypeError genérico) — por isso a sonda ativa, não o texto do
  // erro. Confirmado ao vivo 2026-09-25: archive.org manda
  // Access-Control-Allow-Origin para dataset_meta.json mas não para o
  // .parquet do mesmo item (mesmo nó de armazenamento) — uma falha
  // permanente e específica deste arquivo, não uma instabilidade transitória
  // de rede. Mesma causa-raiz já corrigida no projeto irmão causaganha
  // (issue #1482/PR #1521, ainda não implantada por falta de credencial
  // Cloudflare). Sonda roda uma vez por montagem; nunca refaz a query.
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

  const corsBlocked = $derived(probe === 'cors-blocked');
</script>

<!--
  Estado público de indisponibilidade: uma falha ao carregar o Parquet prova
  somente que este acesso falhou. Não atribuímos a causa nem inferimos que o
  acervo deixou de existir ou ainda não foi publicado — exceto no caso
  cors-blocked, onde a sonda confirma uma causa específica e permanente.
-->
<article class="unavailable">
  <header>
    <strong>Não foi possível acessar o acervo agora</strong>
  </header>
  {#if corsBlocked}
    <p>
      O Internet Archive não envia cabeçalho <code>Access-Control-Allow-Origin</code>
      para este arquivo Parquet (confirmado: o mesmo item responde com CORS para
      <code>dataset_meta.json</code>, mas não para o <code>.parquet</code>). Isso bloqueia
      o navegador de ler o arquivo diretamente, independentemente da sua conexão —
      tentar de novo não vai resolver.
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
