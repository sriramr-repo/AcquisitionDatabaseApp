import pytest
import json
import csv
from pathlib import Path
from src.reports.models import MonthlySummary, HistoricalSummary, DatasetSummary
from src.reports.exporters import ReportExporter

def test_export_monthly_json_markdown(tmp_path):
    exporter = ReportExporter(base_dir=tmp_path)
    summary = MonthlySummary(year=2026, month=8, month_key="2026-08")
    summary.total_ingestion_attempts = 1
    summary.successful_ingestions = 1
    summary.success_rate = 100.0
    
    results = exporter.export_monthly_report(summary)
    
    assert "json" in results
    assert "markdown" in results
    assert results["json"].exists()
    assert results["markdown"].exists()
    
    # Verify JSON content
    with open(results["json"], 'r') as f:
        data = json.load(f)
        assert data["report_metadata"]["report_type"] == "monthly"
        assert data["summary"]["month_key"] == "2026-08"

def test_export_historical_csv(tmp_path):
    exporter = ReportExporter(base_dir=tmp_path)
    summary = HistoricalSummary(start_date="2026-01-01", end_date="2026-06-01")
    ds = DatasetSummary(dataset_version="ia07012026", status="success", file_size=1024)
    summary.dataset_summaries = [ds]
    summary.dataset_versions = ["ia07012026"]
    
    results = exporter.export_historical_report(summary)
    
    assert "csv_datasets" in results
    assert results["csv_datasets"].exists()
    
    with open(results["csv_datasets"], 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["version"] == "ia07012026"
        assert rows[0]["size_bytes"] == "1024"