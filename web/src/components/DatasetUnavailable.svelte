<script lang="ts">
  import { DATASET_PARQUET_URL } from '../lib/db';
  import { withBase } from '../lib/format';

  let { error = null }: { error?: unknown } = $props();

  const detail = $derived(
    error instanceof Error ? error.message : error ? String(error) : null,
  );
</script>

<!--
  Estado público de indisponibilidade: uma falha ao carregar o Parquet prova
  somente que este acesso falhou. Não atribuímos a causa nem inferimos que o
  acervo deixou de existir ou ainda não foi publicado.
-->
<article class="unavailable">
  <header>
    <strong>Não foi possível acessar o acervo agora</strong>
  </header>
  <p>
    A busca depende do arquivo Parquet público configurado pelo Leizilla. Neste
    acesso, o navegador não conseguiu carregá-lo. Isso pode ser temporário e não
    permite concluir que o acervo esteja ausente ou não publicado.
  </p>
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
