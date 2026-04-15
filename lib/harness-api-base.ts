export const DEFAULT_VERCEL_BACKEND_ROUTE_PREFIX = "/backend";

function stripTrailingSlash(value: string): string {
  return value.replace(/\/$/, "");
}

export function resolveHarnessApiBaseUrl(
  env: Partial<Record<"HARNESS_API_BASE_URL" | "VERCEL_URL", string | undefined>>,
): string | null {
  const explicit = env.HARNESS_API_BASE_URL?.trim();
  if (explicit) {
    return stripTrailingSlash(explicit);
  }

  const vercelUrl = env.VERCEL_URL?.trim();
  if (vercelUrl) {
    return `https://${stripTrailingSlash(vercelUrl)}${DEFAULT_VERCEL_BACKEND_ROUTE_PREFIX}`;
  }

  return null;
}
