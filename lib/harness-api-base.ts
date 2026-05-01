export const DEFAULT_VERCEL_BACKEND_ROUTE_PREFIX = "/backend";

function stripTrailingSlash(value: string): string {
  return value.replace(/\/$/, "");
}

export function resolveHarnessApiBaseUrl(
  env: Partial<
    Record<"PROOFLINE_API_BASE_URL" | "HARNESS_API_BASE_URL" | "VERCEL_URL", string | undefined>
  >,
): string | null {
  const vercelUrl = env.VERCEL_URL?.trim();
  if (vercelUrl) {
    return `https://${stripTrailingSlash(vercelUrl)}${DEFAULT_VERCEL_BACKEND_ROUTE_PREFIX}`;
  }

  const prooflineExplicit = env.PROOFLINE_API_BASE_URL?.trim();
  const harnessExplicit = env.HARNESS_API_BASE_URL?.trim();
  const explicit = prooflineExplicit || harnessExplicit;
  if (explicit) {
    return stripTrailingSlash(explicit);
  }

  return null;
}
