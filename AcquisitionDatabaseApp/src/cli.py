import typer
from typing import Optional
from pipeline import run_pipeline
from metadata import list_datasets, get_current_dataset

app = typer.Typer()

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

if __name__ == "__main__":
    app()
