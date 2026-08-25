import json
import csv
from dataclasses import asdict
from datetime import date, datetime

import pytest

from src.reports.exporters import ReportExporter
from src.reports.models import (
    DatasetSummary,
    ExecutionSummary,
    HistoricalSummary,
    MonthlySummary,
)


def read_report(path):
    with path.open(encoding="utf-8") as report_file:
        return json.load(report_file)


def test_daily_json_export_and_date_serialization(tmp_path):
    summary = MonthlySummary(
        year=2026,
        month=8,
        month_key="2026-08",
        latest_ingestion_date=datetime(2026, 8, 16, 10, 30),
        total_ingestion_attempts=1,
        successful_ingestions=1,
        datasets_processed=["v1"],
    )

    result = ReportExporter(tmp_path).export_daily_report(summary)
    path = result["json"]
    markdown_path = result["markdown"]
    csv_path = result["csv"]

    assert path == tmp_path / "daily" / "2026-08-16" / "daily_report.json"
    assert markdown_path == tmp_path / "daily" / "2026-08-16" / "daily_report.md"
    assert csv_path == tmp_path / "daily" / "2026-08-16" / "daily_report.csv"
    payload = read_report(path)
    assert payload["report_type"] == "daily"
    assert payload["period"] == "2026-08-16"
    assert payload["data"]["latest_ingestion_date"] == "2026-08-16T10:30:00"
    expected_data = asdict(summary)
    expected_data["latest_ingestion_date"] = "2026-08-16T10:30:00"
    assert payload["data"] == expected_data
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        csv_rows = list(csv.DictReader(csv_file))
    assert csv_rows[0]["dataset_version"] == "v1"

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# SCM RIA Acquisition Intelligence" in markdown
    assert "## Daily Pipeline Report — 2026-08-16" in markdown
    assert "| Dataset | Date | Status | File Size | Quality Score |" in markdown


def test_monthly_json_export_preserves_none_and_zero(tmp_path):
    summary = MonthlySummary(
        year=2026,
        month=8,
        month_key="2026-08",
        total_ingestion_attempts=0,
        total_file_size_bytes=0,
        avg_quality_score=None,
    )

    result = ReportExporter(tmp_path).export_monthly_report(summary)
    path = result["json"]
    payload = read_report(path)

    assert path == tmp_path / "monthly" / "2026-08" / "monthly_report.json"
    assert payload["period"] == "2026-08"
    assert payload["data"]["total_file_size_bytes"] == 0
    assert payload["data"]["avg_quality_score"] is None
    with result["csv"].open(newline="", encoding="utf-8") as csv_file:
        csv_reader = csv.reader(csv_file)
        csv_rows = list(csv_reader)
    assert csv_rows[0][0] == "dataset_version"
    assert len(csv_rows) == 1

    markdown = path.with_name("monthly_report.md").read_text(encoding="utf-8")
    assert "## Monthly Pipeline Report — 2026-08" in markdown
    assert "Success rate: 0.0%" in markdown
    assert "Average quality score: Unavailable" in markdown


def test_historical_json_export_serializes_nested_models(tmp_path):
    execution = ExecutionSummary(
        dataset_version="v1",
        status="success",
        download_timestamp=datetime(2026, 1, 15, 12, 0),
    )
    monthly = MonthlySummary(
        year=2026,
        month=1,
        month_key="2026-01",
        executions=[execution],
    )
    dataset = DatasetSummary(
        dataset_version="v1",
        ingestion_date=date(2026, 1, 15),
        quality_score=None,
    )
    summary = HistoricalSummary(
        start_date="2026-01-01",
        end_date="2026-02-01",
        dataset_versions=["v1"],
        monthly_summaries=[monthly],
        dataset_summaries=[dataset],
    )

    result = ReportExporter(tmp_path).export_historical_report(summary)
    path = result["json"]
    payload = read_report(path)

    assert path == (
        tmp_path
        / "historical"
        / "2026-01-01_to_2026-02-01"
        / "historical_report.json"
    )
    assert payload["report_type"] == "historical"
    assert payload["period"] == "2026-01-01_to_2026-02-01"
    assert payload["data"]["monthly_summaries"][0]["executions"][0]["dataset_version"] == "v1"
    assert payload["data"]["monthly_summaries"][0]["executions"][0]["download_timestamp"] == "2026-01-15T12:00:00"
    assert payload["data"]["dataset_summaries"][0]["ingestion_date"] == "2026-01-15"
    assert payload["data"]["dataset_summaries"][0]["quality_score"] is None
    assert result["dataset_csv"].name == "dataset_history.csv"
    with result["dataset_csv"].open(newline="", encoding="utf-8") as csv_file:
        dataset_rows = list(csv.DictReader(csv_file))
    assert dataset_rows[0]["dataset_version"] == "v1"
    assert dataset_rows[0]["ingestion_date"] == "2026-01-15"
    assert dataset_rows[0]["quality_score"] == ""

    markdown = result["markdown"].read_text(encoding="utf-8")
    assert "## Historical Pipeline Report" in markdown
    assert "**Period:** 2026-01-01 → 2026-02-01" in markdown
    assert "### Dataset History" in markdown
    assert "### Monthly Summary" in markdown
    assert "| Dataset | Ingestion Date | Status | File Size | Quality Score |" in markdown


