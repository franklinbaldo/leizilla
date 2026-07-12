<script lang="ts">
  import { DATASET_PARQUET_URL } from '../lib/db';
  import { withBase } from '../lib/format';

  let { error = null }: { error?: unknown } = $props();

  const detail = $derived(
    error instanceof Error ? error.message : error ? String(error) : null,
  );
</script>

<!--
  Estado público de cobertura/disponibilidade (PRD §10.4, RFC-0004 passo 6):
  quando o Parquet não carrega, o visitante vê o que o projeto É e onde ele
  está na esteira de publicação — não um stack trace.
-->
<article class="unavailable">
  <header>
    <strong>O acervo ainda não está no ar</strong>
  </header>
  <p>
    O Leizilla preserva, estrutura e audita legislação pública. O primeiro
    dataset (Rondônia v0) está em fase de ativação — o pipeline está pronto,
    mas a coleção ainda não foi publicada no Internet Archive, então a busca
    não tem dados para consultar neste momento.
  </p>
  <p>
    Acompanhe o que já existe e o que falta na
    <a href={withBase('cobertura/')}>página de cobertura</a> ou no
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
