import logging
import time
import json
import psutil
from functools import wraps
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Structured logging setup
LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter"""
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if hasattr(record, 'metrics'):
            log_obj["metrics"] = record.metrics
        return json.dumps(log_obj)

# Setup structured logger
logger = logging.getLogger("sec_pipeline")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(LOG_DIR / "pipeline_structured.log")
handler.setFormatter(StructuredFormatter())
logger.addHandler(handler)

# Also keep human-readable log
human_handler = logging.FileHandler(LOG_DIR / "pipeline.log")
human_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
logger.addHandler(human_handler)

def get_stats() -> Dict[str, float]:
    """Get current system resource utilization"""
    return {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent,
        "disk_free_gb": psutil.disk_usage('/').free / (1024**3)
    }

class ExecutionTimer:
    """Context manager for timing execution with metrics"""
    def __init__(self, operation: str, logger_instance=None):
        self.operation = operation
        self.logger = logger_instance or logger
        self.start_time = None
        self.end_time = None
        self.duration = None
        
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        self.duration = self.end_time - self.start_time
        self.logger.info(
            f"EXEC|{self.operation}|{self.duration:.4f}s|{'SUCCESS' if exc_type is None else 'FAILED'}",
            extra={"metrics": {
                "operation": self.operation,
                "duration_seconds": self.duration,
                "status": "success" if exc_type is None else "failed",
                "error": str(exc_val) if exc_val else None,
                **get_stats()
            }}
        )

def monitor(operation: str = None):
    """Decorator for monitoring function execution"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            with ExecutionTimer(op_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator

class HealthReport:
    """Generate health report for pipeline"""
    def __init__(self):
        self.checks = []
        
    def check_disk_space(self, threshold_pct=90) -> bool:
        disk = psutil.disk_usage('/')
        pct = disk.percent
        status = "PASS" if pct < threshold_pct else "FAIL"
        self.checks.append({
            "name": "disk_space",
            "status": status,
            "value": f"{pct}%",
            "threshold": f"<{threshold_pct}%"
        })
        return status == "PASS"
        
    def check_memory(self, threshold_pct=90) -> bool:
        mem = psutil.virtual_memory()
        pct = mem.percent
        status = "PASS" if pct < threshold_pct else "FAIL"
        self.checks.append({
            "name": "memory",
            "status": status,
            "value": f"{pct}%",
            "threshold": f"<{threshold_pct}%"
        })
        return status == "PASS"
        
    def check_database(self, db_path: str = "data/analytics.duckdb") -> bool:
        path = Path(db_path)
        status = "PASS" if path.exists() else "FAIL"
        self.checks.append({
            "name": "database",
            "status": status,
            "value": "exists" if path.exists() else "missing",
            "threshold": "file exists"
        })
        return status == "PASS"
        
    def check_recent_logs(self, max_age_hours=25) -> bool:
        log_path = LOG_DIR / "pipeline.log"
        if not log_path.exists():
            self.checks.append({"name": "recent_logs", "status": "FAIL", "value": "no_log_file", "threshold": f"<{max_age_hours}h"})
            return False
        age_hours = (time.time() - log_path.stat().st_mtime) / 3600
        status = "PASS" if age_hours < max_age_hours else "FAIL"
        self.checks.append({
            "name": "recent_logs",
            "status": status,
            "value": f"{age_hours:.1f}h ago",
            "threshold": f"<{max_age_hours}h"
        })
        return status == "PASS"
        
    def check_data_freshness(self, max_age_days=35) -> bool:
        """Check if latest dataset is recent enough"""
        from src.metadata import list_datasets
        datasets = list_datasets()
        if not datasets:
            self.checks.append({"name": "data_freshness", "status": "FAIL", "value": "no_datasets", "threshold": f"<{max_age_days}d"})
            return False
        try:
            latest_ts = datasets[0]['download_timestamp']
            age_days = (datetime.utcnow() - datetime.fromisoformat(latest_ts)).days
            status = "PASS" if age_days < max_age_days else "FAIL"
            self.checks.append({
                "name": "data_freshness",
                "status": status,
                "value": f"{age_days}d ago",
                "threshold": f"<{max_age_days}d"
            })
            return status == "PASS"
        except:
            self.checks.append({"name": "data_freshness", "status": "FAIL", "value": "parse_error", "threshold": f"<{max_age_days}d"})
            return False
            
    def run_all(self) -> Dict[str, Any]:
        self.check_disk_space()
        self.check_memory()
        self.check_database()
        self.check_recent_logs()
        self.check_data_freshness()
        
        all_pass = all(c["status"] == "PASS" for c in self.checks)
        return {
            "healthy": all_pass,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "checks": self.checks
        }

