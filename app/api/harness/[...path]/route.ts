import { NextRequest, NextResponse } from "next/server";

const rawBaseUrl = process.env.HARNESS_API_BASE_URL?.trim() ?? "";

function getBaseUrl(): string | null {
  if (!rawBaseUrl) {
    return null;
  }
  return rawBaseUrl.replace(/\/$/, "");
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    return NextResponse.json(
      {
        error:
          "HARNESS_API_BASE_URL is not configured for this frontend deployment.",
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
        error: `Harness API proxy could not reach ${upstreamUrl.origin}: ${
          error instanceof Error ? error.message : "unknown error"
        }`,
      },
      { status: 502 },
    );
  }
}
