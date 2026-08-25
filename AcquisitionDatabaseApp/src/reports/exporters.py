"""JSON, Markdown, and CSV exporters for structured reporting models."""

import csv
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.config import settings
from src.reports.models import HistoricalSummary, MonthlySummary


def _serialize(value: Any) -> Any:
    """Convert reporting-model values into JSON-compatible values."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _serialize(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


class ReportExporter:
    """Write reporting models as JSON, Markdown, and useful CSV tables."""

    _DATASET_CSV_HEADERS = (
        "dataset_version",
        "dataset_name",
        "ingestion_date",
        "status",
        "file_name",
        "file_size_bytes",
        "quality_score",
        "bronze_rows",
        "silver_rows",
        "gold_rows",
        "schema_changes_count",
        "records_added",
        "records_modified",
        "records_deleted",
    )

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir is not None else settings.EXPORTS_DIR / "reports"
        if self.base_dir.exists() and not self.base_dir.is_dir():
            raise OSError(f"Base dir path exists and is not a directory: {self.base_dir}")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(self, report_type: str, period: str, data: Any, filename: str) -> Path:
        report_dir = self.base_dir / report_type / period
        report_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "report_type": report_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period": period,
            "data": _serialize(data),
        }
        output_path = report_dir / filename
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return output_path

    def export_daily_report(
        self,
        summary: MonthlySummary,
        report_date: Optional[str] = None,
    ) -> Dict[str, Path]:
        """Export one daily summary, including an empty daily period."""
        latest_date = summary.latest_ingestion_date
        if isinstance(latest_date, (datetime, date)):
            derived_period = latest_date.isoformat()[:10]
        elif latest_date:
            derived_period = latest_date[:10]
        else:
            derived_period = None
        period = report_date or derived_period
        if period is None:
            raise ValueError("report_date is required when the daily summary has no ingestion date")

        json_path = self._write_json("daily", period, summary, "daily_report.json")
        markdown_path = self._write_markdown(
            "daily",
            period,
            self._render_daily_markdown(summary, period),
            "daily_report.md",
        )
        csv_path = self._write_csv(
            "daily",
            period,
            self._dataset_rows(summary),
            "daily_report.csv",
        )
        return {"json": json_path, "markdown": markdown_path, "csv": csv_path}

    def export_monthly_report(self, summary: MonthlySummary) -> Dict[str, Path]:
        """Export one monthly summary."""
        json_path = self._write_json(
            "monthly",
            summary.month_key,
            summary,
            "monthly_report.json",
        )
        markdown_path = self._write_markdown(
            "monthly",
            summary.month_key,
            self._render_monthly_markdown(summary),
            "monthly_report.md",
        )
        csv_path = self._write_csv(
            "monthly",
            summary.month_key,
            self._dataset_rows(summary),
            "monthly_report.csv",
        )
        return {"json": json_path, "markdown": markdown_path, "csv": csv_path}

    def export_historical_report(self, summary: HistoricalSummary) -> Dict[str, Path]:
        """Export one historical summary across its requested date range."""
        period = f"{summary.start_date or 'start'}_to_{summary.end_date or 'end'}"
        json_path = self._write_json(
            "historical",
            period,
            summary,
            "historical_report.json",
        )
        markdown_path = self._write_markdown(
            "historical",
            period,
            self._render_historical_markdown(summary),
            "historical_report.md",
        )
        results = {
            "json": json_path,
            "markdown": markdown_path,
            "dataset_csv": self._write_csv(
                "historical",
                period,
                [self._dataset_row(dataset) for dataset in summary.dataset_summaries],
                "dataset_history.csv",
            ),
        }
        if summary.monthly_summaries:
            results["monthly_csv"] = self._write_csv(
                "historical",
                period,
                [self._monthly_row(monthly) for monthly in summary.monthly_summaries],
                "monthly_summary.csv",
                headers=(
                    "month_key",
                    "total_ingestion_attempts",
                    "successful_ingestions",
                    "failed_ingestions",
                    "skipped_ingestions",
                    "success_rate",
                    "datasets_processed",
                    "avg_quality_score",
                    "total_warnings",
                    "total_errors",
                ),
            )
        if summary.schema_changes_history:
            results["schema_changes_csv"] = self._write_csv(
                "historical",
                period,
                [self._schema_change_row(change) for change in summary.schema_changes_history],
                "schema_changes.csv",
                headers=("dataset_version", "schema_changes_count", "missing_columns", "extra_columns"),
            )
        if summary.data_changes_history:
            results["data_changes_csv"] = self._write_csv(
                "historical",
                period,
                [self._data_change_row(change) for change in summary.data_changes_history],
                "data_changes.csv",
                headers=("dataset_version", "records_added", "records_modified", "records_deleted"),
            )
        return results

    def _write_markdown(
        self,
        report_type: str,
        period: str,
        content: str,
        filename: str,
    ) -> Path:
        report_dir = self.base_dir / report_type / period
        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / filename
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def _write_csv(
        self,
        report_type: str,
        period: str,
        rows: Iterable[Dict[str, Any]],
        filename: str,
        headers: Optional[Iterable[str]] = None,
    ) -> Path:
        """Write a deterministic CSV table, leaving unavailable fields empty."""
        report_dir = self.base_dir / report_type / period
        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / filename
        fieldnames = tuple(headers) if headers is not None else self._DATASET_CSV_HEADERS
        with output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: self._csv_value(row.get(field)) for field in fieldnames})
        return output_path

    @staticmethod
    def _csv_value(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bool):
            return str(value).lower()
        return value

    @classmethod
    def _dataset_rows(cls, summary: MonthlySummary) -> List[Dict[str, Any]]:
        if summary.executions:
            return [cls._dataset_row(execution) for execution in summary.executions]
        return [
            cls._dataset_row(
                None,
                dataset_version=dataset_version,
                ingestion_date=summary.latest_ingestion_date,
            )
            for dataset_version in summary.datasets_processed
        ]

    @classmethod
    def _dataset_row(
        cls,
        source: Any = None,
        *,
        dataset_version: Optional[str] = None,
        ingestion_date: Any = None,
    ) -> Dict[str, Any]:
        schema_changes = getattr(source, "schema_changes", None)
        data_changes = getattr(source, "data_changes", None)
        return {
            "dataset_version": dataset_version if source is None else getattr(source, "dataset_version", None),
            "dataset_name": getattr(source, "dataset_name", None),
            "ingestion_date": ingestion_date if source is None else getattr(source, "ingestion_date", None) or getattr(source, "download_timestamp", None),
            "status": getattr(source, "status", None),
            "file_name": getattr(source, "file_name", None),
            "file_size_bytes": getattr(source, "file_size", None),
            "quality_score": getattr(source, "quality_score", None),
            "bronze_rows": getattr(source, "bronze_rows", None),
            "silver_rows": getattr(source, "silver_rows", None),
            "gold_rows": getattr(source, "gold_rows", None),
            "schema_changes_count": cls._schema_change_count(schema_changes),
            "records_added": cls._change_metric(data_changes, "added_count", "records_added", "added"),
            "records_modified": cls._change_metric(data_changes, "modified_count", "records_modified", "modified"),
            "records_deleted": cls._change_metric(data_changes, "deleted_count", "records_deleted", "deleted"),
        }

    @staticmethod
    def _schema_change_count(changes: Any) -> Optional[int]:
        if not isinstance(changes, dict):
            return None
        missing = ReportExporter._change_metric(changes, "missing_columns", "missing")
        extra = ReportExporter._change_metric(changes, "extra_columns", "extra")
        if missing is None and extra is None:
            return None
        return (missing or 0) + (extra or 0)

    @staticmethod
    def _change_metric(changes: Any, *keys: str) -> Optional[int]:
        if not isinstance(changes, dict):
            return None
        for key in keys:
            value = changes.get(key)
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, (list, tuple, set)):
                return len(value)
        nested = changes.get("summary")
        if isinstance(nested, dict) and nested is not changes:
            return ReportExporter._change_metric(nested, *keys)
        return None

    @staticmethod
    def _monthly_row(summary: MonthlySummary) -> Dict[str, Any]:
        return {
            "month_key": summary.month_key,
            "total_ingestion_attempts": summary.total_ingestion_attempts,
            "successful_ingestions": summary.successful_ingestions,
            "failed_ingestions": summary.failed_ingestions,
            "skipped_ingestions": summary.skipped_ingestions,
            "success_rate": summary.success_rate,
            "datasets_processed": len(summary.datasets_processed),
            "avg_quality_score": summary.avg_quality_score,
            "total_warnings": summary.total_warnings,
            "total_errors": summary.total_errors,
        }

    @classmethod
    def _schema_change_row(cls, change: Dict[str, Any]) -> Dict[str, Any]:
        details = change.get("changes")
        return {
            "dataset_version": change.get("dataset_version"),
            "schema_changes_count": cls._schema_change_count(details),
            "missing_columns": cls._change_metric(details, "missing_columns", "missing"),
            "extra_columns": cls._change_metric(details, "extra_columns", "extra"),
        }

    @classmethod
    def _data_change_row(cls, change: Dict[str, Any]) -> Dict[str, Any]:
        details = change.get("changes")
        return {
            "dataset_version": change.get("dataset_version"),
            "records_added": cls._change_metric(details, "added_count", "records_added", "added"),
            "records_modified": cls._change_metric(details, "modified_count", "records_modified", "modified"),
            "records_deleted": cls._change_metric(details, "deleted_count", "records_deleted", "deleted"),
        }

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format optional values without confusing zero with unavailable."""
        if value is None:
            return "Unavailable"
        return str(value)

    @staticmethod
    def _format_percentage(value: Optional[float]) -> str:
        if value is None:
            return "Unavailable"
        return f"{value:.1f}%"

    @staticmethod
    def _format_file_size(size_bytes: Optional[int]) -> str:
        if size_bytes is None:
            return "Unavailable"
        if size_bytes == 0:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        size = float(size_bytes)
        unit = units[0]
        for candidate in units:
            unit = candidate
            if size < 1024 or candidate == units[-1]:
                break
            size /= 1024
        if unit == "B":
            return f"{int(size)} B"
        return f"{size:.1f} {unit}"

    @staticmethod
    def _markdown_cell(value: Any) -> str:
        text = ReportExporter._format_value(value).replace("\n", " ").replace("\r", " ")
        for character in ("\\", "|", "`", "*", "_", "[", "]", "<", ">"):
            text = text.replace(character, f"\\{character}")
        return text

    @staticmethod
    def _markdown_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
        header_cells = [ReportExporter._markdown_cell(header) for header in headers]
        lines = [
            "| " + " | ".join(header_cells) + " |",
            "| " + " | ".join("---" for _ in header_cells) + " |",
        ]
        for row in rows:
            cells = [ReportExporter._markdown_cell(value) for value in row]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def _render_daily_markdown(self, summary: MonthlySummary, period: str) -> str:
        rows = []
        for execution in summary.executions:
            rows.append(
                (
                    execution.dataset_version,
                    execution.download_timestamp,
                    execution.status,
                    self._format_file_size(execution.file_size),
                    self._format_value(execution.quality_score),
                )
            )
        if not rows:
            rows = [
                (
                    dataset,
                    summary.latest_ingestion_date,
                    "Unavailable",
                    "Unavailable",
                    "Unavailable",
                )
                for dataset in summary.datasets_processed
            ]

        dataset_activity = (
            self._markdown_table(
                ("Dataset", "Date", "Status", "File Size", "Quality Score"),
                rows,
            )
            if rows
            else "No datasets found for this reporting period."
        )
        return "\n".join(
            [
                "# SCM RIA Acquisition Intelligence",
                f"## Daily Pipeline Report — {period}",
                "",
                "### Executive Summary",
                f"- Ingestion attempts: {summary.total_ingestion_attempts}",
                f"- Successful ingestions: {summary.successful_ingestions}",
                f"- Failed ingestions: {summary.failed_ingestions}",
                f"- Success rate: {self._format_percentage(summary.success_rate)}",
                f"- Datasets processed: {len(summary.datasets_processed)}",
                f"- Latest dataset: {self._format_value(summary.latest_dataset)}",
                "",
                "### Data Quality",
                f"- Average quality score: {self._format_value(summary.avg_quality_score)}",
                f"- Warnings: {summary.total_warnings}",
                f"- Errors: {summary.total_errors}",
                "",
                "### Dataset Activity",
                dataset_activity,
                "",
                "### Changes",
                "Schema and data change details: Unavailable for daily summaries.",
                "",
                "### Limitations",
                "- Execution-level details are unavailable when execution summaries were not provided.",
                "- Schema and data change metrics are not part of the daily reporting model.",
                "",
            ]
        )

    def _render_monthly_markdown(self, summary: MonthlySummary) -> str:
        rows = [
            (
                execution.dataset_version,
                execution.download_timestamp,
                execution.status,
                self._format_file_size(execution.file_size),
                self._format_value(execution.quality_score),
            )
            for execution in summary.executions
        ]
        if not rows:
            rows = [
                (
                    dataset,
                    summary.latest_ingestion_date,
                    "Unavailable",
                    "Unavailable",
                    "Unavailable",
                )
                for dataset in summary.datasets_processed
            ]
        dataset_activity = (
            self._markdown_table(
                ("Dataset", "Ingestion Date", "Status", "File Size", "Quality Score"),
                rows,
            )
            if rows
            else "No datasets found for this reporting period."
        )
        operational_metrics = [
            f"- Total bronze rows: {summary.total_bronze_rows}",
            f"- Total silver rows: {summary.total_silver_rows}",
            f"- Total gold rows: {summary.total_gold_rows}",
            f"- Average execution duration: {self._format_value(summary.avg_execution_duration)}",
            f"- Total execution time: {self._format_value(summary.total_execution_time)}",
            f"- Warnings: {summary.total_warnings}",
            f"- Errors: {summary.total_errors}",
        ]
        quality_scores = (
            ", ".join(self._format_value(score) for score in summary.quality_scores)
            if summary.quality_scores
            else "Unavailable"
        )
        return "\n".join(
            [
                "# SCM RIA Acquisition Intelligence",
                f"## Monthly Pipeline Report — {summary.month_key}",
                "",
                "### Executive Summary",
                f"- Total ingestion attempts: {summary.total_ingestion_attempts}",
                f"- Successful ingestions: {summary.successful_ingestions}",
                f"- Failed ingestions: {summary.failed_ingestions}",
                f"- Skipped ingestions: {summary.skipped_ingestions}",
                f"- Success rate: {self._format_percentage(summary.success_rate)}",
                f"- Datasets processed: {len(summary.datasets_processed)}",
                f"- Latest dataset: {self._format_value(summary.latest_dataset)}",
                "",
                "### Data Quality",
                f"- Average quality score: {self._format_value(summary.avg_quality_score)}",
                f"- Individual quality scores: {quality_scores}",
                f"- Warnings: {summary.total_warnings}",
                f"- Errors: {summary.total_errors}",
                "",
                "### Dataset Activity",
                dataset_activity,
                "",
                "### Schema & Data Changes",
                "Schema changes: Unavailable for monthly summaries.",
                "Added/modified/deleted records: Unavailable for monthly summaries.",
                "",
                "### Operational Metrics",
                *operational_metrics,
                "",
                "### Limitations",
                "- Schema and data change metrics are not currently persisted in the monthly reporting model.",
                "",
            ]
        )

    def _render_historical_markdown(self, summary: HistoricalSummary) -> str:
        period = f"{summary.start_date or 'start'} → {summary.end_date or 'end'}"
        dataset_rows = [
            (
                dataset.dataset_version,
                dataset.ingestion_date,
                dataset.status,
                self._format_file_size(dataset.file_size),
                self._format_value(dataset.quality_score),
            )
            for dataset in summary.dataset_summaries
        ]
        dataset_history = (
            self._markdown_table(
                ("Dataset", "Ingestion Date", "Status", "File Size", "Quality Score"),
                dataset_rows,
            )
            if dataset_rows
            else "No datasets found for this reporting period."
        )
        monthly_rows = [
            (
                monthly.month_key,
                monthly.total_ingestion_attempts,
                self._format_percentage(monthly.success_rate),
                self._format_value(monthly.avg_quality_score),
            )
            for monthly in summary.monthly_summaries
        ]
        monthly_breakdown = (
            self._markdown_table(
                ("Month", "Attempts", "Success Rate", "Average Quality Score"),
                monthly_rows,
            )
            if monthly_rows
            else "No monthly data found for this reporting period."
        )
        schema_history = self._format_change_history(
            summary.schema_changes_history,
            "No schema changes recorded for this reporting period.",
        )
        data_history = self._format_change_history(
            summary.data_changes_history,
            "No data changes recorded for this reporting period.",
        )
        return "\n".join(
            [
                "# SCM RIA Acquisition Intelligence",
                "## Historical Pipeline Report",
                "",
                f"**Period:** {period}",
                "",
                "### Executive Summary",
                f"- Total datasets: {summary.total_datasets}",
                f"- Successful datasets: {summary.successful_datasets}",
                f"- Failed datasets: {summary.failed_datasets}",
                f"- Total file size: {self._format_file_size(summary.total_file_size_bytes)}",
                f"- Average file size: {self._format_file_size(summary.avg_file_size_bytes)}",
                f"- Average quality score: {self._format_value(summary.avg_quality_score)}",
                "",
                "### Dataset History",
                dataset_history,
                "",
                "### Monthly Summary",
                monthly_breakdown,
                "",
                "### Schema Change History",
                schema_history,
                "",
                "### Data Change History",
                data_history,
                "",
                "### Limitations",
                "- Execution durations and resource metrics are unavailable when they were not persisted.",
                "",
            ]
        )

    @staticmethod
    def _format_change_history(changes: List[Dict[str, Any]], empty_message: str) -> str:
        if not changes:
            return empty_message
        rows = []
        for change in changes:
            rows.append((change.get("dataset_version"), json.dumps(change.get("changes"), sort_keys=True)))
        return ReportExporter._markdown_table(("Dataset", "Changes"), rows)
