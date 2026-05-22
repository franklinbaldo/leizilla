<script lang="ts">
  import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
  import LeiSearchUI from './LeiSearchUI.svelte';

  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 2,
        staleTime: 5 * 60 * 1000, // 5 min cache
      },
    },
  });
</script>

<QueryClientProvider {client}>
  <LeiSearchUI />
</QueryClientProvider>
