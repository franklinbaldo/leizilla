<script lang="ts">
  // /lei/?id=… — um raw_id (leizilla-raw-…) abre a camada de texto (ADR-0015);
  // qualquer outro id continua na página da norma estruturada. A página do raw_id mostra
  // primeiro o catálogo oficial (ADR-0017) e, se não há catálogo publicado, só o texto.
  import { isTextoId } from '../../lib/db';
  import LeiPage from './LeiPage.svelte';
  import NormaPage from '../catalogo/NormaPage.svelte';

  const id = new URLSearchParams(location.search).get('id')?.trim() ?? '';
</script>

{#if isTextoId(id)}
  <NormaPage normaId={id} />
{:else}
  <LeiPage />
{/if}
