<script lang="ts">
  // Página de uma norma do catálogo oficial (/lei/?id=leizilla-raw-…, ADR-0017): o
  // cabeçalho do índice e as relações vêm primeiro; o texto OCR da camada de texto
  // (ADR-0015), quando há, vem embaixo. Sem catálogo publicado, cai na página de texto
  // anterior.
  import { estagioDe, ESTAGIO_DESCRICAO, type CatalogoRow } from '../../lib/catalogo';
  import { catalogoAvailable, getNormaCatalogo } from '../../lib/catalogoDb';
  import { getStructuredLeiId } from '../../lib/db';
  import { leiUrl, withBase } from '../../lib/format';
  import DatasetUnavailable from '../DatasetUnavailable.svelte';
  import TextoPage from '../lei/TextoPage.svelte';
  import NormaCabecalho from './NormaCabecalho.svelte';
  import Relacoes from './Relacoes.svelte';

  let { normaId }: { normaId: string } = $props();

  let row = $state<CatalogoRow | null>(null);
  let comCatalogo = $state(false);
  let estruturadaId = $state<string | null>(null);
  let loading = $state(true);
  let error = $state<unknown>(null);

  const estagio = $derived(row ? estagioDe(row) : 'nao-medido');

  $effect(() => {
    let cancelado = false;
    (async () => {
      const ok = await catalogoAvailable();
      const found = ok ? await getNormaCatalogo(normaId) : null;
      const leiId = found?.estruturada ? await getStructuredLeiId(normaId).catch(() => null) : null;
      return { ok, found, leiId };
    })().then(
      ({ ok, found, leiId }) => {
        if (cancelado) return;
        comCatalogo = ok && found !== null;
        row = found;
        estruturadaId = leiId;
        loading = false;
      },
      (err) => {
        if (cancelado) return;
        error = err;
        loading = false;
      },
    );
    return () => {
      cancelado = true;
    };
  });

  $effect(() => {
    if (row) document.title = `${row.titulo} — Leizilla`;
  });
</script>

{#if error}
  <DatasetUnavailable {error} />
{:else if loading}
  <p aria-busy="true">Carregando a norma…</p>
{:else if !comCatalogo || !row}
  <TextoPage textoId={normaId} />
{:else}
  <NormaCabecalho {row} />

  {#if estruturadaId}
    <p class="leitura-estruturada">
      <a href={leiUrl(estruturadaId)} role="button">Ler a versão estruturada desta norma</a>
    </p>
  {/if}

  <Relacoes {normaId} />

  {#if row.legivel !== false}
    <TextoPage textoId={normaId} embedded />
  {:else}
    <section aria-labelledby="titulo-sem-texto">
      <h3 id="titulo-sem-texto">Texto</h3>
      <p>
        Ainda não há texto legível publicado para esta norma. {ESTAGIO_DESCRICAO[estagio]}
        Enquanto isso, o documento está disponível pelos links acima.
      </p>
      <p><a href={withBase('/')}>Voltar à busca</a></p>
    </section>
  {/if}
{/if}

<style>
  .leitura-estruturada {
    margin-bottom: 1.25rem;
  }
</style>
