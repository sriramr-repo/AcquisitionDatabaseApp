# Production recovery evidence

Canonical IAPD activation requires three independent recovery artifacts before
migration or publication:

1. A provider-managed PostgreSQL snapshot or branch reference.
2. A custom-format PostgreSQL dump with a validated `pg_restore --list`
   catalog and a successful restore into an empty, isolated database.
3. A verified local application backup with a hash-matched restore into an
   isolated temporary directory.

The recovery evidence command creates the latter two and records the
operator-supplied provider snapshot reference. It does not create or verify a
provider snapshot through an API. The operator must create that snapshot in
the database provider first and retain its identifier.

## Safety boundaries

- Run from the protected refresh host, never Vercel.
- `DATABASE_URL` must match the approved production fingerprint.
- `RECOVERY_RESTORE_DATABASE_URL` must identify a distinct, empty, explicitly
  approved database or provider branch.
- The restore command uses no `--clean`, `--create`, or ownership/privilege
  restoration. A non-empty target is rejected.
- Database passwords are passed to trusted PostgreSQL tools through libpq
  environment variables, never command arguments, output, or evidence files.
- Docker is not used or required.
- The evidence gate fails if the restored migration ledger, active dataset, or
  critical table counts differ from the pre-dump production baseline.

## Prerequisites

Install compatible `pg_dump`, `pg_restore`, and `psql` client tools on the
refresh host. Set `SCM_POSTGRES_BIN_DIR` to their absolute bin directory when
the tools are installed by a keg-only package and are intentionally absent from
the global `PATH`. On Apple Silicon with Homebrew `libpq`, use
`/opt/homebrew/opt/libpq/bin`. An explicit directory is fail-closed: every
required tool must be executable there and the recovery command will not fall
back to a different `PATH` binary. Copy `deploy/recovery-evidence.env.example`
to a protected, ignored file, set mode `600`, and provide the production and
isolated-restore URLs.

The approved isolated restore database must be disposable and must not serve
Vercel, scheduled jobs, users, or any other environment. Creating that target
and the provider snapshot are explicit operator actions.

## Create evidence

After pausing the scheduler and creating the provider snapshot:

```bash
set -a
source deploy/recovery-evidence.env
set +a

SCM_ENV=PROD python3 -m src.cli recovery-evidence-create \
  --provider-snapshot-id PROVIDER_SNAPSHOT_ID \
  --provider-snapshot-created-at 2026-11-08T12:00:00Z \
  --operator OPERATOR_ID \
  --restore-owner RESTORE_OWNER_ID
```

The command records only redacted database identities and credential-free
fingerprints. Output is written under
`data/backups/recovery-evidence/<evidence-id>/`. The PostgreSQL dump and catalog
remain private backup artifacts and must not be committed or uploaded to
Vercel.

The command stops before creating artifacts when PostgreSQL tools are missing,
the source fingerprint differs, the restore target is production, or the
restore target is non-empty. A failure after evidence creation begins leaves a
`status: failed` manifest and never reports readiness.

## Re-verify evidence

```bash
SCM_ENV=PROD python3 -m src.cli recovery-evidence-verify \
  data/backups/recovery-evidence/EVIDENCE_ID/evidence.json
```

Verification recomputes the dump, catalog, local manifest, and local backup
hashes and checks both restore proofs. Any missing, modified, incomplete, or
failed artifact blocks the activation gate.

## Evidence limitations

The tool proves that the custom dump and local backup restored successfully at
the recorded time. It does not continuously monitor provider retention,
automatically delete the isolated restore database, or authorize production
rollback. Retain the provider snapshot and isolated restore target until the
activation and rollback window closes, then remove them through the provider's
approved operational process.
