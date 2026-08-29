# SCM RIA Acquisition Dashboard

This is the Vercel-oriented application layer. It does not ingest SEC data or
write Bronze, Silver, Gold, metadata, or research SQLite files.

## Local setup

```bash
cp .env.example .env.local
docker compose up -d postgres
npm install
npm run db:migrate
python3 -m src.dashboard_publisher publish --dataset-version ia07012026 --database-url "$DATABASE_URL"
npm run dev
```

Create a bcrypt password hash for `AUTH_DEV_PASSWORD_HASH`; do not commit the
value. All dashboard routes and APIs require Auth.js credentials login.

## Enrichment

`FIRECRAWL_API_KEY` is server-only. `POST /api/enrichment/:firmId` performs a
bounded official-site scrape and persists a review-required evidence capture.
It does not accept or write external facts into analyst research.

The research agent consumes those saved evidence captures in bounded queued
jobs. It uses LangChain structured output and stores every extracted value as a
source-linked `PROPOSED` observation. An authenticated analyst must explicitly
accept, reject, or mark each observation conflicting; the agent never writes
Gold, Priority, outreach state, or accepted research directly.

Run a small worker batch from the protected Python environment:

```bash
python3 -m src.cli research-agent-worker --database-url "$PUBLISHER_DATABASE_URL" --limit 3
```

The protected Research page can queue the next 5, 10, or 25 evidence-backed
Priority A firms. The equivalent operator command is:

```bash
python3 -m src.cli research-agent-queue-batch \
  --database-url "$PUBLISHER_DATABASE_URL" \
  --dataset-version ia08032026_0 \
  --limit 10
```

Batch queueing is idempotent and never invokes a model in the web request. The
separate worker remains responsible for bounded inference, and every extracted
observation remains review-required.

The default worker provider is local Ollama with `qwen3:8b`. Set
`RESEARCH_AGENT_PROVIDER=openai` and configure `OPENAI_API_KEY` only when the
hosted provider is desired. A FreeToken server can be selected with
`RESEARCH_AGENT_PROVIDER=freetoken`, `FREETOKEN_BASE_URL`, and a model name
reported by its `/v1/models` endpoint. The worker checks `/health` and the model
list before claiming jobs, so a stopped or misconfigured FreeToken host leaves
queued work untouched. `FREETOKEN_API_KEY` is optional for authenticated reverse
proxies; FreeToken's loopback server does not require one by default.

Server-only configuration: `RESEARCH_AGENT_PROVIDER`, `RESEARCH_AGENT_MODEL`,
`OLLAMA_BASE_URL`, `FREETOKEN_BASE_URL`, `FREETOKEN_API_KEY`, `OPENAI_API_KEY`,
`RESEARCH_AGENT_PROVIDER_HEALTH_TIMEOUT_SECONDS`,
`RESEARCH_AGENT_MAX_PAGES`, `RESEARCH_AGENT_MAX_TOKENS`, and
`RESEARCH_AGENT_TIMEOUT_SECONDS`. Evidence preparation and worker safety are bounded by
`RESEARCH_AGENT_MAX_CONTENT_CHARS`, `RESEARCH_AGENT_MAX_CHUNK_CHARS`,
`RESEARCH_AGENT_MAX_CHUNKS`, `RESEARCH_AGENT_MAX_CHUNKS_PER_REQUEST`, `RESEARCH_AGENT_MAX_ATTEMPTS`,
`RESEARCH_AGENT_RETRY_BASE_SECONDS`, and `RESEARCH_AGENT_LEASE_SECONDS`.
No model call occurs while rendering a page. Workers claim jobs with expiring leases;
transient failures retry with bounded backoff while provenance failures stop safely.

## Local-first IAPD and Cloudflare R2

The complete IAPD feed is normalized on the protected production machine. The
local store retains every person and national current-employment link in
versioned DuckDB and Parquet artifacts under `data/iapd/local/`. Neon retains
only compact firm coverage and workflow state.

The local publisher creates deterministic, gzip-compressed dashboard bundles:

```text
data/iapd/bundles/{dataset_version}/firms/{firm_id}.json.gz
data/iapd/bundles/{dataset_version}/manifest.json
```

Bundles are uploaded privately to Cloudflare R2 at:

```text
iapd/{dataset_version}/objects/{bundle_sha256}.json.gz
iapd/{dataset_version}/manifest.json
```

The manifest is uploaded last and acts as the activation checkpoint. The
dashboard retrieves a bundle only from protected server-side code when a firm
detail page is opened. Target Explorer never performs R2 requests. Hash,
schema, dataset, payload-size, timeout, and decompression limits are enforced.
The server cache is bounded by both entry count and total expanded bytes; firm
pages and the protected API display representatives in bounded pages even when
an unusually large firm has thousands of current links.

Required server-only R2 configuration:

- `CLOUDFLARE_R2_ACCOUNT_ID`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
- `CLOUDFLARE_R2_BUCKET`

Build and publish manually from the repository root:

```bash
python3 -m src.iapd_local build-store \
  --source-zip data/iapd/raw/IA_INDVL_Feed_08_20_2026.xml.zip \
  --source-url https://reports.adviserinfo.sec.gov/reports/CompilationReports/IA_INDVL_Feed_08_20_2026.xml.zip \
  --snapshot-date 2026-08-20 \
  --dataset-version ia08032026_0 \
  --output-root data/iapd/local \
  --firm-source-duckdb data/analytics.duckdb \
  --firm-table gold_scm_acquisition_v1_ia08032026_0

python3 -m src.iapd_local build-bundles \
  --dataset-version ia08032026_0 \
  --local-root data/iapd/local \
  --output-root data/iapd/bundles \
  --firm-source-duckdb data/analytics.duckdb \
  --firm-table gold_scm_acquisition_v1_ia08032026_0

python3 -m src.iapd_local publish-r2 \
  --manifest data/iapd/bundles/ia08032026_0/manifest.json \
  --report-path data/iapd/r2-publications/ia08032026_0.json \
  --workers 16
```

For a deliberate full verification run, add `--force`. Force publication
re-uploads every content-addressed bundle, retains the prior active manifest
under its SHA-256 rollback key, and still activates the new manifest last. It
does not delete any R2 objects or change Neon. Upload concurrency is bounded
to 1-64 workers and defaults to 16; `IAPD_R2_UPLOAD_WORKERS` may set the
scheduled-refresh default.

Neon cleanup is never automatic. It requires a verified R2 publication report,
a complete local Neon detail backup, matching coverage totals, and unchanged
research/outreach counts. `deploy/production-refresh.sh` builds the local store
and bundles after the normal dashboard publish; it publishes to R2 only when
all four R2 credentials are configured.

For the scheduled macOS refresh, copy
`deploy/production-refresh.env.example` to the ignored
`deploy/production-refresh.env`, provide the database and R2 values, and set
the file mode to `600`. The refresh wrapper refuses a more broadly readable
secrets file.

## Deployment

Use a hosted PostgreSQL-compatible `DATABASE_URL`, `AUTH_SECRET`, server-side
`FIRECRAWL_API_KEY`, and the Cloudflare R2 variables above. Run Drizzle migrations during deployment and
run the publisher from the protected production environment after a verified
refresh. Vercel is not used for DuckDB, SQLite, persistent files, or SEC batch
ingestion.

## Virtual SDR

The firm page includes an approval-gated **Prepare CEO Brief** workflow.
Vercel creates an idempotent application record and submits the durable run to
LangSmith Deployment; it does not execute the long-running graph inside a
serverless request. The graph uses immutable SEC/Gold facts plus accepted,
source-linked research, stores the structured artifact in PostgreSQL,
optionally mirrors it to private Cloudflare R2, and pauses for approval through
a LangGraph interrupt. V1 prepares an email and call brief but never sends
outreach.

Required server-only deployment settings are documented in `.env.example`.
Configure the same `DATABASE_URL` and R2 credentials on the LangSmith
deployment, then deploy the graph identified by `virtual_sdr` in the
repository-level `langgraph.json`. Keep `LANGSMITH_HIDE_INPUTS=true` and
`LANGSMITH_HIDE_OUTPUTS=true`; traces retain execution metadata and timing
without copying evidence, contacts, or drafts into observability payloads.

Apply the Drizzle migrations before enabling the button. If LangSmith is
unavailable or unconfigured, the attempt is recorded as `UNAVAILABLE` and the
rest of the dashboard continues normally.
