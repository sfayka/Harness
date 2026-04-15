type BlobListFn = (options: { token: string; limit: number }) => Promise<unknown>;

export type BlobRuntimeHealth = {
  configured: boolean;
  accessible: boolean;
  error: string | null;
};

async function listBlobsWithSdk(options: {
  token: string;
  limit: number;
}): Promise<unknown> {
  const { list } = await import("@vercel/blob");
  return list(options);
}

export async function getBlobRuntimeHealth(
  env: Partial<Record<"BLOB_READ_WRITE_TOKEN", string | undefined>>,
  listBlobs: BlobListFn = listBlobsWithSdk,
): Promise<BlobRuntimeHealth> {
  const token = env.BLOB_READ_WRITE_TOKEN?.trim();
  if (!token) {
    return {
      configured: false,
      accessible: false,
      error: null,
    };
  }

  try {
    await listBlobs({ token, limit: 1 });
    return {
      configured: true,
      accessible: true,
      error: null,
    };
  } catch (error) {
    return {
      configured: true,
      accessible: false,
      error: error instanceof Error ? error.message : "unknown error",
    };
  }
}
