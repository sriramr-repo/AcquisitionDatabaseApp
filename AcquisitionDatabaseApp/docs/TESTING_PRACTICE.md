# Testing Practice

This repository uses tests as part of normal development. The goal is fast feedback for small logic changes, regression protection for fixes, and end-to-end confidence for user workflows.

## Test level

### Unit tests

Use unit tests for deterministic logic that can run without a real database, network, filesystem production data, or browser. Examples include:

- SEC parsing, normalization, mappings, and null-versus-zero behavior.
- AUM, client, staffing, custodian, and Gold calculations.
- Priority classification, seller-intent rules, and score reason codes.
- Report serialization and formatting helpers.
- Publisher validation and preservation decisions when dependencies are mocked.
- Firecrawl/LangChain output validation, provenance, confidence, and guardrails.
- Filtering, sorting, pagination, and authentication/permission helpers.

Every new business rule or calculation should have direct unit coverage. Every bug fix should add a regression test that fails before the fix and passes afterward.

### Integration tests

Use integration tests when real component boundaries matter, such as pipeline-to-DuckDB, publisher-to-PostgreSQL, migrations, or persistence and transaction behavior. Use isolated fixtures or temporary databases and never production data.

### End-to-end tests

Use end-to-end tests for complete user journeys, such as authentication, target filtering, firm detail, research updates, evidence review, and outreach activity creation. Keep external services mocked unless the test is explicitly a controlled environment check.

## Required edge cases

When relevant, tests should cover empty input, missing values, explicit zero, malformed input, duplicate identifiers, boundary thresholds, retries/failures, stale data, and permission failures. Unknown or unavailable values must not become zero.

## Local commands

Run focused tests first:

```bash
pytest tests/test_<area>.py -q
```

Then run the related regression tests. For dashboard changes, also run:

```bash
cd web
npm run build
```

Do not use production databases, ingestion artifacts, or live external calls in ordinary tests.

## Pull-request expectations

The pull-request checklist is the minimum bar. A change may omit a test only when the change is documentation-only or a reviewer records why executable behavior cannot be tested.