class ExecutionSummary:
    """Generate execution summary from logs"""
    def __init__(self, log_path: str = "data/logs/pipeline.log"):
        self.log_path = Path(log_path)
        
    def parse_logs(self):
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text().splitlines()
        parsed = []
        for line in lines:
            parts = line.split(' | ', 2)
            if len(parts) >= 3:
                parsed.append({"timestamp": parts[0], "level": parts[1], "message": parts[2]})
        return parsed
        
    def get_summary(self) -> Dict[str, Any]:
        logs = self.parse_logs()
        if not logs:
            return {"error": "No logs found"}
            
        exec_logs = [l for l in logs if l["message"].startswith("EXEC|")]
        success_logs = [l for l in exec_logs if "SUCCESS" in l["message"]]
        failed_logs = [l for l in exec_logs if "FAILED" in l["message"]]
        
        durations = []
        for l in exec_logs:
            try:
                dur = float(l["message"].split('|')[2].replace('s', ''))
                durations.append(dur)
            except:
                pass
                
        return {
            "total_executions": len(exec_logs),
            "successful": len(success_logs),
            "failed": len(failed_logs),
            "success_rate": len(success_logs) / len(exec_logs) * 100 if exec_logs else 0,
            "avg_duration_seconds": sum(durations) / len(durations) if durations else 0,
            "max_duration_seconds": max(durations) if durations else 0,
            "min_duration_seconds": min(durations) if durations else 0,
            "last_execution": logs[-1]["timestamp"] if logs else None
        }

class PipelineDashboard:
    """CLI-only operational dashboard"""
    def __init__(self):
        self.health = HealthReport()
        self.summary = ExecutionSummary()
        
    def render(self) -> str:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        
        console = Console()
        output = []
        
        # Health Report
        health = self.health.run_all()
        table = Table(title="Health Report", box=box.ROUNDED)
        table.add_column("Check", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Value", style="yellow")
        table.add_column("Threshold", style="dim")
        
        for check in health["checks"]:
            status_style = "green" if check["status"] == "PASS" else "red"
            table.add_row(
                check["name"],
                f"[{status_style}]{check['status']}[/{status_style}]",
                check["value"],
                check["threshold"]
            )
        console.print(table)
        
        # Execution Summary
        summary = self.summary.get_summary()
        if "error" not in summary:
            table2 = Table(title="Execution Summary", box=box.ROUNDED)
            table2.add_column("Metric", style="cyan")
            table2.add_column("Value", style="green")
            for k, v in summary.items():
                table2.add_row(k.replace("_", " ").title(), str(v))
            console.print(table2)
            
        # Resource Utilization
        stats = get_stats()
        table3 = Table(title="Resource Utilization", box=box.ROUNDED)
        table3.add_column("Resource", style="cyan")
        table3.add_column("Value", style="green")
        for k, v in stats.items():
            if isinstance(v, float):
                table3.add_row(k.replace("_", " ").title(), f"{v:.1f}")
            else:
                table3.add_row(k.replace("_", " ").title(), str(v))
        console.print(table3)
        
        return ""

def emit_warning(category: str, message: str, details: Dict = None):
    """Emit structured warning for operational issues"""
    warning = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "type": "WARNING",
        "category": category,
        "message": message,
        "details": details or {}
    }
    logger.warning(json.dumps(warning))
    
    # Also log human-readable
    logger.warning(f"WARN|{category}|{message}")

# Warning categories
def warn_row_drop(expected: int, actual: int, table: str):
    if actual < expected * 0.95:
        emit_warning("ROW_DROP", f"Unexpected row drop in {table}: {actual}/{expected} ({(actual/expected)*100:.1f}%)", 
                     {"table": table, "expected": expected, "actual": actual})

def warn_missing_table(table: str, dataset: str):
    emit_warning("MISSING_TABLE", f"Expected table {table} not found in {dataset}", {"table": table, "dataset": dataset})

def warn_schema_drift(missing: list, extra: list, table: str):
    if missing or extra:
        emit_warning("SCHEMA_DRIFT", f"Schema drift in {table}: {len(missing)} missing, {len(extra)} extra columns",
                     {"table": table, "missing": missing, "extra": extra})

def warn_download_failed(url: str, error: str):
    emit_warning("DOWNLOAD_FAILED", f"Failed to download {url}: {error}", {"url": url, "error": error})

def warn_storage_issue(path: str, issue: str):
    emit_warning("STORAGE_ISSUE", f"Storage issue at {path}: {issue}", {"path": path, "issue": issue})