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

## Deployment

Use a hosted PostgreSQL-compatible `DATABASE_URL`, `AUTH_SECRET`, and
server-side `FIRECRAWL_API_KEY`. Run Drizzle migrations during deployment and
run the publisher from the protected production environment after a verified
refresh. Vercel is not used for DuckDB, SQLite, persistent files, or SEC batch
ingestion.
