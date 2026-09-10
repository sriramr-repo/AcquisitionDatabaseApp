import json
from datetime import date

import duckdb

from src.iapd_local import _create_local_schema, compare_local_snapshots


def _snapshot(path, snapshot_id, people, links):
    with duckdb.connect(str(path)) as connection:
        _create_local_schema(connection)
        connection.execute(
            "INSERT INTO iapd_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [snapshot_id, "dataset", date(2026, 9, 1), "https://example.test/feed.zip",
             "feed.zip", "hash", "schema", len(people), len(links), len(links), len(links),
             len({row[1] for row in links}), 0],
        )
        for crd, disclosures in people:
            payload = json.dumps({"disclosures": disclosures})
            connection.execute(
                "INSERT INTO iapd_people VALUES (?,?,?,?,?,?)",
                [snapshot_id, crd, f"Person {crd}", True, None, payload],
            )
        for crd, firm, registrations, city in links:
            payload = json.dumps({
                "registrations": registrations, "city": city,
                "address_line_1": "1 Main St",
            })
            connection.execute(
                "INSERT INTO iapd_current_links VALUES (?,?,?,?,?)",
                [snapshot_id, firm, crd, f"{crd}-{firm}", payload],
            )


def test_compare_local_snapshots_reports_changes_and_writes_json(tmp_path):
    previous, current = tmp_path / "previous.duckdb", tmp_path / "current.duckdb"
    _snapshot(
        previous, "p", [("1", []), ("2", []), ("3", [{"criminal": False}])],
        [("1", "10", [{"status": "APPROVED"}], "Boston"),
         ("2", "20", [], "Boston"), ("3", "30", [], "Boston")],
    )
    _snapshot(
        current, "c", [("1", []), ("3", [{"criminal": True}]), ("4", [])],
        [("1", "11", [{"status": "APPROVED"}], "Boston"),
         ("3", "30", [{"status": "REVOKED"}], "Cambridge"),
         ("4", "40", [], "Boston")],
    )
    report_path = tmp_path / "report.json"
    report = compare_local_snapshots(
        current_database=current, previous_database=previous,
        report_path=report_path, sample_limit=10,
    )
    assert report["counts"] == {
        "new_representatives": 1,
        "disappeared_representatives": 1,
        "employer_changes": 1,
        "registration_changes": 1,
        "disclosure_changes": 1,
        "material_contact_changes": 1,
    }
    assert json.loads(report_path.read_text())["samples"]["new_representatives"] == ["4"]
    assert report["affected_firm_count"] == 5
    firm_changes = {row["firm_id"]: row for row in report["firm_changes"]}
    assert firm_changes["10"]["counts"]["employer_changes"] == 1
    assert firm_changes["11"]["counts"]["employer_changes"] == 1
    assert firm_changes["20"]["counts"]["disappeared_representatives"] == 1
    assert firm_changes["30"]["counts"]["registration_changes"] == 1
    assert firm_changes["30"]["counts"]["disclosure_changes"] == 1
    assert firm_changes["30"]["counts"]["material_contact_changes"] == 1
    assert firm_changes["40"]["counts"]["new_representatives"] == 1
    assert "does not establish termination" in report["interpretation_guardrails"][0]

    second_path = tmp_path / "second.json"
    second = compare_local_snapshots(
        current_database=current, previous_database=previous,
        report_path=second_path, sample_limit=10,
    )
    assert second == report
    assert second_path.read_bytes() == report_path.read_bytes()


def test_compare_local_snapshots_emits_baseline_without_prior(tmp_path):
    current = tmp_path / "current.duckdb"
    _snapshot(current, "c", [("1", [])], [("1", "10", [], "Boston")])
    report = compare_local_snapshots(
        current_database=current, previous_database=None,
    )
    assert report["status"] == "baseline"
    assert all(value == 0 for value in report["counts"].values())
    assert report["firm_changes"] == []
    assert report["affected_firm_count"] == 0
