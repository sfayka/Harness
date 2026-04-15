import { NextResponse } from "next/server";

import { getBlobRuntimeHealth } from "@/lib/blob-runtime-health";

export const dynamic = "force-dynamic";

export async function GET() {
  const blob = await getBlobRuntimeHealth({
    BLOB_READ_WRITE_TOKEN: process.env.BLOB_READ_WRITE_TOKEN,
  });

  return NextResponse.json(
    {
      status:
        !blob.configured || blob.accessible ? "ok" : "degraded",
      blob,
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}
