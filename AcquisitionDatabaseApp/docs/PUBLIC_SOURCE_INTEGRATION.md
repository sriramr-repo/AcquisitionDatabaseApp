# Public-source integration workflow

This repository uses a metadata-first workflow for Priority A and Priority B
RIA research. SEC/Silver/Gold records remain immutable batch facts. Public
documents and analyst observations are stored separately in `research.db`.

## Source registry

`src/source_registry.py` defines the source taxonomy, authority, landing URL,
collection mode, Form ADV field dictionary, task statuses, observation value
types, confidence levels, and review statuses. The official SEC references are:

- [SEC adviser data](https://www.sec.gov/data-research/sec-markets-data/information-about-registered-investment-advisers-exempt-reporting-advisers)
- [Historical Form ADV data](https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data)
- [IAPD](https://adviserinfo.sec.gov/)
- [Form ADV Part 1A definitions](https://www.sec.gov/files/formadv-part1a_1.pdf)

## Storage

- `research_source_tasks`: one deterministic task per firm, dataset version,
  and source type.
- `target_research_sources`: source URL and provenance metadata for a document
  or page that an analyst can review.
- `research_observations`: proposed facts, estimates, or assessments linked to
  a source. Review does not automatically write a research field.
- `historical_adv_filings`: metadata and hashes for historical ADV CSV rows.

`research_status` and source-task status are separate from outreach workflow
state. An unavailable source is recorded as `UNAVAILABLE`; it is not treated as
an unresearched or negative fact.

## Commands

Initialize all eight core source tasks for the active dataset:

```bash
SCM_ENV=PROD python3 -m src.cli initialize-source-tasks ia07012026
```

Inspect coverage:

```bash
SCM_ENV=PROD python3 -m src.cli source-coverage ia07012026
```

The workflow does not crawl broadly, infer founder/ownership/seller intent, or
send outreach. Historical ADV CSV registration is available through
`src/historical_adv.py`; it records filing metadata and content hashes without
changing Silver or Gold.
