"""Structured operational alerts with a pluggable notifier boundary."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.operations import OperationsRepository


logger = logging.getLogger("scm.alerts")


class AlertNotifier:
    """Persist every alert and emit it to the configured local log."""

    def __init__(self, repository: OperationsRepository | None = None):
        self.repository = repository or OperationsRepository()

    def emit(self, event_type: str, message: str, *, severity: str = "ERROR",
             run_id: str | None = None, details: dict[str, Any] | None = None) -> int:
        alert_id = self.repository.record_alert(
            event_type, severity, message, run_id=run_id,
            details_json=json.dumps(details or {}, default=str),
        )
        logger.log(logging.ERROR if severity in {"ERROR", "CRITICAL"} else logging.WARNING,
                   "%s [%s] %s", event_type, severity, message)
        return alert_id

