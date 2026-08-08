import zipfile
import shutil
from pathlib import Path

def extract_zip(zip_path: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    extracted_files = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        for member in z.infolist():
            # Skip directories
            if member.is_dir():
                continue
            
            # Extract to a temporary path, then move and rename
            # This handles potential issues with long filenames and ensures direct placement
            temp_path = dest / Path(member.filename).name
            with z.open(member) as source, open(temp_path, 'wb') as target:
                shutil.copyfileobj(source, target)
            extracted_files.append(temp_path)

    # Clean up any empty directories created by extractall if it was used
    # (though with z.open() direct write, this might be less necessary)
    for item in dest.iterdir():
        if item.is_dir() and not list(item.iterdir()): # Check if directory is empty
            item.rmdir()
            
    return len(extracted_files)
