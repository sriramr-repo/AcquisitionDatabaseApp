# ADR: Canonical Data Model for SCM RIA Intelligence

## 1. Canonical Entities
- **`Firm`**: Primary entity for adviser profiles, AUM, and regulatory status.
- **`FirmOffice`**: Normalizes physical locations linked to `firm_id`.
- **`FirmAcquiredFirm`**: Tracks M&A lineage for structural intelligence.

## 2. Rationalization
Entities provide a stable, normalized interface for disparate regulatory data. They decouple identification from physical footprint and historical acquisition links, ensuring consistent join paths.

## 3. SEC Mapping
- **`Firm`**: Maps to firm identifiers, financial fields, and regulatory flags in SEC Form ADV filings.
- **`FirmOffice`**: Maps to physical location schedules and contact metadata.
- **`FirmAcquiredFirm`**: Maps to successor/predecessor declarations in regulatory records.

## 4. Normalization Strategy
A star-schema approach was chosen to balance write performance (low redundancy) with read-heavy analytical needs. By isolating transient attributes (`FirmOffice`) from static identity (`Firm`), we maintain a source of truth that supports schema versioning.

## 5. Architectural Enablement
- **Acquisition Scoring**: Linked records enable graph traversals (parent/subsidiary chains).
- **Historical Analysis**: `dataset_version` and `record_hash` permit time-series "as-of" snapshot reconstruction.
- **Research Enrichment**: `firm_id` provides a stable key for external data injection (e.g., news sentiment, private equity deal flow).
- **Reporting**: Decoupled models enable granular domain reporting without querying giant, wide tables.