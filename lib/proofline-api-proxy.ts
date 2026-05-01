import { NextRequest, NextResponse } from "next/server";

import { resolveHarnessApiBaseUrl } from "@/lib/harness-api-base";

function getBaseUrl(): string | null {
  return resolveHarnessApiBaseUrl({
    HARNESS_API_BASE_URL: process.env.HARNESS_API_BASE_URL,
    VERCEL_URL: process.env.VERCEL_URL,
  });
}

export async function proxyProoflineApiRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    return NextResponse.json(
      {
        error:
          "Proofline API base URL could not be resolved. Set HARNESS_API_BASE_URL locally or deploy behind Vercel Services.",
      },
      { status: 503 },
    );
  }

  const params = await context.params;
  const upstreamPath = params.path.join("/");
  const upstreamUrl = new URL(`${baseUrl}/${upstreamPath}`);
  upstreamUrl.search = request.nextUrl.search;

  try {
    const upstreamResponse = await fetch(upstreamUrl, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    const body = await upstreamResponse.text();
    return new NextResponse(body, {
      status: upstreamResponse.status,
      headers: {
        "Content-Type":
          upstreamResponse.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: `Proofline API proxy could not reach ${upstreamUrl.origin}: ${
          error instanceof Error ? error.message : "unknown error"
        }`,
      },
      { status: 502 },
    );
  }
}
