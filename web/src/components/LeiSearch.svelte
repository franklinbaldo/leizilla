<script lang="ts">
  import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
  import { catalogoAvailable } from '../lib/catalogoDb';
  import CatalogoBusca from './catalogo/CatalogoBusca.svelte';
  import LeiSearchUI from './LeiSearchUI.svelte';

  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 2,
        staleTime: 5 * 60 * 1000, // 5 min cache
      },
    },
  });

  // ADR-0017: com o catálogo oficial publicado a busca cobre todo o índice da Casa Civil;
  // sem ele (ainda não publicado, ou espelho fora do ar) vale a busca anterior sobre
  // `versoes` + `textos`, que também reporta a indisponibilidade do dataset.
  let modo = $state<'carregando' | 'catalogo' | 'anterior'>('carregando');
  $effect(() => {
    catalogoAvailable().then(
      (ok) => (modo = ok ? 'catalogo' : 'anterior'),
      () => (modo = 'anterior'),
    );
  });
</script>

<QueryClientProvider {client}>
  {#if modo === 'catalogo'}
    <CatalogoBusca />
  {:else if modo === 'anterior'}
    <LeiSearchUI />
  {:else}
    <p aria-busy="true">Carregando…</p>
  {/if}
</QueryClientProvider>
