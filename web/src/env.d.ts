/// <reference path="../.astro/types.d.ts" />
/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly PUBLIC_PARQUET_URL: string;
  /** Camada de texto (ADR-0015): URL canônica do textos.parquet e a que o DuckDB-WASM lê. */
  readonly PUBLIC_TEXTOS_PARQUET_URL: string;
  readonly PUBLIC_TEXTOS_SOURCE_URL: string;
  /** Base do CDN dos artefatos duckdb-wasm (self-host opcional). */
  readonly PUBLIC_DUCKDB_CDN: string;
  /** Repositório de extensões DuckDB (self-host opcional). */
  readonly PUBLIC_DUCKDB_EXT_REPO: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
