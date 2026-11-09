const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");

require.extensions[".ts"] = (module, filename) => module._compile(
  ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
  filename,
);

const {
  databaseFingerprint,
  databaseIdentity,
  mutationBlocked,
  mutationsAllowed,
  validateVercelDeployment,
} = require("../lib/deployment-policy.ts");

function baseEnvironment(databaseUrl, deployment = "production") {
  const production = databaseFingerprint(databaseIdentity(
    "postgres://user:secret@ep-production.example/neondb",
  ));
  return {
    VERCEL_ENV: deployment,
    DATABASE_URL: databaseUrl,
    SCM_PRODUCTION_DATABASE_FINGERPRINT: production,
    SCM_NEON_PROJECT_ID: "approved-project",
    NEON_PROJECT_ID: "approved-project",
    SCM_MUTATIONS_ENABLED: deployment === "production" ? "true" : "false",
    AUTH_SECRET: "auth-secret",
    AUTH_DEV_EMAIL: "analyst@example.com",
    AUTH_DEV_PASSWORD_HASH: "bcrypt-hash",
    NEXT_PUBLIC_APP_URL: "https://dashboard.example.com",
    CLOUDFLARE_R2_ACCOUNT_ID: "account",
    CLOUDFLARE_R2_BUCKET: "bucket",
    CLOUDFLARE_R2_READ_ACCESS_KEY_ID: "read-key",
    CLOUDFLARE_R2_READ_SECRET_ACCESS_KEY: "read-secret",
  };
}

test("pooled and direct Neon URLs share a credential-free fingerprint", () => {
  const direct = databaseIdentity("postgres://user:one@ep-production.example/neondb");
  const pooled = databaseIdentity("postgres://user:two@ep-production-pooler.example/neondb");
  assert.equal(direct.pooled, false);
  assert.equal(pooled.pooled, true);
  assert.equal(databaseFingerprint(direct), databaseFingerprint(pooled));
});

test("production accepts only the approved pooled database with explicit mutations", () => {
  const env = baseEnvironment("postgres://user:secret@ep-production-pooler.example/neondb");
  const result = validateVercelDeployment(env);
  assert.equal(result.deployment, "production");
  assert.equal(result.mutationsAllowed, true);
  assert.equal(result.databaseTarget.pooled, true);

  assert.throws(
    () => validateVercelDeployment({...env, DATABASE_URL: "postgres://user:secret@ep-production.example/neondb"}),
    /pooled Neon hostname/,
  );
  assert.throws(
    () => validateVercelDeployment({...env, SCM_MUTATIONS_ENABLED: "false"}),
    /explicit SCM_MUTATIONS_ENABLED=true/,
  );
});

test("production rejects localhost, refresh credentials, and public secrets", () => {
  const env = baseEnvironment("postgres://user:secret@ep-production-pooler.example/neondb");
  assert.throws(
    () => validateVercelDeployment({...env, DATABASE_URL: "postgres://user:secret@localhost/neondb"}),
    /localhost/,
  );
  assert.throws(
    () => validateVercelDeployment({...env, PUBLISHER_DATABASE_URL: env.DATABASE_URL}),
    /refresh-host variable/,
  );
  assert.throws(
    () => validateVercelDeployment({...env, NEXT_PUBLIC_DATABASE_URL: env.DATABASE_URL}),
    /expose server credential/,
  );
});

test("preview requires an approved-project branch distinct from production and blocks mutations", () => {
  const previewUrl = "postgres://user:secret@ep-preview-pooler.example/preview";
  const env = baseEnvironment(previewUrl, "preview");
  const result = validateVercelDeployment(env);
  assert.equal(result.deployment, "preview");
  assert.equal(result.mutationsAllowed, false);
  assert.equal(mutationsAllowed({...env, SCM_MUTATIONS_ENABLED: "true"}), false);
  assert.equal(mutationBlocked(env, "POST", "/api/outreach/123"), true);
  assert.equal(mutationBlocked(env, "GET", "/api/outreach/123"), false);

  assert.throws(
    () => validateVercelDeployment({...env, SCM_MUTATIONS_ENABLED: "true"}),
    /preview mutations cannot be enabled/,
  );
  assert.throws(
    () => validateVercelDeployment({...env, DATABASE_URL: "postgres://user:secret@ep-production-pooler.example/neondb"}),
    /distinct from production/,
  );
  assert.throws(
    () => validateVercelDeployment({...env, NEON_PROJECT_ID: "different-project"}),
    /approved Neon project/,
  );
});

test("local development remains reversible and does not require deployment secrets", () => {
  assert.deepEqual(validateVercelDeployment({}), {
    deployment: "local",
    enforced: false,
    mutationsAllowed: true,
  });
  assert.equal(mutationBlocked({SCM_MUTATIONS_ENABLED: "false"}, "DELETE", "/api/firms/1"), true);
  assert.equal(mutationBlocked({SCM_MUTATIONS_ENABLED: "false"}, "POST", "/login"), false);
});
