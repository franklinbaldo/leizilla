const DEFAULT_ITEM = "leizilla-dataset-ro-v0-latest";
const DEFAULT_FILE = "versoes.parquet";

function requireHeader(response, name, expected) {
  const actual = response.headers.get(name);
  if (actual !== expected) {
    throw new Error(`${name}: expected ${expected}, got ${actual ?? "<missing>"}`);
  }
}

export async function verifyProxy({
  baseUrl,
  item = DEFAULT_ITEM,
  file = DEFAULT_FILE,
  fetchImpl = fetch,
}) {
  const target = new URL(`/download/${item}/${file}`, baseUrl).toString();

  const preflight = await fetchImpl(target, {
    method: "OPTIONS",
    headers: {
      origin: "https://example.invalid",
      "access-control-request-method": "GET",
      "access-control-request-headers": "range",
    },
  });
  if (preflight.status !== 204) {
    throw new Error(`OPTIONS: expected 204, got ${preflight.status}`);
  }
  requireHeader(preflight, "access-control-allow-origin", "*");

  const head = await fetchImpl(target, { method: "HEAD" });
  if (!head.ok) {
    throw new Error(`HEAD: expected 2xx, got ${head.status}`);
  }
  requireHeader(head, "access-control-allow-origin", "*");

  const ranged = await fetchImpl(target, {
    method: "GET",
    headers: { range: "bytes=0-1" },
  });
  if (ranged.status !== 206) {
    throw new Error(`Range GET: expected 206, got ${ranged.status}`);
  }
  requireHeader(ranged, "access-control-allow-origin", "*");
  const contentRange = ranged.headers.get("content-range");
  if (!contentRange?.startsWith("bytes 0-1/")) {
    throw new Error(
      `content-range: expected bytes 0-1/*, got ${contentRange ?? "<missing>"}`,
    );
  }

  return {
    target,
    optionsStatus: preflight.status,
    headStatus: head.status,
    rangeStatus: ranged.status,
    contentRange,
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const baseUrl = process.argv[2] ?? process.env.PROXY_BASE_URL;
  if (!baseUrl) {
    console.error("usage: node verify.mjs https://<worker>.workers.dev");
    process.exitCode = 2;
  } else {
    try {
      const result = await verifyProxy({ baseUrl });
      console.log(JSON.stringify(result, null, 2));
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
}
