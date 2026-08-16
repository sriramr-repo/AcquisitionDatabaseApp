"""Reporting and Aggregation Layer for SCM RIA Acquisition Intelligence Platform."""

from src.reports.models import (
    ExecutionSummary,
    DatasetSummary,
    MonthlySummary,
    HistoricalSummary,
)
from src.reports.aggregator import (
    get_dataset_summary,
    get_daily_summary,
    get_monthly_summary,
    get_historical_summary,
)
from src.reports.exporters import ReportExporter

__all__ = [
    "ExecutionSummary",
    "DatasetSummary", 
    "MonthlySummary",
    "HistoricalSummary",
    "get_dataset_summary",
    "get_daily_summary",
    "get_monthly_summary",
    "get_historical_summary",
    "ReportExporter",
]
