import pytest
import json
import csv
from pathlib import Path
from datetime import datetime
from src.reports.models import MonthlySummary, HistoricalSummary, DatasetSummary
from src.reports.exporters import ReportExporter

@pytest.fixture
def temp_export_dir(tmp_path):
    return tmp_path / "exports"

@pytest.fixture
def exporter(temp_export_dir):
    return ReportExporter(base_dir=temp_export_dir)

def test_export_daily_json_markdown(exporter, temp_export_dir):
    summary = MonthlySummary(year=2023, month=1, month_key="2023-01")
    summary.total_ingestion_attempts = 1
    summary.successful_ingestions = 1
    summary.datasets_processed = ["v1"]
    summary.latest_dataset = "v1"
    summary.latest_ingestion_date = "2023-01-01T10:00:00"
    summary.avg_quality_score = 0.95
    
    results = exporter.export_daily_report(summary)
    
    assert results["json"].exists()
    assert results["markdown"].exists()
    assert "daily/2023-01-01" in str(results["json"])
    
    with open(results["json"]) as f:
        data = json.load(f)
        assert data["report_metadata"]["report_type"] == "daily"
        assert data["summary"]["total_ingestion_attempts"] == 1

def test_export_monthly_json_markdown(exporter, temp_export_dir):
    summary = MonthlySummary(year=2023, month=1, month_key="2023-01")
    results = exporter.export_monthly_report(summary)
    
    assert results["json"].exists()
    assert results["markdown"].exists()
    assert "monthly/2023-01" in str(results["json"])

def test_export_historical_all_formats(exporter, temp_export_dir):
    ds = DatasetSummary(dataset_version="v1", status="success", file_size=1000)
    summary = HistoricalSummary(start_date="2023-01-01", end_date="2023-02-01")
    summary.dataset_summaries = [ds]
    
    results = exporter.export_historical_report(summary)
    
    assert results["json"].exists()
    assert results["markdown"].exists()
    assert results["csv_datasets"].exists()
    
    with open(results["csv_datasets"]) as f:
        reader = csv.reader(f)
        rows = list(reader)
        assert rows[0] == ["version", "date", "status", "size_bytes", "quality_score"]
        assert rows[1][0] == "v1"

def test_empty_period_handling(exporter):
    summary = MonthlySummary(year=2023, month=1, month_key="2023-01")
    # No datasets added
    results = exporter.export_daily_report(summary)
    assert "No datasets found" in results["markdown"].read_text()

def test_nested_model_serialization(exporter):
    # Historical report includes MonthlySummary and DatasetSummary lists
    ds = DatasetSummary(dataset_version="v1", quality_score=0.9)
    ms = MonthlySummary(year=2023, month=1, month_key="2023-01")
    summary = HistoricalSummary()
    summary.dataset_summaries = [ds]
    summary.monthly_summaries = [ms]
    
    results = exporter.export_historical_report(summary)
    with open(results["json"]) as f:
        data = json.load(f)
        assert len(data["summary"]["dataset_summaries"]) == 1
        assert data["summary"]["dataset_summaries"][0]["quality_score"] == 0.9

def test_none_value_preservation(exporter):
    ds = DatasetSummary(dataset_version="v1", quality_score=None)
    summary = HistoricalSummary()
    summary.dataset_summaries = [ds]
    
    results = exporter.export_historical_report(summary)
    with open(results["json"]) as f:
        data = json.load(f)
        assert data["summary"]["dataset_summaries"][0]["quality_score"] is None

def test_invalid_path_error_handling(tmp_path):
    # Path to a file, making it an unwritable directory
    bad_path = tmp_path / "file.txt"
    bad_path.write_text("not a dir")

    with pytest.raises(OSError):
        ReportExporter(base_dir=bad_path)