import json

from src.reports.exporters import ReportExporter
from src.reports.models import HistoricalSummary


def test_historical_json_can_be_read_back(tmp_path):
    summary = HistoricalSummary()

    result = ReportExporter(tmp_path).export_historical_report(summary)

    with result["json"].open(encoding="utf-8") as report_file:
        payload = json.load(report_file)

    assert payload["report_type"] == "historical"
    assert payload["period"] == "start_to_end"
    assert payload["data"]["total_datasets"] == 0
