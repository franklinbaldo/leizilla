import { afterEach, describe, expect, it, vi } from 'vitest';
import { DATASET_PARQUET_URL, datasetIaItemFromParquetUrl, probeDatasetAccess } from './db';

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

describe('probeDatasetAccess', () => {
  // issue #167/#223: archive.org sends Access-Control-Allow-Origin for
  // dataset_meta.json but not for the .parquet file of the same item — a
  // permanent, file-specific CORS gap that a browser only ever surfaces as a
  // generic network error, indistinguishable from a transient outage. This
  // probe is how the UI tells the two apart.
  it('returns "ok" when the parquet URL itself is reachable', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 206 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(probeDatasetAccess()).resolves.toBe('ok');
    expect(fetchMock).toHaveBeenCalledWith(
      DATASET_PARQUET_URL,
      expect.objectContaining({ headers: { Range: 'bytes=0-0' } }),
    );
  });

  it('returns "cors-blocked" when only the parquet fetch fails', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === DATASET_PARQUET_URL) {
        return Promise.reject(new TypeError('Failed to fetch'));
      }
      return Promise.resolve(new Response(null, { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(probeDatasetAccess()).resolves.toBe('cors-blocked');
  });

  it('returns "unavailable" when both the parquet and control fetches fail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(probeDatasetAccess()).resolves.toBe('unavailable');
  });
});
