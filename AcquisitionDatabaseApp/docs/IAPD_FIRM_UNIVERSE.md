# Canonical IAPD firm universe

The canonical firm population comes from the same-date SEC and state firm
compilations listed in the official IAPD manifest. The individual compilation
remains a representative enrichment source and never creates firms.

Each snapshot is versioned as `iapdfirmYYYYMMDD`. Bronze retains a ZIP
containing both validated `.xml.gz` sources and the reconciliation report.
Silver contains one `silver_firms_<version>` row per CRD plus normalized
`silver_firm_registrations_<version>` and `silver_firm_offices_<version>`
tables. Previous datasets are not overwritten.

Registration relationships are source facts:

- `SEC_REGISTRATION` and `STATE_REGISTRATION` make a firm registered.
- `SEC_ERA` and `STATE_ERA` are preserved but do not make an ERA-only firm
  registered.
- `STATE_NOTICE_FILE` is never treated as state registration.
- A CRD with both SEC and state registration is counted once and marked dual.

Unknown or transitional statuses require review. They are not silently treated
as inactive. Missing AUM remains null. ERA-only firms remain in Silver and Gold
for provenance but receive the `NOT_REGISTERED_ADVISER` hard exclusion.

Inspect already-downloaded files without publishing:

```bash
python3 -m src.cli iapd-firm-inspect \
  --sec-source-gz /path/to/IA_FIRM_SEC_Feed_MM_DD_YYYY.xml.gz \
  --state-source-gz /path/to/IA_FIRM_STATE_Feed_MM_DD_YYYY.xml.gz \
  --snapshot-date YYYY-MM-DD \
  --report-path /tmp/iapd-firm-reconciliation.json
```

Production discovery validates the manifest, official host, filenames, gzip
streams, XML roots and generation dates, and the published IARD XSDs before
normalization. The closest retained SEC Silver roster is compared by exact CRD.
A date-mismatched comparison is informational; unexplained differences against
an equal-date roster block promotion.

Production supports two explicit source-selection modes:

- The default `latest_manifest` mode resolves the official manifest once and
  passes that immutable SEC/state pair through the complete run.
- `pinned_activation_manifest` mode reads a reviewed local JSON manifest. It
  reconstructs only canonical official-host URLs and requires the downloaded
  source hashes, XSD hashes, parser version, snapshot identity, and
  reconciliation counts to match before promotion.

The reviewed first-activation manifest is
`deploy/iapd-firm-activations/iapdfirm20261107.json`. Its counts are validation
evidence for that snapshot, not permanent population assertions. Run it with:

```bash
SCM_ENV=PROD python3 -m src.cli production-refresh \
  --firm-activation-manifest deploy/iapd-firm-activations/iapdfirm20261107.json
```

The scheduler accepts the same path through
`IAPD_FIRM_ACTIVATION_MANIFEST`. Invalid or changed pinned snapshots are moved
under `data/quarantine/iapd-firms/` and never become active. Run manifests and
the Bronze reconciliation report record the discovery mode, official
filenames and URLs, activation-manifest hash, actual artifact hashes, and
validation results.

Dashboard migrations must be applied before publishing a canonical snapshot.
Registered-firm, ERA-only, dual-registration, and acquisition-target counts are
separate. Historical SEC-only datasets retain null registration classification.
