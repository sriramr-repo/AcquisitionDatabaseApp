# Form ADV facts, lineage, and seller intent

## Source flow

```text
SEC monthly IA CSV ──► structured ADV parser ──► adv_firm_facts ──► Form ADV card
        │                         │                     │
        │                         └── exact fields ─────┴──► fact_definitions
        │
        └── CRD + firm name ──► IAPD summary/current PDF identity
                                      │
                                      └── local OCR (queued, leased, rate-limited, page-bounded)
                                              │
                                              ├── deterministic Schedule 5.K.(3) parser
                                              ├── optional grounded LangChain fallback
                                              └── proposed Schedule 5.K.(3) custodians

Direct/authorized communication ──► seller_intent_evidence (PROPOSED)
                                              │
                                              ├── reject ──► retained evidence
                                              └── confirm ─► seller_intent_current
                                                               │
                                                               └── seller_intent_history
```

Silver, Gold, SCM Acquisition V2, Priority, research status, outreach status, and seller intent remain separate.

## Source authority

| Fact group | Primary source | Extraction | Review |
|---|---|---|---|
| Identity, SEC number | SEC monthly IA CSV | Structured | Automated validation |
| Items 1.O, 2.A, 4, 5.A–5.G, 5.K flags | SEC monthly IA CSV | Structured | Exact source field retained in catalog |
| Current filing identity/links | IAPD firm summary and direct CRD PDF | CRD/name validation | Failed matches remain visible |
| Schedule D 5.K.(3) custodian rows | Official current ADV PDF | Local OCR, optional grounded LangChain fallback | Proposed until reviewed |
| Ownership/control, custody, affiliations, SMA structure, private funds, disclosures, offices | Official ADV PDF / schedules | Versioned proposed schedule observations | Review required |
| Part 2A brochure intelligence | Official ADV Part 2A brochure | Firecrawl capture plus review-gated structured extraction | Review required |
| Research facts | Public evidence and analyst research | Research agent/analyst | Existing review workflow |
| Seller intent | Direct or authorized evidence | Rule-based proposal | User confirmation required |

## Seller-intent rules

Seller intent is a verified business-development fact, not a regulatory filing fact or acquisition score.

| Status | Discrete meaning |
|---|---|
| `UNKNOWN` | No verified evidence currently establishes willingness or unwillingness. |
| `SIGNAL_IDENTIFIED` | Credible indirect evidence suggests a transaction or transition discussion may be relevant, but it is not confirmed. |
| `DIRECTLY_EXPRESSED` | An owner or authorized decision maker explicitly expressed openness to a transaction. |
| `ENGAGED_IN_DISCUSSION` | A substantive two-way discussion occurred and has a next step. |
| `FORMAL_PROCESS` | A verified organized sale, merger, or strategic-alternatives process is underway. |
| `NOT_INTERESTED` | An owner or authorized decision maker explicitly stated they are not currently interested. |
| `STALE` | A user manually marked a previously verified status as no longer reliable. |
| `CONFLICTING` | Credible current evidence supports materially different conclusions. |

Permitted evidence includes owner/authorized-representative communication, outreach responses, calls, meetings, authorized intermediaries, named referrals, and public formal-process announcements. SEC/IAPD facts, founder age, staffing, lack of a visible successor, and no-response are context only and cannot establish seller intent.

## Operational behavior

- Monthly publication stores one compact current fact row per active firm.
- The latest successful structured filing is displayed; failed refreshes do not erase it.
- Manual refresh creates an idempotent queued job.
- OCR executes locally, not in Vercel, and has command/page/time boundaries.
- Custodian batch states are explicit: `NOT_REQUIRED`, `REVIEW_REQUIRED`, `NEEDS_REVIEW`, `UNAVAILABLE`, `RETRY_WAIT`, or `FAILED`; a missing extraction is never treated as zero custodians.
- Workers atomically claim one job at a time, use a lease, retry only transient source failures, throttle public-PDF retrieval, and delete each temporary page image immediately after OCR.
- The local OCR worker requires `pdfinfo`, `pdftoppm`, and `tesseract`; missing tools fail only the queued OCR job and do not interrupt structured ADV publication.
- `NULL` always means unavailable or not reported and is never rewritten to zero.
- External links open in a new tab; dashboard navigation stays in the current tab.
