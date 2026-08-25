import shutil
import sys
from pathlib import Path
from src.config import settings as package_settings

def archive_dataset(dataset_name: str):
    # Support the legacy top-level import path used by older operators/tests,
    # while keeping production paths resolved at call time.
    settings = package_settings if __name__.startswith("src.") else getattr(sys.modules.get("config"), "settings", package_settings)
    bronze = settings.RAW_DIR / dataset_name
    zip_path = settings.RAW_DIR / f"{dataset_name}.zip"
    if bronze.exists():
        destination = settings.ARCHIVE_DIR / dataset_name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(bronze), str(destination))
    if zip_path.exists():
        destination = settings.ARCHIVE_DIR / f"{dataset_name}.zip"
        if destination.exists():
            destination.unlink()
        shutil.move(str(zip_path), str(destination))