def test_empty_daily_period_uses_explicit_date(tmp_path):
    summary = MonthlySummary(year=2026, month=8, month_key="2026-08")

    path = ReportExporter(tmp_path).export_daily_report(
        summary,
        report_date="2026-08-16",
    )["json"]
    payload = read_report(path)

    assert payload["data"]["total_ingestion_attempts"] == 0
    assert payload["data"]["datasets_processed"] == []
    markdown = path.with_name("daily_report.md").read_text(encoding="utf-8")
    assert "No datasets found for this reporting period." in markdown


def test_empty_daily_period_requires_date(tmp_path):
    summary = MonthlySummary(year=2026, month=8, month_key="2026-08")

    with pytest.raises(ValueError, match="report_date is required"):
        ReportExporter(tmp_path).export_daily_report(summary)


def test_empty_historical_period_exports_valid_json(tmp_path):
    summary = HistoricalSummary(start_date="2026-01-01", end_date="2026-02-01")

    result = ReportExporter(tmp_path).export_historical_report(summary)
    path = result["json"]
    payload = read_report(path)

    assert payload["data"]["total_datasets"] == 0
    assert payload["data"]["dataset_versions"] == []
    with result["dataset_csv"].open(newline="", encoding="utf-8") as csv_file:
        assert list(csv.reader(csv_file)) == [list(ReportExporter._DATASET_CSV_HEADERS)]
    markdown = path.with_name("historical_report.md").read_text(encoding="utf-8")
    assert "No datasets found for this reporting period." in markdown


def test_export_creates_nested_directories_and_replaces_same_report(tmp_path):
    exporter = ReportExporter(tmp_path / "exports" / "reports")
    first = MonthlySummary(year=2026, month=8, month_key="2026-08")
    second = MonthlySummary(
        year=2026,
        month=8,
        month_key="2026-08",
        total_ingestion_attempts=1,
    )

    first_result = exporter.export_monthly_report(first)
    second_result = exporter.export_monthly_report(second)
    path = first_result["json"]
    replaced_path = second_result["json"]

    assert replaced_path == path
    assert read_report(path)["data"]["total_ingestion_attempts"] == 1
    assert second_result["markdown"] == first_result["markdown"]
    assert "Total ingestion attempts: 1" in second_result["markdown"].read_text(encoding="utf-8")


def test_csv_dataset_fields_preserve_none_zero_and_iso_dates(tmp_path):
    execution = ExecutionSummary(
        dataset_version="v1",
        status="success",
        download_timestamp=datetime(2026, 8, 16, 10, 30),
        file_size=0,
        bronze_rows=0,
        silver_rows=None,
        gold_rows=0,
        quality_score=None,
    )
    summary = MonthlySummary(
        year=2026,
        month=8,
        month_key="2026-08",
        executions=[execution],
    )

    result = ReportExporter(tmp_path).export_monthly_report(summary)

    with result["csv"].open(newline="", encoding="utf-8") as csv_file:
        row = next(csv.DictReader(csv_file))
    assert row["dataset_version"] == "v1"
    assert row["ingestion_date"] == "2026-08-16T10:30:00"
    assert row["file_size_bytes"] == "0"
    assert row["bronze_rows"] == "0"
    assert row["silver_rows"] == ""
    assert row["gold_rows"] == "0"
    assert row["quality_score"] == ""


def test_historical_change_csvs_are_created_only_when_data_exists(tmp_path):
    summary = HistoricalSummary(
        start_date="2026-01-01",
        end_date="2026-02-01",
        schema_changes_history=[
            {"dataset_version": "v1", "changes": {"missing": ["a"], "extra": []}}
        ],
        data_changes_history=[
            {"dataset_version": "v1", "changes": {"added_count": 2, "modified_count": 0}}
        ],
        monthly_summaries=[MonthlySummary(year=2026, month=1, month_key="2026-01")],
    )

    result = ReportExporter(tmp_path).export_historical_report(summary)

    assert result["schema_changes_csv"].name == "schema_changes.csv"
    assert result["data_changes_csv"].name == "data_changes.csv"
    assert result["monthly_csv"].name == "monthly_summary.csv"
    assert "schema_changes_count" in result["schema_changes_csv"].read_text(encoding="utf-8").splitlines()[0]
    assert "records_added" in result["data_changes_csv"].read_text(encoding="utf-8").splitlines()[0]


def test_cross_format_values_and_special_character_escaping(tmp_path):
    execution = ExecutionSummary(
        dataset_version="v|1\n*_[x]",
        status="success",
        download_timestamp="2026-08-16T10:30:00",
        file_name='firm,"quoted".csv',
        file_size=0,
        quality_score=0.95,
    )
    summary = MonthlySummary(
        year=2026,
        month=8,
        month_key="2026-08",
        executions=[execution],
    )

    result = ReportExporter(tmp_path).export_monthly_report(summary)
    payload = read_report(result["json"])
    with result["csv"].open(newline="", encoding="utf-8") as csv_file:
        csv_row = next(csv.DictReader(csv_file))
    markdown = result["markdown"].read_text(encoding="utf-8")

    assert payload["data"]["executions"][0]["dataset_version"] == "v|1\n*_[x]"
    assert csv_row["dataset_version"] == "v|1\n*_[x]"
    assert csv_row["file_name"] == 'firm,"quoted".csv'
    assert csv_row["file_size_bytes"] == "0"
    assert csv_row["quality_score"] == "0.95"
    assert "v\\|1 \\*\\_\\[x\\]" in markdown


def test_invalid_report_object_fails_explicitly(tmp_path):
    with pytest.raises(AttributeError):
        ReportExporter(tmp_path).export_monthly_report(object())


def test_invalid_base_directory_raises(tmp_path):
    bad_path = tmp_path / "file.txt"
    bad_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError):
        ReportExporter(bad_path)
