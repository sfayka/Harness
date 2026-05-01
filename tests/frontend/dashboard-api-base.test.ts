import assert from "node:assert/strict";
import test from "node:test";

import { resolveDashboardApiBasePath } from "../../lib/harness-api";

type TestWindow = {
  __HARNESS_DASHBOARD_CONFIG__?: {
    apiBaseUrl?: string;
  };
};

function resetEnvironment() {
  delete process.env.NEXT_PUBLIC_PROOFLINE_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_HARNESS_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_HARNESS_DASHBOARD_MODE;
  delete (globalThis as { window?: TestWindow }).window;
}

test.afterEach(() => {
  resetEnvironment();
});

test("uses the Proofline Next proxy by default", () => {
  resetEnvironment();

  assert.equal(resolveDashboardApiBasePath(), "/api/proofline");
});

test("uses same-origin API paths for local static dashboard builds", () => {
  resetEnvironment();
  process.env.NEXT_PUBLIC_HARNESS_DASHBOARD_MODE = "local-static";

  assert.equal(resolveDashboardApiBasePath(), "");
});

test("uses explicit Proofline public API base URL when configured", () => {
  resetEnvironment();
  process.env.NEXT_PUBLIC_PROOFLINE_API_BASE_URL = "http://127.0.0.1:8765/";

  assert.equal(resolveDashboardApiBasePath(), "http://127.0.0.1:8765");
});

test("uses Harness public API base URL as compatibility fallback", () => {
  resetEnvironment();
  process.env.NEXT_PUBLIC_HARNESS_API_BASE_URL = "http://127.0.0.1:8765/";

  assert.equal(resolveDashboardApiBasePath(), "http://127.0.0.1:8765");
});

test("prefers Proofline public API base URL over Harness compatibility fallback", () => {
  resetEnvironment();
  process.env.NEXT_PUBLIC_PROOFLINE_API_BASE_URL = "http://proofline.example/";
  process.env.NEXT_PUBLIC_HARNESS_API_BASE_URL = "http://harness.example/";

  assert.equal(resolveDashboardApiBasePath(), "http://proofline.example");
});

test("ignores blank Proofline public API base URL before using Harness fallback", () => {
  resetEnvironment();
  process.env.NEXT_PUBLIC_PROOFLINE_API_BASE_URL = "  ";
  process.env.NEXT_PUBLIC_HARNESS_API_BASE_URL = "http://harness.example/";

  assert.equal(resolveDashboardApiBasePath(), "http://harness.example");
});

test("runtime dashboard config wins over build-time environment", () => {
  resetEnvironment();
  process.env.NEXT_PUBLIC_PROOFLINE_API_BASE_URL = "http://proofline-build.example/";
  process.env.NEXT_PUBLIC_HARNESS_API_BASE_URL = "http://build-time.example/";
  (globalThis as { window?: TestWindow }).window = {
    __HARNESS_DASHBOARD_CONFIG__: {
      apiBaseUrl: "http://runtime.example/",
    },
  };

  assert.equal(resolveDashboardApiBasePath(), "http://runtime.example");
});
