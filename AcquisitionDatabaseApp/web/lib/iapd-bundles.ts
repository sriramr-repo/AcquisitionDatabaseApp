import "server-only";

import crypto from "node:crypto";
import { gunzipSync } from "node:zlib";
import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";

const MANIFEST_SCHEMA_VERSION = "iapd-bundle-manifest-v1";
const BUNDLE_SCHEMA_VERSION = "iapd-firm-bundle-v1";
const safePart = /^[A-Za-z0-9_-]+$/;
const cache = new Map<string, { expiresAt: number; sizeBytes: number; value: any }>();
let cacheBytes = 0;
let client: S3Client | undefined;

export type IapdBundleStatus =
  | "AVAILABLE"
  | "NO_CURRENT_REPRESENTATIVE"
  | "CONFIGURATION_MISSING"
  | "MANIFEST_UNAVAILABLE"
  | "BUNDLE_UNAVAILABLE"
  | "INTEGRITY_FAILED"
  | "FAILED";

export type IapdBundleResult = {
  status: IapdBundleStatus;
  bundle?: any;
  message?: string;
};

function config() {
  const values = {
    accountId: process.env.CLOUDFLARE_R2_ACCOUNT_ID,
    accessKeyId: process.env.CLOUDFLARE_R2_ACCESS_KEY_ID,
    secretAccessKey: process.env.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
    bucket: process.env.CLOUDFLARE_R2_BUCKET,
    sessionToken: process.env.CLOUDFLARE_R2_SESSION_TOKEN || "",
  };
  return [values.accountId, values.accessKeyId, values.secretAccessKey, values.bucket].every(Boolean)
    ? values as Record<keyof typeof values, string>
    : null;
}

function storageClient(configuration: NonNullable<ReturnType<typeof config>>) {
  if (!client) {
    client = new S3Client({
      endpoint: `https://${configuration.accountId}.r2.cloudflarestorage.com`,
      region: "auto",
      credentials: {
        accessKeyId: configuration.accessKeyId,
        secretAccessKey: configuration.secretAccessKey,
        ...(configuration.sessionToken ? { sessionToken: configuration.sessionToken } : {}),
      },
      maxAttempts: 2,
    });
  }
  return client;
}

function cacheGet(key: string) {
  const item = cache.get(key);
  if (!item || item.expiresAt <= Date.now()) {
    if (item) cacheBytes -= item.sizeBytes;
    cache.delete(key);
    return undefined;
  }
  return item.value;
}

function cacheSet(key: string, value: any, sizeBytes: number) {
  const ttl = Math.min(3_600, Math.max(30, Number(process.env.IAPD_BUNDLE_CACHE_TTL_SECONDS || 300)));
  const maximum = Math.min(1_000, Math.max(10, Number(process.env.IAPD_BUNDLE_CACHE_MAX_ENTRIES || 250)));
  const maximumBytes = Math.min(256_000_000, Math.max(10_000_000, Number(process.env.IAPD_BUNDLE_CACHE_MAX_BYTES || 50_000_000)));
  const existing = cache.get(key);
  if (existing) {
    cacheBytes -= existing.sizeBytes;
    cache.delete(key);
  }
  if (sizeBytes > maximumBytes) return;
  while (cache.size && (cache.size >= maximum || cacheBytes + sizeBytes > maximumBytes)) {
    const oldestKey = cache.keys().next().value as string;
    const oldest = cache.get(oldestKey);
    if (oldest) cacheBytes -= oldest.sizeBytes;
    cache.delete(oldestKey);
  }
  cache.set(key, { expiresAt: Date.now() + ttl * 1_000, sizeBytes, value });
  cacheBytes += sizeBytes;
}

async function objectBytes(
  storage: S3Client,
  bucket: string,
  key: string,
  maximumBytes: number,
) {
  const timeout = Math.min(30_000, Math.max(1_000, Number(process.env.IAPD_R2_TIMEOUT_MS || 8_000)));
  const response = await storage.send(
    new GetObjectCommand({ Bucket: bucket, Key: key }),
    { abortSignal: AbortSignal.timeout(timeout) },
  );
  if (!response.Body) throw new Error("R2 object has no response body");
  if (response.ContentLength != null && response.ContentLength > maximumBytes) {
    throw new Error(`R2 object exceeds the ${maximumBytes}-byte limit`);
  }
  const bytes = Buffer.from(await response.Body.transformToByteArray());
  if (bytes.length > maximumBytes) throw new Error(`R2 object exceeds the ${maximumBytes}-byte limit`);
  return { bytes, metadata: response.Metadata || {} };
}

