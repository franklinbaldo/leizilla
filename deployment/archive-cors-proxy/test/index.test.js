import assert from "node:assert/strict";
import { it } from "node:test";
import { handleRequest, parseDownloadPath } from "../src/index.js";

it("accepts the canonical dataset path", () => {
  assert.deepEqual(
    parseDownloadPath("/download/leizilla-dataset-ro-v0-latest/versoes.parquet"),
    { item: "leizilla-dataset-ro-v0-latest", file: "versoes.parquet" },
  );
});

it("rejects an item outside the leizilla-dataset-* namespace", () => {
  assert.equal(parseDownloadPath("/download/some-other-item/versoes.parquet"), null);
});

it("rejects a non-parquet file under an allowed item", () => {
  assert.equal(parseDownloadPath("/download/leizilla-dataset-ro-v0-latest/versoes.csv"), null);
});

it("answers CORS preflight without contacting upstream", async () => {
  const request = new Request("https://proxy.example/download/leizilla-dataset-ro-v0-latest/versoes.parquet", {
    method: "OPTIONS",
  });
  const fetchImpl = () => {
    throw new Error("upstream should not be called for OPTIONS");
  };
  const response = await handleRequest(request, fetchImpl);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get("access-control-allow-origin"), "*");
});

it("rejects methods other than GET/HEAD/OPTIONS", async () => {
  const request = new Request("https://proxy.example/download/leizilla-dataset-ro-v0-latest/versoes.parquet", {
    method: "POST",
  });
  const response = await handleRequest(request);
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("access-control-allow-origin"), "*");
});

it("returns 404 for a path that is not an allowed dataset download", async () => {
  const request = new Request("https://proxy.example/download/some-other-item/file.parquet");
  const response = await handleRequest(request);
  assert.equal(response.status, 404);
});

it("proxies a matching request to archive.org, forwarding Range and adding CORS", async () => {
  const request = new Request(
    "https://proxy.example/download/leizilla-dataset-ro-v0-latest/versoes.parquet",
    { headers: { range: "bytes=0-1" } },
  );

  let capturedUrl;
  let capturedRange;
  const fetchImpl = (url, init) => {
    capturedUrl = url;
    capturedRange = init.headers.get("range");
    return Promise.resolve(
      new Response("body", {
        status: 206,
        headers: { "content-range": "bytes 0-1/2", "content-type": "application/octet-stream" },
      }),
    );
  };

  const response = await handleRequest(request, fetchImpl);
  assert.equal(
    capturedUrl,
    "https://archive.org/download/leizilla-dataset-ro-v0-latest/versoes.parquet",
  );
  assert.equal(capturedRange, "bytes=0-1");
  assert.equal(response.status, 206);
  assert.equal(response.headers.get("access-control-allow-origin"), "*");
  assert.equal(response.headers.get("content-range"), "bytes 0-1/2");
});

it("returns 502 when the upstream fetch fails", async () => {
  const request = new Request("https://proxy.example/download/leizilla-dataset-ro-v0-latest/versoes.parquet");
  const fetchImpl = () => Promise.reject(new Error("network down"));
  const response = await handleRequest(request, fetchImpl);
  assert.equal(response.status, 502);
});
