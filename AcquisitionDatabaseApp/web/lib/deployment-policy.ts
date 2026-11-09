import { createHash } from "node:crypto";
import {
  deploymentEnvironment,
  mutationsAllowed,
  type Environment,
} from "./deployment-mutations.ts";

export { deploymentEnvironment, mutationBlocked, mutationsAllowed } from "./deployment-mutations.ts";
export type { DeploymentEnvironment, Environment } from "./deployment-mutations.ts";

const sha256Pattern = /^[0-9a-f]{64}$/;
const prohibitedVercelVariables = [
  "PUBLISHER_DATABASE_URL",
  "SCM_DATA_DIR",
  "IAPD_FIRM_ACTIVATION_MANIFEST",
  "IAPD_R2_UPLOAD_WORKERS",
  "CLOUDFLARE_R2_ACCESS_KEY_ID",
  "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
  "CLOUDFLARE_R2_SESSION_TOKEN",
];
const publicSecretName = /(DATABASE|PASSWORD|SECRET|TOKEN|ACCESS_KEY|API_KEY|R2)/;

function required(env: Environment, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new Error(`Vercel deployment requires ${name}`);
  return value;
}

export function databaseIdentity(url: string) {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("Vercel DATABASE_URL is not a valid URL");
  }
  if (!["postgres:", "postgresql:"].includes(parsed.protocol) || !parsed.hostname || !parsed.pathname.slice(1)) {
    throw new Error("Vercel DATABASE_URL must identify PostgreSQL explicitly");
  }
  const suppliedHost = parsed.hostname.toLowerCase();
  const pooled = suppliedHost.includes("-pooler.");
  const host = suppliedHost.replace("-pooler.", ".");
  if (["localhost", "127.0.0.1", "::1"].includes(host)) {
    throw new Error("Vercel refuses a localhost database target");
  }
  return {
    database: decodeURIComponent(parsed.pathname.slice(1)),
    host,
    port: parsed.port ? Number(parsed.port) : 5432,
    pooled,
    schema: "public",
  };
}

export function databaseFingerprint(identity: ReturnType<typeof databaseIdentity>) {
  // Key order matches Python's json.dumps(..., sort_keys=True, separators=(",", ":")).
  const canonical = JSON.stringify({
    database: identity.database,
    host: identity.host,
    port: identity.port,
    schema: identity.schema,
  });
  return createHash("sha256").update(canonical).digest("hex");
}

function requiredFingerprint(env: Environment, name: string): string {
  const value = required(env, name).toLowerCase();
  if (!sha256Pattern.test(value)) throw new Error(`${name} must be a SHA-256 fingerprint`);
  return value;
}

export function validateVercelDeployment(env: Environment) {
  const deployment = deploymentEnvironment(env);
  if (deployment === "local" || deployment === "development") {
    return { deployment, enforced: false, mutationsAllowed: mutationsAllowed(env) };
  }
  for (const name of Object.keys(env)) {
    if (name.startsWith("NEXT_PUBLIC_") && name !== "NEXT_PUBLIC_APP_URL" && publicSecretName.test(name)) {
      throw new Error(`Vercel must not expose server credential ${name} to the client`);
    }
  }
  for (const name of prohibitedVercelVariables) {
    if (env[name]) throw new Error(`Vercel must not define refresh-host variable ${name}`);
  }
  const databaseUrl = required(env, "DATABASE_URL");
  const identity = databaseIdentity(databaseUrl);
  const actualFingerprint = databaseFingerprint(identity);
  const productionFingerprint = requiredFingerprint(env, "SCM_PRODUCTION_DATABASE_FINGERPRINT");
  const approvedNeonProject = required(env, "SCM_NEON_PROJECT_ID");
  const actualNeonProject = required(env, "NEON_PROJECT_ID");
  if (!identity.pooled) {
    throw new Error("Vercel DATABASE_URL must use the pooled Neon hostname");
  }
  if (actualNeonProject !== approvedNeonProject) {
    throw new Error("Vercel database does not belong to the approved Neon project");
  }
  required(env, "AUTH_SECRET");
  required(env, "AUTH_DEV_EMAIL");
  required(env, "AUTH_DEV_PASSWORD_HASH");
  required(env, "CLOUDFLARE_R2_ACCOUNT_ID");
  required(env, "CLOUDFLARE_R2_BUCKET");
  required(env, "CLOUDFLARE_R2_READ_ACCESS_KEY_ID");
  required(env, "CLOUDFLARE_R2_READ_SECRET_ACCESS_KEY");

  if (deployment === "production") {
    if (actualFingerprint !== productionFingerprint) {
      throw new Error("Vercel production database does not match the approved fingerprint");
    }
    if (!mutationsAllowed(env)) {
      throw new Error("Vercel production requires explicit SCM_MUTATIONS_ENABLED=true");
    }
    const appUrl = required(env, "NEXT_PUBLIC_APP_URL");
    if (!appUrl.startsWith("https://") || appUrl.includes("localhost")) {
      throw new Error("Vercel production NEXT_PUBLIC_APP_URL must use public HTTPS");
    }
  } else {
    // The Vercel-managed Neon integration injects a different copy-on-write
    // branch URL for each preview deployment, so its fingerprint is dynamic.
    if (actualFingerprint === productionFingerprint) {
      throw new Error("Vercel preview must use a database distinct from production");
    }
    if (env.SCM_MUTATIONS_ENABLED === "true") {
      throw new Error("Vercel preview mutations cannot be enabled");
    }
  }
  return {
    deployment,
    enforced: true,
    mutationsAllowed: mutationsAllowed(env),
    databaseTarget: { ...identity, fingerprint: actualFingerprint },
    neonProjectId: actualNeonProject,
    r2ReadOnlyCredentialsConfigured: true,
  };
}
