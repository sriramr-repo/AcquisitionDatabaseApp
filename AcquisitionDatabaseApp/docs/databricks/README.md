# Databricks Delta Sync

The analytics pipeline runs locally on DuckDB. `delta-sync` copies its finished **gold** tables into
**Delta Lake** tables that Databricks can register in **Unity Catalog**. Operational state (agent
research, contacts, outreach) stays in **Neon Postgres** and is never part of this export.

## Where it fits

```mermaid
flowchart LR
    subgraph OLTP["Operational (Neon Postgres)"]
        A1[Research agents] --> N[(firm_research<br/>contacts<br/>outreach_activities<br/>iapd_live_captures)]
    end

    subgraph Local["Analytics (DuckDB, local)"]
        SEC[SEC Form ADV<br/>monthly roster] --> B[Bronze<br/>raw files]
        B --> S[Silver<br/>normalized firms]
        S --> G[Gold<br/>gold_scm_acquisition_v1_&lt;version&gt;]
    end

    subgraph Lakehouse["Databricks Lakehouse"]
        V[/Unity Catalog volume<br/>Delta files/] --> T[(Managed Delta table<br/>catalog.acquisition_gold.*)]
        T --> SQL[SQL warehouse<br/>dashboards & analysis]
    end

    G -- "sec-pipeline delta-sync" --> D[/Local Delta tables<br/>data/exports/delta/] 
    D -- "upload" --> V
    N -. "kept separate" .- G
```

## How one gold table becomes one Delta table

DuckDB stores one table per monthly dataset version. `delta-sync` folds every version into a single
Delta table, partitioned by `dataset_version`.

```mermaid
flowchart LR
    T1["gold_scm_acquisition_v1_ia07012026"] --> P1["dataset_version=ia07012026/"]
    T2["gold_scm_acquisition_v1_ia08032026_0"] --> P2["dataset_version=ia08032026_0/"]
    subgraph Delta["Delta table: gold_scm_acquisition_v1"]
        LOG[_delta_log/]
        P1
        P2
    end
```

- **Table names** are parsed as `gold_<name>_<dataset_version>`; `<name>` becomes the Delta table name.
- **Re-runs are safe.** Each run overwrites only the partitions for the versions it syncs
  (`predicate = dataset_version = '<version>'`); other versions are left alone.
- **Schema drift is merged** (`schema_mode="merge"`), so a newly added gold column doesn't fail the write.
- **An existing `dataset_version` column is reused** and set from the table name, never duplicated.
- **Writes nothing to Databricks itself.** The job prints `CREATE TABLE` statements and writes a
  `_sync_manifest.json` with row counts per table and version.

## Usage

Install the optional dependency:

```bash
pip install -e '.[delta]'
```

Preview what would be exported (reads DuckDB, writes nothing):

```bash
SCM_ENV=PROD python3 -m src.cli delta-sync --dry-run --catalog workspace
```

Export one version to a local folder:

```bash
SCM_ENV=PROD python3 -m src.cli delta-sync --version ia08032026_0 --catalog workspace
```

Write straight to cloud storage that Databricks can read (credentials come from the environment,
e.g. `AWS_PROFILE` / `AWS_REGION`):

```bash
SCM_ENV=PROD python3 -m src.cli delta-sync --target s3://<bucket>/acquisition_gold
```

| Option | Default | Meaning |
|---|---|---|
| `--target` | `<data>/exports/delta` | Local folder or `s3://`, `abfss://`, `gs://` URI |
| `--version` | all versions | Dataset version to sync; repeat for several |
| `--catalog` | `main` | Unity Catalog catalog used in the printed DDL |
| `--schema` | `acquisition_gold` | Schema used in the printed DDL |
| `--dry-run` | off | Count rows and print DDL without writing |

## Loading into Unity Catalog

```mermaid
sequenceDiagram
    participant L as Local machine
    participant V as UC volume
    participant W as SQL warehouse
    L->>L: delta-sync --version ia08032026_0
    L->>V: databricks fs cp -r gold_scm_acquisition_v1 dbfs:/Volumes/.../raw/
    L->>W: CREATE OR REPLACE TABLE ... AS SELECT * FROM delta.`/Volumes/...`
    W-->>L: SELECT dataset_version, count(*) → verify against manifest
```

```bash
databricks schemas create acquisition_gold workspace
databricks volumes create workspace acquisition_gold raw MANAGED
databricks fs cp -r data/exports/delta/gold_scm_acquisition_v1 \
  dbfs:/Volumes/workspace/acquisition_gold/raw/gold_scm_acquisition_v1
```

```sql
CREATE OR REPLACE TABLE workspace.acquisition_gold.gold_scm_acquisition_v1
AS SELECT * FROM delta.`/Volumes/workspace/acquisition_gold/raw/gold_scm_acquisition_v1`;

SELECT dataset_version, count(*) FROM workspace.acquisition_gold.gold_scm_acquisition_v1 GROUP BY 1;
```

Unity Catalog does not allow an external table whose location is inside a volume, so the volume is a
landing zone and the table is a managed copy. The `CREATE TABLE ... LOCATION` statements the job prints
are for cloud-storage targets, not local folders.

**First load (Oct 2026):** `ia08032026_0`, 17,018 rows, row count matched DuckDB.

## Tests

```bash
python3 -m pytest tests/test_delta_sync.py
```

Covers table-name parsing, writing two versions into one partitioned table, idempotent re-runs, an
existing `dataset_version` column, and the manifest.
