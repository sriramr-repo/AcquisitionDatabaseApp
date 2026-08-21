import typer
from typing import Optional
from src.pipeline import run_pipeline
from src.metadata import list_datasets, get_current_dataset

app = typer.Typer()

@app.command()
def dashboard():
    """Launch operational dashboard (CLI only)."""
    import pandas as pd
    from pathlib import Path
    from rich.console import Console
    from rich.table import Table
    from rich import box
    
    console = Console()
    table = Table(title="Pipeline Dashboard", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    # Parse logs
    from src.config import settings
    log_path = settings.LOG_DIR / "pipeline.log"
    if log_path.exists():
        logs = [l.strip().split(' | ') for l in log_path.read_text().splitlines() if ' | ' in l]
        df = pd.DataFrame(logs, columns=['ts', 'lvl', 'msg'])
        
        # Extract metrics from log messages
        exec_logs = df[df['msg'].str.startswith('EXEC|', na=False)]
        if not exec_logs.empty:
            avg_time = exec_logs['msg'].str.extract(r'(\d+\.\d+)s')[0].astype(float).mean()
            table.add_row("Last Execution", str(len(exec_logs)))
            table.add_row("Avg Duration", f"{avg_time:.2f}s")
            table.add_row("Success Rate", f"{len(exec_logs[exec_logs['msg'].str.contains('SUCCESS')]) / len(exec_logs) * 100:.1f}%")
        
        # Resource stats
        try:
            from src.telemetry import get_stats
            stats = get_stats()
            table.add_row("CPU Usage", f"{stats['cpu']}%")
            table.add_row("Memory Usage", f"{stats['mem']}%")
        except:
            pass
        
        # Dataset count
        from src.metadata import list_datasets
        datasets = list_datasets()
        table.add_row("Datasets Loaded", str(len(datasets)))
        if datasets:
            table.add_row("Latest Dataset", datasets[0]['dataset_version'])
    else:
        table.add_row("Status", "No logs found")
    
    console.print(table)

@app.command()
def download_data():
    """Discover and download latest SEC dataset."""
    typer.echo("Discovering latest SEC dataset...")
    meta = run_pipeline(force=False)
    if meta['status'] == 'success':
        typer.echo(f"✅ Dataset {meta['dataset_version']} ingested successfully.")
    elif meta['status'] == 'skipped':
        typer.echo(f"⚠️ Dataset {meta['dataset_version']} already exists.")

@app.command()
def force_refresh():
    """Force re-download of latest dataset."""
    typer.echo("Forcing re-download...")
    meta = run_pipeline(force=True)
    if meta['status'] == 'success':
        typer.echo(f"✅ Dataset {meta['dataset_version']} refreshed.")

@app.command("list-datasets")
def list_datasets_command():
    """List downloaded SEC datasets."""
    datasets = list_datasets()
    for d in datasets:
        typer.echo(f"{d['dataset_version']} | {d['status']} | {d['download_timestamp']}")

@app.command()
def show_current():
    """Show currently active dataset."""
    current = get_current_dataset()
    if current:
        typer.echo(f"Current dataset: {current['dataset_version']}")
    else:
        typer.echo("No dataset ingested yet.")

@app.command()
def health_check():
    """Run health checks."""
    import psutil
    from pathlib import Path
    from datetime import datetime
    
    checks = []
    
    # Disk space
    disk = psutil.disk_usage('/')
    checks.append(f"Disk: {disk.percent}% used")
    
    # Memory
    mem = psutil.virtual_memory()
    checks.append(f"Memory: {mem.percent}% used")
    
    # CPU
    cpu = psutil.cpu_percent(interval=1)
    checks.append(f"CPU: {cpu}%")
    
    # Database exists
    from src.config import settings
    db_path = settings.DUCKDB_FILE
    checks.append(f"Database: {'✓' if db_path.exists() else '✗'}")
    
    # Latest log timestamp
    log_path = settings.LOG_DIR / "pipeline.log"
    if log_path.exists():
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
        checks.append(f"Last Log: {mtime.strftime('%Y-%m-%d %H:%M')}")
    
    typer.echo("\n".join(checks))


@app.command("production-status")
def production_status_command():
    """Show the active environment, current dataset, and recent operational runs."""
    from src.production import production_status
    import json
    typer.echo(json.dumps(production_status(), indent=2, default=str))


@app.command("production-health-check")
def production_health_check_command():
    """Run production invariant and path health checks."""
    from src.production import production_health_check
    import json
    result = production_health_check()
    typer.echo(json.dumps(result, indent=2, default=str))
    if not result.get("healthy"):
        raise typer.Exit(code=1)


@app.command("production-refresh")
def production_refresh_command(force: bool = typer.Option(False, "--force")):
    """Run the controlled monthly production refresh."""
    from src.production import production_refresh
    import json
    try:
        result = production_refresh(trigger_type="cli", force=force)
    except Exception as exc:
        typer.echo(f"Production refresh failed: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(result, indent=2, default=str))


@app.command("iapd-refresh")
def iapd_refresh_command(
    database_url: str = typer.Option(..., "--database-url"),
    date: Optional[str] = typer.Option(None, "--date"),
    force: bool = typer.Option(False, "--force"),
):
    """Run the monthly IAPD representative refresh."""
    from datetime import date as date_type
    from src.iapd import run_iapd_monthly
    import json
    run_date = date_type.fromisoformat(date) if date else None
    result = run_iapd_monthly(database_url=database_url, run_date=run_date, force=force)
    typer.echo(json.dumps(result, indent=2, default=str))


@app.command("iapd-import")
def iapd_import_command(
    database_url: str = typer.Option(..., "--database-url"),
    date: str = typer.Option(..., "--date"),
    source_url: str = typer.Option(..., "--source-url"),
    xml_path: str = typer.Option(..., "--xml-path"),
    source_zip: Optional[str] = typer.Option(None, "--source-zip"),
    priority: Optional[str] = typer.Option(None, "--priority", help="Comma-separated dashboard priorities to publish, for example PRIORITY_A"),
):
    """Import a manually downloaded IAPD XML snapshot."""
    from datetime import date as date_type
    from pathlib import Path
    from src.iapd import import_iapd_from_paths
    import json
    result = import_iapd_from_paths(
        database_url=database_url,
        snapshot_date=date_type.fromisoformat(date),
        source_url=source_url,
        source_zip=Path(source_zip) if source_zip else None,
        xml_path=Path(xml_path),
        priority_categories=[item.strip() for item in priority.split(",") if item.strip()] if priority else None,
    )
    typer.echo(json.dumps(result, indent=2, default=str))


@app.command("iapd-live-crawl")
def iapd_live_crawl_command(
    database_url: str = typer.Option(..., "--database-url"),
    crd: str = typer.Option(..., "--crd"),
    url: Optional[str] = typer.Option(None, "--url"),
):
    """Capture one public IAPD representative page through Firecrawl."""
    from src.iapd_live import capture_iapd_live_page
    import json
    typer.echo(json.dumps(capture_iapd_live_page(individual_crd=crd, database_url=database_url, url=url), indent=2, default=str))


@app.command("iapd-reconcile")
def iapd_reconcile_command(
    database_url: str = typer.Option(..., "--database-url"),
    crd: Optional[str] = typer.Option(None, "--crd"),
    all_records: bool = typer.Option(False, "--all", help="Rebuild all derived IAPD effective records."),
    limit: Optional[int] = typer.Option(None, "--limit", min=1),
):
    """Rebuild the derived, provenance-preserving IAPD effective record."""
    from src.iapd_live import reconcile_iapd_individual, rebuild_iapd_reconciliations
    import json
    if all_records:
        result = rebuild_iapd_reconciliations(database_url=database_url, limit=limit)
    elif crd:
        result = reconcile_iapd_individual(individual_crd=crd, database_url=database_url)
    else:
        raise typer.BadParameter("provide --crd or --all")
    typer.echo(json.dumps(result, indent=2, default=str))


@app.command("iapd-audit")
def iapd_audit_command(database_url: str = typer.Option(..., "--database-url")):
    """List recent IAPD parse and reconciliation issues without changing data."""
    import json
    import psycopg
    with psycopg.connect(database_url) as connection:
        rows = connection.execute("SELECT snapshot_id,individual_crd,stage,severity,issue_code,message,created_at FROM iapd_import_issues ORDER BY created_at DESC LIMIT 100").fetchall()
    typer.echo(json.dumps([list(row) for row in rows], indent=2, default=str))


@app.command("list-runs")
def list_runs_command(limit: int = typer.Option(20, min=1, max=500)):
    """List persisted production runs."""
    from src.operations import OperationsRepository
    import json
    typer.echo(json.dumps(OperationsRepository().list_runs(limit), indent=2, default=str))


@app.command("show-run")
def show_run_command(run_id: str):
    """Show one run and all recorded stages."""
    from src.operations import OperationsRepository
    import json
    repository = OperationsRepository()
    run = repository.get_run(run_id)
    if run is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(code=1)
    run["stages"] = repository.list_stages(run_id)
    typer.echo(json.dumps(run, indent=2, default=str))


@app.command("backup")
def backup_command(dataset_version: Optional[str] = typer.Option(None, "--dataset-version")):
    """Create a verified local production backup."""
    from src.backup import create_backup
    from src.metadata import get_current_dataset
    import json
    current = get_current_dataset()
    version = dataset_version or (current or {}).get("dataset_version")
    typer.echo(json.dumps(create_backup(dataset_version=version), indent=2, default=str))


@app.command("list-backups")
def list_backups_command():
    """List registered backups."""
    from src.backup import list_backups
    import json
    typer.echo(json.dumps(list_backups(), indent=2, default=str))


@app.command("verify-backup")
def verify_backup_command(path: str):
    """Verify a backup manifest and all recorded file hashes."""
    from src.backup import verify_backup
    import json
    result = verify_backup(path)
    typer.echo(json.dumps(result, indent=2, default=str))
    if not result.get("valid"):
        raise typer.Exit(code=1)


@app.command("research-refresh-queue")
def research_refresh_queue_command(dataset_version: str, previous_version: Optional[str] = None):
    """Generate the event-driven research refresh queue."""
    from src.research_queue import build_research_refresh_queue, save_research_refresh_queue
    import json
    queue = build_research_refresh_queue(dataset_version, previous_version=previous_version)
    path = save_research_refresh_queue(queue, dataset_version)
    typer.echo(json.dumps({"path": str(path), "count": len(queue)}, indent=2))


@app.command("initialize-source-tasks")
def initialize_source_tasks_command(dataset_version: str, all_firms: bool = False):
    """Create idempotent metadata-first public-source tasks."""
    from src.research import ResearchRepository
    import json
    categories = ("EXCLUDED", "PRIORITY_A", "PRIORITY_B", "PRIORITY_C") if all_firms else ("PRIORITY_A", "PRIORITY_B")
    result = ResearchRepository().initialize_source_tasks(
        dataset_version, priority_categories=categories
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("list-source-tasks")
def list_source_tasks_command(
    dataset_version: Optional[str] = None,
    source_type: Optional[str] = None,
    status: Optional[str] = None,
    firm_id: Optional[str] = None,
):
    """List public-source task metadata and review status."""
    from src.research import ResearchRepository
    import json
    result = ResearchRepository().list_source_tasks(
        dataset_version=dataset_version, source_type=source_type, status=status, firm_id=firm_id
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("source-coverage")
def source_coverage_command(dataset_version: str):
    """Report source-task coverage by type and status."""
    from src.research import ResearchRepository
    import json
    typer.echo(json.dumps(ResearchRepository().source_coverage(dataset_version), indent=2))


@app.command("list-observations")
def list_observations_command(firm_id: str, dataset_version: str, review_status: Optional[str] = None):
    """List proposed or reviewed external observations for one firm."""
    from src.research import ResearchRepository
    import json
    typer.echo(json.dumps(ResearchRepository().list_observations(firm_id, dataset_version, review_status), indent=2))


@app.command("monthly-report")
def monthly_report_command(dataset_version: Optional[str] = None):
    """Generate the operational and acquisition monthly JSON report."""
    from src.production import generate_monthly_report
    typer.echo(str(generate_monthly_report(dataset_version)))

# Expose a Click command object so both the installed entry point and the
# standard click.testing runner behave consistently across Click versions.
app = typer.main.get_command(app)

if __name__ == "__main__":
    app()
