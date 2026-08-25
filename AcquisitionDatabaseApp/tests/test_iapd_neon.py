from __future__ import annotations

import pytest

from src.iapd_neon import DETAIL_TABLES, NeonCleanupBlocked, validate_cleanup_documents


def documents():
    manifest = {
        "dataset_version": "v1", "firm_count": 3,
        "available_bundle_count": 2, "representative_count": 5,
    }
    r2 = {
        "status": "success", "dataset_version": "v1", "verified_bundles": 2,
        "manifest_key": "iapd/v1/manifest.json", "manifest_sha256": "abc",
    }
    backup = {
        "status": "success", "dataset_version": "v1",
        "tables": [{"table": table, "rows": 0} for table in DETAIL_TABLES],
    }
    return manifest, r2, backup


def test_cleanup_documents_require_complete_backup_and_verified_r2():
    manifest, r2, backup = documents()
    assert validate_cleanup_documents(
        dataset_version="v1", bundle_manifest=manifest,
        r2_report=r2, backup_manifest=backup,
    ) == {"firm_count": 3, "representative_count": 5, "available_bundle_count": 2}


def test_cleanup_is_blocked_when_any_r2_bundle_is_unverified():
    manifest, r2, backup = documents()
    r2["verified_bundles"] = 1
    with pytest.raises(NeonCleanupBlocked, match="not every"):
        validate_cleanup_documents(
            dataset_version="v1", bundle_manifest=manifest,
            r2_report=r2, backup_manifest=backup,
        )


def test_cleanup_is_blocked_when_backup_omits_a_table():
    manifest, r2, backup = documents()
    backup["tables"].pop()
    with pytest.raises(NeonCleanupBlocked, match="backup omits"):
        validate_cleanup_documents(
            dataset_version="v1", bundle_manifest=manifest,
            r2_report=r2, backup_manifest=backup,
        )
