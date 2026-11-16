<script lang="ts">
  // Bloco do catálogo oficial na página de uma norma estruturada (ADR-0017): título, data,
  // ementa e situação do índice da Casa Civil, e as relações com outras normas. Some sem
  // aviso se o catálogo não está publicado ou a norma não consta dele.
  import type { CatalogoRow } from '../../lib/catalogo';
  import { catalogoAvailable, getCatalogoDeLei } from '../../lib/catalogoDb';
  import NormaCabecalho from './NormaCabecalho.svelte';
  import Relacoes from './Relacoes.svelte';

  let { leiId }: { leiId: string } = $props();

  let row = $state<CatalogoRow | null>(null);

  $effect(() => {
    let cancelado = false;
    catalogoAvailable()
      .then((ok) => (ok ? getCatalogoDeLei(leiId) : null))
      .then((found) => {
        if (!cancelado) row = found;
      })
      .catch(() => {
        if (!cancelado) row = null;
      });
    return () => {
      cancelado = true;
    };
  });
</script>

{#if row}
  <NormaCabecalho {row} compacto />
  <Relacoes normaId={row.norma_id} />
{/if}
