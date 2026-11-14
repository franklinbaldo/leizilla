<script lang="ts">
  // /lei/?id=… — um raw_id (leizilla-raw-…) abre a camada de texto (ADR-0015);
  // qualquer outro id continua na página da norma estruturada.
  import { isTextoId } from '../../lib/db';
  import LeiPage from './LeiPage.svelte';
  import TextoPage from './TextoPage.svelte';

  const id = new URLSearchParams(location.search).get('id')?.trim() ?? '';
</script>

{#if isTextoId(id)}
  <TextoPage textoId={id} />
{:else}
  <LeiPage />
{/if}
