import { afterEach, describe, expect, it, vi } from 'vitest';
import { datasetIaItemFromParquetUrl, getDuckdbSourceUrl, probeDatasetAccess } from './db';

describe('datasetIaItemFromParquetUrl', () => {
  it('extracts the item from the canonical Internet Archive URL', () => {
    expect(
      datasetIaItemFromParquetUrl(
        'https://archive.org/download/leizilla-dataset-ro-v0-latest/versoes.parquet',
      ),
    ).toBe('leizilla-dataset-ro-v0-latest');
  });

  it('preserves the same item identity when the parquet is served by a CORS proxy', () => {
    expect(
      datasetIaItemFromParquetUrl(
        'https://leizilla-cors.example.workers.dev/download/leizilla-dataset-ro-v0-latest/versoes.parquet',
      ),
    ).toBe('leizilla-dataset-ro-v0-latest');
  });

  it('returns null when the URL does not preserve the IA download pathname', () => {
    expect(datasetIaItemFromParquetUrl('https://example.org/versoes.parquet')).toBeNull();
    expect(datasetIaItemFromParquetUrl('not a url')).toBeNull();
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getDuckdbSourceUrl', () => {
  // Regression: astro.config.mjs's `base: '/leizilla'` has no trailing slash, and
  // import.meta.env.BASE_URL preserves that exactly — naively concatenating
  // `${base}data/...` produced `/leizilladata/ro/versoes.parquet` in production
  // (confirmed live: a 404, DuckDB-WASM never found the mirror). getDuckdbSourceUrl
  // must normalize the join the same way web/src/lib/format.ts's withBase() does.
  it('inserts exactly one slash between a base without a trailing slash and the data path', () => {
    const originalBase = import.meta.env.BASE_URL;
    (import.meta.env as Record<string, string>).BASE_URL = '/leizilla';
    try {
      const url = getDuckdbSourceUrl();
      expect(url).not.toContain('leizilladata');
      expect(new URL(url).pathname).toBe('/leizilla/data/ro/versoes.parquet');
    } finally {
      (import.meta.env as Record<string, string>).BASE_URL = originalBase;
    }
  });
});

describe('probeDatasetAccess', () => {
  // ADR-0014: DuckDB-WASM reads a same-origin mirror of the Parquet by default
  // (getDuckdbSourceUrl()), not the archive.org item directly — archive.org never
  // sends Access-Control-Allow-Origin for .parquet (issue #223), so a browser
  // fetch() to it would never succeed regardless of network health. This probe
  // tells a genuinely-down mirror apart from an unrelated network outage.
  it('returns "ok" when the mirror URL itself is reachable', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 206 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(probeDatasetAccess()).resolves.toBe('ok');
    expect(fetchMock).toHaveBeenCalledWith(
      getDuckdbSourceUrl(),
      expect.objectContaining({ headers: { Range: 'bytes=0-0' } }),
    );
  });

  it('returns "mirror-unreachable" when only the mirror fetch fails', async () => {
    const sourceUrl = getDuckdbSourceUrl();
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === sourceUrl) {
        return Promise.reject(new TypeError('Failed to fetch'));
      }
      return Promise.resolve(new Response(null, { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(probeDatasetAccess()).resolves.toBe('mirror-unreachable');
  });

  it('returns "unavailable" when the mirror responds with a non-ok status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404 })));

    await expect(probeDatasetAccess()).resolves.toBe('unavailable');
  });

  it('returns "unavailable" when both the mirror and control fetches fail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(probeDatasetAccess()).resolves.toBe('unavailable');
  });
});
