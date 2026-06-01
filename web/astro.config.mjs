import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const svelteClient = path.resolve(__dirname, 'node_modules/svelte/src/index-client.js');
const svelteLegacy = path.resolve(__dirname, 'node_modules/svelte/src/legacy/legacy-client.js');
const svelteReactivity = path.resolve(__dirname, 'node_modules/svelte/src/reactivity/index-client.js');
const svelteStore = path.resolve(__dirname, 'node_modules/svelte/src/store/index-client.js');

export default defineConfig({
  integrations: [svelte()],
  output: 'static',
  site: 'https://franklinbaldo.github.io',
  base: '/leizilla',
  vite: {
    resolve: {
      alias: [
        { find: /^svelte$/, replacement: svelteClient },
        { find: /^svelte\/legacy$/, replacement: svelteLegacy },
        { find: /^svelte\/reactivity$/, replacement: svelteReactivity },
        { find: /^svelte\/store$/, replacement: svelteStore },
      ],
    },
    optimizeDeps: {
      exclude: [
        '@duckdb/duckdb-wasm',
        'svelte',
        'svelte/legacy',
        'svelte/reactivity',
        'svelte/store',
      ],
    },
  },
});
