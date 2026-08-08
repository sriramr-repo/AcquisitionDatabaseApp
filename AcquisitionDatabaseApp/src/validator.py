from pathlib import Path
import zipfile

def validate_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path, 'r') as z:
            return z.testzip() is None
    except Exception:
        return False

def validate_extracted(path: Path) -> bool:
    # Case-insensitive check for CSV files
    files = [f for f in path.iterdir() if f.suffix.lower() == '.csv']
    return len(files) > 0

def validate_csv(path: Path) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(1024) != b''
    except Exception:
        return False