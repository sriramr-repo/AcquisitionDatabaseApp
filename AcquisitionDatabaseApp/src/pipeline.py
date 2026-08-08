import logging
import time
from datetime import datetime
from pathlib import Path

from src.download import get_latest_url, download_zip
from src.extract import extract_zip
from src.validator import validate_zip, validate_extracted, validate_csv
from src.loader import load_to_dataframes, save_to_db
from src.metadata import init_metadata, log_ingestion, dataset_exists
from src.archive import archive_dataset
from src.storage import StorageManager, PathResolver
from src.config import settings

# Initialize storage manager
storage = StorageManager()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_DIR / 'pipeline.log')
    ]
)
logger = logging.getLogger(__name__)

def run_pipeline(force: bool = False) -> dict:
    init_metadata()
    start_time = time.time()
    meta = {
        'dataset_version': 'unknown',
        'dataset_name': 'unknown',
        'source_url': 'unknown',
        'download_timestamp': datetime.utcnow().isoformat(),
        'file_name': 'unknown',
        'file_size': 0,
        'sha256_checksum': 'unknown',
        'tables_loaded': '',
        'rows_loaded': 0,
        'execution_time': 0.0,
        'status': 'failed',
        'notes': ''
    }

    try:
        logger.info("Starting pipeline execution")
        
        latest_url = get_latest_url()
        dataset_name = Path(latest_url).stem
        meta['dataset_version'] = dataset_name
        meta['dataset_name'] = dataset_name
        meta['source_url'] = latest_url
        logger.info(f"Discovered dataset: {dataset_name}")
        
        if dataset_exists(dataset_name) and not force:
            logger.info(f"Dataset {dataset_name} already exists and force refresh not requested, skipping.")
            meta['status'] = 'skipped'
            meta['notes'] = 'Dataset already exists'
            return meta

        # Archive any existing dataset (extracted dir + zip) before processing new one
        archive_dataset(dataset_name)

        # Use PathResolver for bronze layer paths
        dataset_path = PathResolver.bronze_raw(dataset_name)
        zip_path = PathResolver.bronze_raw_zip(dataset_name)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading from {latest_url}")
        checksum = download_zip(latest_url, zip_path)
        meta['file_name'] = zip_path.name
        meta['file_size'] = zip_path.stat().st_size
        meta['sha256_checksum'] = checksum
        logger.info(f"Downloaded {zip_path.name} ({zip_path.stat().st_size} bytes)")
        
        if not validate_zip(zip_path):
            raise ValueError("Downloaded ZIP is corrupt or invalid.")
        logger.info("ZIP validation passed.")

        file_count = extract_zip(zip_path, dataset_path)
        logger.info(f"Extracted {file_count} files to {dataset_path}.")
        
        if not validate_extracted(dataset_path):
            raise ValueError("No CSV files found after extraction.")
        
        for csv_file in dataset_path.glob('*.csv'):
            if not validate_csv(csv_file):
                raise ValueError(f"Corrupt or empty CSV file detected: {csv_file.name}")
        logger.info("Extracted CSV validation passed.")

        dataframes = load_to_dataframes(dataset_path)
        tables, rows = save_to_db(dataframes, dataset_name)
        meta['tables_loaded'] = ','.join(tables)
        meta['rows_loaded'] = rows
        logger.info(f"Loaded {rows} rows across {len(tables)} tables into DuckDB.")

        # Silver layer: normalize raw data to canonical entities
        try:
            from src.normalizer import Normalizer
            from src.loader import write_silver

            normalizer = Normalizer(dataset_version=dataset_name)

            # Find the firm roster dataframe (main source for silver)
            roster_df = next((df for name, df in dataframes.items()
                            if 'FIRM_ROSTER' in name.upper() or 'IA_SEC' in name.upper()), None)

            if roster_df is not None:
                normalized = normalizer.normalize_batch(roster_df)
                silver_tables, silver_rows = write_silver(normalized, dataset_name)
                logger.info(f"Silver layer: wrote {silver_rows} rows across {len(silver_tables)} tables")
            else:
                logger.warning("No firm roster DataFrame found for silver normalization")
        except Exception as e:
            logger.warning(f"Silver normalization failed (non-critical): {e}", exc_info=True)

        # Data quality validation (Step 7)
        try:
            from src.quality import run_quality_validation
            quality_report = run_quality_validation(dataset_name)
            if quality_report['summary']['failed'] > 0:
                logger.warning(f"{quality_report['summary']['failed']} quality checks failed")
            else:
                logger.info(f"All {quality_report['summary']['passed']} quality checks passed")
        except Exception as e:
            logger.warning(f"Quality validation failed (non-critical): {e}", exc_info=True)

        # Gold layer: compute acquisition scores
        try:
            from src.gold import GoldBuilder
            gold_builder = GoldBuilder(storage)
            gold_firms_df = gold_builder.build_gold(dataset_name)
            logger.info(f"Gold layer: computed scores for {len(gold_firms_df)} firms.")
        except Exception as e:
            logger.error(f"Gold layer failed: {e}", exc_info=True)
            raise

        # Step 8: Change detection (monthly comparison)
        try:
            from src.change_detector import ChangeDetector
            detector = ChangeDetector(storage)
            history = detector.get_version_history('firms')
            if len(history) >= 2:
                # Compare current with previous
                prev_version = next((v for v in reversed(history) if v != dataset_name.replace('-', '')), None)
                if prev_version:
                    report = detector.compare_versions(prev_version, dataset_name, 'firms')
                    if 'error' not in report:
                        report_path = detector.save_change_report(dataset_name, report)
                        logger.info(f"Change detection: {report['summary']['added_count']} added, {report['summary']['modified_count']} modified.")
            else:
                logger.info("Change detection: first version, skipping comparison.")
        except Exception as e:
            logger.warning(f"Change detection failed (non-critical): {e}")

        # Schema diff: compare bronze vs silver fields
        try:

            from src.schema_diff import check_schema_drift
            import json
            roster_df = next((df for name, df in dataframes.items()
                            if 'FIRM_ROSTER' in name.upper() or 'IA_SEC' in name.upper()), None)
            if roster_df is not None:
                report = check_schema_drift(list(roster_df.columns))
                if report['missing'] or report['extra']:
                    logger.warning(f"Schema drift: {len(report['missing'])} missing, {len(report['extra'])} extra.")
                    storage.save_artifact(dataset_name, 'schema_diff', f"schema_diff_{int(time.time())}.json", json.dumps(report, indent=2))
            else:
                logger.warning("No firm roster found for schema diff.")
        except Exception as e:
            logger.warning(f"Schema diff failed (non-critical): {e}")

        # Run profiling service on loaded data
        if tables:
            try:
                from src.profiling.profiler import ProfileService
                profile_service = ProfileService(storage)
                logger.info("Starting dataset profiling...")
                for table in tables:
                    profile_results = profile_service.profile_table(dataset_name, table)
                    logger.info(f"Profiled table: {table} (quality score: {profile_results.get('quality', {}).get('quality_score', 'N/A')})")
            except Exception as e:
                logger.warning(f"Profiling failed (non-critical): {e}")
        
        meta['status'] = 'success'
        meta['notes'] = ''

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        meta['status'] = 'failed'
        meta['notes'] = str(e)
    finally:
        meta['execution_time'] = time.time() - start_time
        log_ingestion(meta)
        logger.info(f"Pipeline finished in {meta['execution_time']:.2f}s with status: {meta['status']}")
    return meta