async function activeManifest(datasetVersion: string, configuration: NonNullable<ReturnType<typeof config>>) {
  const cacheKey = `manifest:${datasetVersion}`;
  const cached = cacheGet(cacheKey);
  if (cached) return cached;
  const maximum = Number(process.env.IAPD_R2_MAX_MANIFEST_BYTES || 10_000_000);
  const { bytes, metadata } = await objectBytes(
    storageClient(configuration), configuration.bucket,
    `iapd/${datasetVersion}/manifest.json`, maximum,
  );
  const digest = crypto.createHash("sha256").update(bytes).digest("hex");
  if (metadata.sha256 && metadata.sha256 !== digest) throw new Error("IAPD manifest hash mismatch");
  const manifest = JSON.parse(bytes.toString("utf8"));
  if (manifest.schema_version !== MANIFEST_SCHEMA_VERSION || manifest.dataset_version !== datasetVersion) {
    throw new Error("IAPD manifest contract mismatch");
  }
  const byFirm = new Map<string, any>(manifest.entries.map((entry: any) => [String(entry.firm_id), entry]));
  const result = { ...manifest, byFirm };
  cacheSet(cacheKey, result, bytes.length);
  return result;
}

function errorCode(error: unknown) {
  const value = error as any;
  return String(value?.name || value?.Code || value?.$metadata?.httpStatusCode || "");
}

export async function getIapdFirmBundle(
  datasetVersion: string,
  firmId: string,
): Promise<IapdBundleResult> {
  if (!safePart.test(datasetVersion) || !safePart.test(firmId)) {
    return { status: "FAILED", message: "Invalid dataset or firm identifier" };
  }
  const configuration = config();
  if (!configuration) {
    return { status: "CONFIGURATION_MISSING", message: "Cloudflare R2 is not configured" };
  }
  let manifest: any;
  try {
    manifest = await activeManifest(datasetVersion, configuration);
  } catch (error) {
    const code = errorCode(error);
    if (["NoSuchKey", "NotFound", "404"].includes(code)) {
      return { status: "MANIFEST_UNAVAILABLE", message: "The IAPD dataset manifest is unavailable" };
    }
    return { status: "FAILED", message: error instanceof Error ? error.message : "Unable to retrieve IAPD manifest" };
  }
  const entry = manifest.byFirm.get(firmId);
  if (!entry) return { status: "INTEGRITY_FAILED", message: "Firm is absent from the active IAPD manifest" };
  if (entry.status === "NO_CURRENT_REPRESENTATIVE") {
    return { status: "NO_CURRENT_REPRESENTATIVE", message: "No current representative link is reported in this IAPD snapshot" };
  }
  if (entry.status !== "AVAILABLE" || !entry.object_key || !entry.sha256) {
    return { status: "BUNDLE_UNAVAILABLE", message: "The firm detail bundle is unavailable" };
  }
  const cacheKey = `bundle:${datasetVersion}:${firmId}:${entry.sha256}`;
  const cached = cacheGet(cacheKey);
  if (cached) return { status: "AVAILABLE", bundle: cached };
  try {
    const maximum = Number(process.env.IAPD_R2_MAX_BUNDLE_BYTES || 5_000_000);
    const { bytes, metadata } = await objectBytes(
      storageClient(configuration), configuration.bucket, entry.object_key, maximum,
    );
    const digest = crypto.createHash("sha256").update(bytes).digest("hex");
    if (digest !== entry.sha256 || (metadata.sha256 && metadata.sha256 !== digest)) {
      return { status: "INTEGRITY_FAILED", message: "The IAPD bundle hash does not match the active manifest" };
    }
    const expandedMaximum = Number(process.env.IAPD_R2_MAX_EXPANDED_BUNDLE_BYTES || 25_000_000);
    const expanded = gunzipSync(bytes, { maxOutputLength: expandedMaximum });
    const bundle = JSON.parse(expanded.toString("utf8"));
    if (
      bundle.schema_version !== BUNDLE_SCHEMA_VERSION ||
      bundle.dataset_version !== datasetVersion ||
      String(bundle.firm_id) !== firmId ||
      bundle.snapshot_id !== manifest.snapshot_id
    ) {
      return { status: "INTEGRITY_FAILED", message: "The IAPD bundle contract does not match the active manifest" };
    }
    cacheSet(cacheKey, bundle, expanded.length);
    return { status: "AVAILABLE", bundle };
  } catch (error) {
    const code = errorCode(error);
    if (["NoSuchKey", "NotFound", "404"].includes(code)) {
      return { status: "BUNDLE_UNAVAILABLE", message: "The firm detail bundle is missing from Cloudflare R2" };
    }
    return { status: "FAILED", message: error instanceof Error ? error.message : "Unable to retrieve IAPD bundle" };
  }
}
