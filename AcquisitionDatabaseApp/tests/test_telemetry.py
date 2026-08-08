"""Tests for telemetry and operational readiness."""

import pytest
from src.telemetry import (
    get_stats,
    ExecutionTimer,
    HealthReport,
    ExecutionSummary,
    warn_row_drop,
    warn_schema_drift,
    warn_missing_table,
    warn_download_failed,
    warn_storage_issue,
)


def test_get_stats():
    stats = get_stats()
    assert "cpu_percent" in stats
    assert "memory_percent" in stats
    assert "disk_percent" in stats
    assert "disk_free_gb" in stats
    assert 0 <= stats["cpu_percent"] <= 100
    assert 0 <= stats["memory_percent"] <= 100


def test_execution_timer():
    with ExecutionTimer("test_op") as timer:
        pass
    assert timer.duration is not None
    assert timer.duration >= 0


def test_health_report():
    hr = HealthReport()
    report = hr.run_all()
    assert "healthy" in report
    assert "checks" in report
    assert len(report["checks"]) == 5
    for check in report["checks"]:
        assert check["status"] in ("PASS", "FAIL")
        assert "name" in check
        assert "value" in check
        assert "threshold" in check


def test_execution_summary():
    es = ExecutionSummary("data/logs/pipeline.log")
    summary = es.get_summary()
    assert "total_executions" in summary
    assert "successful" in summary
    assert "failed" in summary
    assert "success_rate" in summary


def test_warning_emitters(caplog):
    warn_row_drop(100, 80, "test_table")
    warn_schema_drift(["col1"], ["col2"], "test_table")
    warn_missing_table("missing", "dataset1")
    warn_download_failed("http://example.com", "timeout")
    warn_storage_issue("/tmp/test", "permission denied")
    
    assert any("ROW_DROP" in r.message for r in caplog.records)
    assert any("SCHEMA_DRIFT" in r.message for r in caplog.records)
    assert any("MISSING_TABLE" in r.message for r in caplog.records)
    assert any("DOWNLOAD_FAILED" in r.message for r in caplog.records)
    assert any("STORAGE_ISSUE" in r.message for r in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])