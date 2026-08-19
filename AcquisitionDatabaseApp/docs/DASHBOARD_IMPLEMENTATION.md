# Dashboard implementation status

The dashboard is a separate `web/` Next.js application. Its PostgreSQL serving
database is populated by `src/dashboard_publisher.py`, which reads protected
DuckDB/SQLite sources without modifying them.

The initial application includes authenticated Overview, Target Explorer, Firm
Detail, Research, Outreach, Changes, and Operations routes; server-side target
queries; score/fact/research/source display; outreach state persistence; and a
server-side Firecrawl endpoint that stores review-required evidence captures.

The Firecrawl endpoint is intentionally explicit and bounded. It is not called
while rendering target lists, does not send outreach, and does not overwrite
analyst research.

Local PostgreSQL requires Docker. If the Docker daemon is unavailable, the
Next.js production build and Python publisher compilation can still be checked,
but migrations and a real publish must wait for PostgreSQL.
