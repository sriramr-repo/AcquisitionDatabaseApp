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
    log_path = Path("data/logs/pipeline.log")
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

@app.command()
def list_datasets():
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
    db_path = Path("data/analytics.duckdb")
    checks.append(f"Database: {'✓' if db_path.exists() else '✗'}")
    
    # Latest log timestamp
    log_path = Path("data/logs/pipeline.log")
    if log_path.exists():
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
        checks.append(f"Last Log: {mtime.strftime('%Y-%m-%d %H:%M')}")
    
    typer.echo("\n".join(checks))

if __name__ == "__main__":
    app()
