import assert from "node:assert/strict";
import test from "node:test";

import { resolveHarnessApiBaseUrl } from "../../lib/harness-api-base";

test("prefers explicit HARNESS_API_BASE_URL and strips a trailing slash", () => {
  const resolved = resolveHarnessApiBaseUrl({
    HARNESS_API_BASE_URL: "https://api.example.com/",
  });

  assert.equal(resolved, "https://api.example.com");
});

test("prefers same-project Vercel routing over explicit overrides in hosted deployments", () => {
  const resolved = resolveHarnessApiBaseUrl({
    HARNESS_API_BASE_URL: "https://stale-backend.example.com/",
    VERCEL_URL: "harness-preview.vercel.app",
  });

  assert.equal(resolved, "https://harness-preview.vercel.app/backend");
});

test("derives the hosted backend url from VERCEL_URL when no override is set", () => {
  const resolved = resolveHarnessApiBaseUrl({
    VERCEL_URL: "harness-preview.vercel.app",
  });

  assert.equal(resolved, "https://harness-preview.vercel.app/backend");
});

test("returns null when neither local override nor hosted deployment context exists", () => {
  const resolved = resolveHarnessApiBaseUrl({});

  assert.equal(resolved, null);
});
