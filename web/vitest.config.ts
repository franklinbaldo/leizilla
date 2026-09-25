import path from 'path';
import { fileURLToPath } from 'url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Same client-build alias astro.config.mjs uses for the real app — needed here
// too so .test.ts files can `import { mount, unmount } from 'svelte'` and get
// the client runtime (mount/unmount only exist there), not svelte's server/SSR
// build. Vitest runs modules through Vite's SSR pipeline by default, which
// would otherwise resolve bare 'svelte' to the server build.
//
// Deliberately an explicit alias, not a global `resolve.conditions: ['browser']`
// — the latter also flips @duckdb/duckdb-wasm onto its browser Worker bundle
// (top-level `ReferenceError: Worker is not defined` in jsdom), breaking
// db.test.ts.
const svelteClient = path.resolve(__dirname, 'node_modules/svelte/src/index-client.js');

export default defineConfig({
  // svelte() lets .test.ts files import .svelte components directly (mount/unmount
  // from 'svelte', jsdom env below) for the Dados/Versoes fixture tests — see
  // Versoes.test.ts. Pure-logic tests (model.test.ts, format.test.ts, db.test.ts)
  // don't need it but are unaffected.
  plugins: [svelte({ compilerOptions: { dev: true } })],
  resolve: {
    alias: [{ find: /^svelte$/, replacement: svelteClient }],
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
});
