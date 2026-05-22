import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';

export default defineConfig({
  integrations: [svelte()],
  output: 'static',
  site: 'https://franklinbaldo.github.io',
  base: '/leizilla',
  vite: {
    optimizeDeps: {
      exclude: ['@duckdb/duckdb-wasm'],
    },
  },
});
