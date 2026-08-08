import shutil
from pathlib import Path
from src.config import settings
from src.storage import StorageManager

# Initialize StorageManager
storage = StorageManager()

def archive_dataset(dataset_name: str):
    storage.archive_dataset(dataset_name)
