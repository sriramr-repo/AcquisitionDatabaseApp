# Target Research Schema

The research layer is stored separately from the SEC-derived Silver and Gold
layers in `data/research.db`. Its key is `(firm_id, dataset_version)`.

`target_research` contains only analyst or external-enrichment fields and
workflow metadata. It does not copy the Gold record. `target_research_sources`
stores one-to-many provenance records linked by the same composite key.

The public-source integration adds four metadata-first structures:

- `research_source_tasks` — deterministic source work items for each Priority A
  or B firm, dataset version, and source type.
- `target_research_sources` — source authority, URL, title, publication/access
  dates, retrieval status, content hash, supported fields, and analyst owner.
- `research_observations` — proposed `FACT`, `ESTIMATE`, or `ASSESSMENT` values
  linked to a source, with confidence and review status.
- `historical_adv_filings` — historical Form ADV filing identifiers, dates,
  source paths, retrieval status, and content hashes.

Source task statuses are `NOT_STARTED`, `DISCOVERED`, `RETRIEVED`,
`REVIEW_REQUIRED`, `ACCEPTED`, `UNAVAILABLE`, `FAILED`, and `STALE`.
Observation statuses are `PROPOSED`, `ACCEPTED`, `REJECTED`, and
`CONFLICTING`. Reviewing an observation never automatically changes a
`target_research` field; factual field updates continue to require explicit
source-linked application through `update_factual_fields`.

## Value categories

- **Fact:** externally verifiable information, recorded with one or more source
  records (for example, a founder listed on a company website).
- **Estimate:** numeric or inferred economic information, always accompanied by
  a method and an economics confidence value.
- **Assessment:** analyst judgment, such as succession readiness or strategic
  fit. It is not treated as SEC-derived data.

Confidence values are `LOW`, `MEDIUM`, `HIGH`, or `VERIFIED` where meaningful.
Succession readiness uses `UNKNOWN`, `LOW`, `MEDIUM`, or `HIGH`.

## Workflow

`NOT_STARTED → IN_PROGRESS → RESEARCH_COMPLETE` is the normal flow.
`NEEDS_REVIEW` handles conflicting or insufficient evidence. `STALE` marks a
record requiring refresh after a future policy threshold. These statuses are
research workflow states, not CRM or outreach stages.

## Dossier schema

The future dossier is a presentation of Gold facts plus this research record:

1. Executive Snapshot
2. Why SCM Should Care
3. Firm Profile
4. Founder & Ownership
5. Succession Assessment
6. Economics
7. Investment & Custodian Fit
8. Risks
9. Recommended Next Action
10. Sources

The repository provides record CRUD, evidence CRUD, source-task initialization,
historical filing metadata registration, observation review, and idempotent
Priority A/B source coverage initialization. It does not perform broad web
crawling, automatically accept external facts, or create outreach activity
records.
