#!/usr/bin/env node

import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(scriptPath), "..");
const stageRoot = path.join(repoRoot, ".harness-local-dashboard-build");
const stageSource = path.join(stageRoot, "source");
const outputDir = path.join(repoRoot, "dist", "local-dashboard");
const appSource = path.join(repoRoot, "app");
const appTarget = path.join(stageSource, "app");

async function copyIfExists(source, target) {
  if (existsSync(source)) {
    await cp(source, target, {
      recursive: true,
      force: true,
      verbatimSymlinks: true,
    });
  }
}

async function prepareStage() {
  await rm(stageRoot, { recursive: true, force: true });
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(stageSource, { recursive: true });

  await copyIfExists(appSource, appTarget);
  await rm(path.join(appTarget, "api"), { recursive: true, force: true });

  for (const entry of [
    "components",
    "lib",
    "public",
    "next.config.ts",
    "package.json",
    "postcss.config.mjs",
    "tsconfig.json",
    "next-env.d.ts",
  ]) {
    await copyIfExists(path.join(repoRoot, entry), path.join(stageSource, entry));
  }
}

function runNextBuild() {
  const result = spawnSync("pnpm", ["exec", "next", "build", stageSource], {
    cwd: repoRoot,
    env: {
      ...process.env,
      HARNESS_DASHBOARD_OUTPUT: "export",
      NEXT_PUBLIC_HARNESS_DASHBOARD_MODE: "local-static",
      NEXT_TELEMETRY_DISABLED: "1",
    },
    stdio: "inherit",
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

async function writeManifest() {
  const manifest = {
    format_version: 1,
    mode: "local-static",
    base_path: "/dashboard",
    api_base: "same-origin",
    entrypoints: [
      "/dashboard/",
      "/dashboard/tasks/",
      "/dashboard/verification/",
      "/dashboard/reconciliation/",
      "/dashboard/reviews/",
    ],
  };
  await writeFile(
    path.join(outputDir, "dashboard-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf-8",
  );
}

async function main() {
  await prepareStage();
  runNextBuild();
  await cp(path.join(stageSource, "out"), outputDir, {
    recursive: true,
    force: true,
  });
  await writeManifest();
  console.log(`Built local dashboard assets at ${path.relative(repoRoot, outputDir)}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
