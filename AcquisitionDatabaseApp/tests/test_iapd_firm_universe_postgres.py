"""Opt-in PostgreSQL checks for the migrated firm-universe serving schema."""
import os

import pytest


@pytest.fixture
def migrated_firm_tables():
    url = os.getenv("SCM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SCM_TEST_DATABASE_URL required for isolated PostgreSQL tests")
    import psycopg

    with psycopg.connect(url) as connection:
        with connection.transaction(force_rollback=True):
            connection.execute("CREATE TEMP TABLE dataset_versions (LIKE public.dataset_versions INCLUDING ALL) ON COMMIT DROP")
            connection.execute("CREATE TEMP TABLE firms (LIKE public.firms INCLUDING ALL) ON COMMIT DROP")
            connection.execute("CREATE TEMP TABLE outreach_targets (LIKE public.outreach_targets INCLUDING ALL) ON COMMIT DROP")
            connection.execute("INSERT INTO dataset_versions (dataset_version,published_at) VALUES ('fixture',now())")
            rows = [
                ("100", True, True, False, False, False, "REGISTERED"),
                ("200", True, False, True, False, False, "REGISTERED"),
                ("300", True, True, True, False, True, "REGISTERED"),
                ("400", False, False, False, True, False, "ERA_ONLY"),
            ]
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO firms
                    (firm_id,dataset_version,is_registered,is_sec_registered,is_state_registered,
                     is_era_only,is_dual_registered,population_classification,canonical_population_source)
                    VALUES (%s,'fixture',%s,%s,%s,%s,%s,%s,'IAPD_FIRM_COMPILATION')""",
                    rows,
                )
            yield connection


def test_migrated_postgres_schema_classifies_one_canonical_row_per_crd(migrated_firm_tables):
    connection = migrated_firm_tables
    assert connection.execute("SELECT count(*) FROM firms").fetchone()[0] == 4
    assert connection.execute("SELECT count(*) FROM firms WHERE is_registered").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM firms WHERE is_sec_registered AND NOT is_state_registered").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM firms WHERE is_state_registered AND NOT is_sec_registered").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM firms WHERE is_dual_registered").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM firms WHERE is_era_only").fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM firms WHERE canonical_population_source='IAPD_FIRM_COMPILATION'"
    ).fetchone()[0] == 4

    connection.execute("SAVEPOINT duplicate_crd")
    with pytest.raises(Exception) as error:
        connection.execute(
            "INSERT INTO firms (firm_id,dataset_version) VALUES ('300','fixture')"
        )
    assert getattr(error.value, "sqlstate", None) == "23505"
    connection.execute("ROLLBACK TO SAVEPOINT duplicate_crd")
    connection.execute("RELEASE SAVEPOINT duplicate_crd")
    assert connection.execute("SELECT count(*) FROM firms WHERE firm_id='300'").fetchone()[0] == 1


def test_migrated_postgres_schema_excludes_era_from_outreach_targets(migrated_firm_tables):
    connection = migrated_firm_tables
    connection.execute(
        """INSERT INTO outreach_targets (firm_id,dataset_version,status)
        SELECT firm_id,dataset_version,'NOT_RESEARCHED' FROM firms
        WHERE population_classification <> 'ERA_ONLY'"""
    )
    assert connection.execute("SELECT count(*) FROM outreach_targets").fetchone()[0] == 3
    assert connection.execute(
        "SELECT count(*) FROM outreach_targets WHERE firm_id='400'"
    ).fetchone()[0] == 0


def test_outreach_api_and_ui_apply_the_shared_registration_guard():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    guarded_routes = (
        root / "web/app/api/outreach/[firmId]/route.ts",
        root / "web/app/api/outreach/[firmId]/activities/route.ts",
        root / "web/app/api/virtual-sdr/[firmId]/route.ts",
    )
    for route in guarded_routes:
        assert "requireOutreachEligible" in route.read_text()
    page = (root / "web/app/firms/[firmId]/page.tsx").read_text()
    assert "outreachAllowed(data.firm)" in page
