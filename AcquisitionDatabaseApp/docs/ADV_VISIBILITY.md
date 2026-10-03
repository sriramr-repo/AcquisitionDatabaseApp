# ADV visibility and office publication

Implemented September 4, 2026. UI changes are local; this task did not commit, push, or deploy the frontend.

Target Explorer shows six compact indicators under each firm name: succession, custodians, ownership, Part 2A content, office address, and telephone. Each links in the same tab to its firm-detail section. Definitions are available on hover. External source links open separately.

Firm detail exposes Item 4 separately from the analyst succession assessment; complete stored custodian fields; reported Schedule A/B principals and evidence; brochure sources and observations; custody, disclosures, affiliations, private funds, other activities, and additional-office evidence. Proposed/conflicting/rejected findings remain visibly labelled. Absent evidence is never interpreted as a negative filing answer.

The main firm record, scores, facts, research, outreach, ADV facts, custodian records and schedule observations use the current published dataset. IAPD principals retain their own filing date because that source is not dataset-versioned. No beneficial-ownership interpretation or seller-intent inference is added.

## Office source mapping

| SEC roster column | Serving field |
|---|---|
| Main Office Street Address 1 | main_office_street_address_1 |
| Main Office Street Address 2 | main_office_street_address_2 |
| Main Office City | main_office_city |
| Main Office State | main_office_state |
| Main Office Country | main_office_country |
| Main Office Postal Code | main_office_postal_code |
| Main Office Telephone Number | main_office_phone |

The publisher first uses the matching Silver office table. If that table is absent, it reads the exact dataset's preserved Bronze roster ZIP. It validates required headers, unique numeric CRDs, bounded size, and CRC during reading. UTF-8 and Windows-1252 text are supported. Blanks remain null; postal codes and telephone numbers remain text. It does not use representative addresses as firm main offices.

Migration `0019_main_office_postal_code` adds a nullable serving column. It was applied to the configured hosted database after verifying its migration checkpoint and active dataset. The office-only publisher reconciles the complete CRD set and uses one transaction; repeating identical publication makes no updates.

```sh
SCM_ENV=PROD python3 -m src.dashboard_publisher publish-offices \
  --dataset-version ia08032026_0 --database-url "$DATABASE_URL"
```

The normal publisher also uses the fallback for future datasets. Source path configuration must identify the production archive explicitly through the project's existing environment settings.

## Verified hosted coverage

Dataset `ia08032026_0`, September 4, 2026:

| Metric | Coverage |
|---|---:|
| Firms / office records reconciled | 17,018 |
| Main-office telephone | 17,018 |
| Street address line 1 | 15,648 |
| Postal code | 15,559 |
| Item 4 response | 17,018 |
| Custodian records | 12 proposed records, 11 firms |
| Extended schedule observations | 0 |

Before this repair, all hosted August office fields were empty because the August Silver office table was absent. The missing street/postal values above are actual roster blanks, not assumed values. No full coverage claim is made for brochure parsing or schedule extraction.

The first office-only publication updated 17,018 records; a repeat updated zero. SHA-256 checks confirmed the local analytics, metadata, research database, and Bronze ZIP remained unchanged. Hosted score, research, outreach-target and activity fingerprints also remained unchanged.

## Verification

```sh
python3 -m pytest tests/test_dashboard_office_postal.py tests/test_dashboard_publisher_score_version.py tests/test_adv_facts.py tests/test_dashboard_adv_security.py tests/test_seller_intent.py -q
# Optional PostgreSQL tests: all tables are temporary and rolled back.
SCM_TEST_DATABASE_URL="$DATABASE_URL" python3 -m pytest tests/test_dashboard_office_postgres.py -q
cd web
node --test tests/adv-visibility.test.cjs
node tests/adv-queries-smoke.cjs
npm run build
```

The read-only smoke check covers real pagination uniqueness, priority filtering, four sort fields, empty search, indicator availability and firm-detail dataset alignment. Component tests cover null/zero, conflicting and rejected evidence, address formatting and link targets. `node tests/adv-layout-preview.cjs` serves synthetic data only on loopback port 3102 for visual inspection. The real local application correctly redirects unauthenticated requests to login; an authenticated browser review of the live layout was not completed in this task.

Remaining collection work: systematic Part 2A extraction, complete custodian processing/review, and populated extended schedules. Existing pending source jobs and accepted research were not changed by the visibility implementation.
