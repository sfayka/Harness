import assert from "node:assert/strict";
import test from "node:test";

import { getBlobRuntimeHealth } from "../../lib/blob-runtime-health";

test("reports Blob as unconfigured when no token is present", async () => {
  const health = await getBlobRuntimeHealth({});

  assert.deepEqual(health, {
    configured: false,
    accessible: false,
    error: null,
  });
});

test("reports Blob as accessible when the SDK call succeeds", async () => {
  const health = await getBlobRuntimeHealth(
    {
      BLOB_READ_WRITE_TOKEN: "blob_rw_token",
    },
    async () => ({ blobs: [] }),
  );

  assert.deepEqual(health, {
    configured: true,
    accessible: true,
    error: null,
  });
});

test("reports Blob as degraded when the SDK call fails", async () => {
  const health = await getBlobRuntimeHealth(
    {
      BLOB_READ_WRITE_TOKEN: "blob_rw_token",
    },
    async () => {
      throw new Error("blob probe failed");
    },
  );

  assert.deepEqual(health, {
    configured: true,
    accessible: false,
    error: "blob probe failed",
  });
});
