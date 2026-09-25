import assert from "node:assert/strict";
import { it } from "node:test";
import { parseDownloadPath } from "../src/index.js";

it("accepts the canonical dataset path", () => {
  assert.deepEqual(
    parseDownloadPath("/download/leizilla-dataset-ro-v0-latest/versoes.parquet"),
    { item: "leizilla-dataset-ro-v0-latest", file: "versoes.parquet" },
  );
});
