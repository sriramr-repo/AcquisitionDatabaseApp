"""
Standardized report exporters for SCM RIA Acquisition Intelligence Platform.
Turns reporting models into JSON, Markdown, and CSV files.
"""
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Union

from src.config import settings
from src.reports.models import (
    DatasetSummary,
    MonthlySummary,
    HistoricalSummary,
)

class ReportExporter:
    """Handles serialization and file writing for various report types."""
    
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or settings.BASE_DIR / "exports" / "reports"
        if self.base_dir.exists() and not self.base_dir.is_dir():
            raise OSError(f"Base dir path exists and is not a directory: {self.base_dir}")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_report_path(self, type_name: str, period: str, filename: str) -> Path:
        """Constructs and creates output directory."""
        report_dir = self.base_dir / type_name / period
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir / filename

    def export_daily_report(self, summary: MonthlySummary) -> Dict[str, Path]:
        """Export daily summary to JSON and Markdown."""
        period = summary.month_key
        date_str = summary.latest_ingestion_date[:10] if summary.latest_ingestion_date else "unknown"
        results = {}

        # 1. JSON
        json_data = {
            "report_metadata": {
                "report_type": "daily",
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "date": date_str
            },
            "summary": summary.to_dict()
        }
        json_path = self._get_report_path("daily", date_str, f"daily_{date_str}.json")
        json_path.write_text(json.dumps(json_data, indent=2))
        results["json"] = json_path

        # 2. Markdown
        md_content = self._render_daily_markdown(summary, date_str)
        md_path = self._get_report_path("daily", date_str, f"daily_{date_str}.md")
        md_path.write_text(md_content)
        results["markdown"] = md_path

        return results

    def export_monthly_report(self, summary: MonthlySummary) -> Dict[str, Path]:
        """Export monthly summary to JSON and Markdown."""
        period = summary.month_key
        results = {}
        
        # 1. JSON
        json_data = {
            "report_metadata": {
                "report_type": "monthly",
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "period": period,
                "version": "1.0"
            },
            "summary": summary.to_dict(),
            "executions": [vars(e) for e in summary.executions]
        }
        json_path = self._get_report_path("monthly", period, f"report_{period}.json")
        json_path.write_text(json.dumps(json_data, indent=2))
        results["json"] = json_path

        # 2. Markdown
        md_content = self._render_monthly_markdown(summary)
        md_path = self._get_report_path("monthly", period, f"report_{period}.md")
        md_path.write_text(md_content)
        results["markdown"] = md_path
        
        return results

    def export_historical_report(self, summary: HistoricalSummary) -> Dict[str, Path]:
        """Export historical summary to JSON, Markdown, and CSV."""
        date_str = f"{summary.start_date or 'start'}_to_{summary.end_date or 'end'}"
        results = {}

        # 1. JSON
        json_data = {
            "report_metadata": {
                "report_type": "historical",
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "period": date_str
            },
            "summary": summary.to_dict()
        }
        json_path = self._get_report_path("historical", date_str, f"historical_{date_str}.json")
        json_path.write_text(json.dumps(json_data, indent=2))
        results["json"] = json_path

        # 2. CSV - Dataset History
        csv_path = self._get_report_path("historical", date_str, f"datasets_{date_str}.csv")
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["version", "date", "status", "size_bytes", "quality_score"])
            for ds in summary.dataset_summaries:
                writer.writerow([
                    ds.dataset_version, ds.ingestion_date, ds.status, 
                    ds.file_size or 0, ds.quality_score or "N/A"
                ])
        results["csv_datasets"] = csv_path

        # 3. Markdown
        md_content = self._render_historical_markdown(summary)
        md_path = self._get_report_path("historical", date_str, f"historical_{date_str}.md")
        md_path.write_text(md_content)
        results["markdown"] = md_path

        return results

    def _render_daily_markdown(self, s: MonthlySummary, date_str: str) -> str:
        """Converts Daily summary to Markdown string."""
        return f"""# SCM RIA Acquisition Intelligence
## Daily Pipeline Report: {date_str}

### Executive Summary
- **Attempts:** {s.total_ingestion_attempts}
- **Successes:** {s.successful_ingestions}
- **Failures:** {s.failed_ingestions}
- **Latest Dataset:** {s.latest_dataset or "N/A"}

### Data Quality
- **Avg Quality Score:** {f"{s.avg_quality_score:.4f}" if s.avg_quality_score else "N/A"}
- **Total Warnings:** {s.total_warnings}

### Datasets Processed
{chr(10).join([f"- {ds}" for ds in s.datasets_processed]) if s.datasets_processed else "No datasets found for this period."}

_Generated at: {datetime.utcnow().isoformat()}Z_
"""

    def _render_monthly_markdown(self, s: MonthlySummary) -> str:
        """Converts MonthlySummary to Markdown string."""
        return f"""# SCM RIA Acquisition Intelligence
## Monthly Pipeline Report: {s.month_key}

### Executive Summary
- **Attempts:** {s.total_ingestion_attempts}
- **Successes:** {s.successful_ingestions}
- **Failures:** {s.failed_ingestions}
- **Skipped:** {s.skipped_ingestions}
- **Success Rate:** {s.success_rate:.1f}%
- **Latest Dataset:** {s.latest_dataset or "N/A"}

### Data Quality
- **Avg Quality Score:** {f"{s.avg_quality_score:.4f}" if s.avg_quality_score else "N/A"}
- **Total Warnings:** {s.total_warnings}
- **Total Errors:** {s.total_errors}

### Dataset Activity
| Version | Date | Status | Size (MB) | Quality |
|---------|------|--------|-----------|---------|
{chr(10).join([f"| {d.dataset_version} | {d.ingestion_date[:10] if d.ingestion_date else 'N/A'} | {d.status} | {((d.file_size or 0)/1024/1024):.2f} | {d.quality_score or 'N/A'} |" for d in s.executions if hasattr(d, 'dataset_version')])}

### Limitations
- Execution duration and resource metrics (CPU/RAM) are currently not historically persisted in structured form.
- Record of rows dropped or specific schema drift counts are sourced from artifacts where available.

_Generated at: {datetime.utcnow().isoformat()}Z_
"""

    def _render_historical_markdown(self, s: HistoricalSummary) -> str:
        """Converts HistoricalSummary to Markdown string."""
        return f"""# SCM RIA Acquisition Intelligence
## Historical Operational Report
**Period:** {s.start_date or "Inception"} to {s.end_date or "Present"}

### Summary Metrics
- **Total Datasets:** {s.total_datasets}
- **Successful:** {s.successful_datasets}
- **Failed:** {s.failed_datasets}
- **Total Data Processed:** {((s.total_file_size_bytes)/1024/1024/1024):.2f} GB
- **Avg Quality Score:** {f"{s.avg_quality_score:.4f}" if s.avg_quality_score else "N/A"}

### Monthly Performance
| Month | Attempts | Success % | Avg Quality |
|-------|----------|-----------|-------------|
{chr(10).join([f"| {m.month_key} | {m.total_ingestion_attempts} | {m.success_rate:.1f}% | {f'{m.avg_quality_score:.4f}' if m.avg_quality_score else 'N/A'} |" for m in s.monthly_summaries])}

### Schema & Data Changes
- **Versions with Schema Drift:** {len(s.schema_changes_history)}
- **Versions with Significant Data Changes:** {len(s.data_changes_history)}

_Generated at: {datetime.utcnow().isoformat()}Z_
"""