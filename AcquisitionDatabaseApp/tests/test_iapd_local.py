from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import date

import duckdb
import pytest

from src.iapd_local import (
    BUNDLE_SCHEMA_VERSION,
    IAPDLocalError,
    R2Config,
    build_local_store,
    generate_firm_bundles,
    load_firm_ids,
    publish_bundles_to_r2,
)


SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<IAPD>
  <Indvl>
    <Info><firstName>Jane</firstName><lastName>Advisor</lastName><indvlPK>12345</indvlPK><activeAGRegistration>Y</activeAGRegistration></Info>
    <CrntEmps><CrntEmp><orgPK>98765</orgPK><orgName>Example Advisory LLC</orgName><city>Boston</city><state>MA</state>
      <CrntRgstns><CrntRgstn><regAuthority>MA</regAuthority><regStatus>Approved</regStatus></CrntRgstn></CrntRgstns>
    </CrntEmp></CrntEmps>
    <OthrNms><OthrNm><firstName>J</firstName><lastName>Advisor</lastName></OthrNm></OthrNms>
    <EmpHss><EmpHs><orgName>Prior Firm</orgName><fromDate>2020-01-01</fromDate></EmpHs></EmpHss>
    <OthrBuss><OthrBus><description>Insurance agent</description></OthrBus></OthrBuss>
    <DRPs><DRP><criminal>Y</criminal></DRP></DRPs>
  </Indvl>
  <Indvl><Info><firstName>No</firstName><lastName>Employer</lastName><indvlPK>54321</indvlPK></Info></Indvl>
</IAPD>"""


def _source_zip(tmp_path):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("feed.xml", SAMPLE_XML)
    return path


def _build(tmp_path):
    return build_local_store(
        source_zip=_source_zip(tmp_path),
        source_url="https://example.test/feed.zip",
        snapshot_date=date(2026, 8, 20),
        dataset_version="fixture",
        output_root=tmp_path / "local",
        expected_current_links=1,
        batch_size=1,
    )


def test_local_store_is_atomic_complete_and_parquet_backed(tmp_path):
    result = _build(tmp_path)
    assert result["person_count"] == 2
    assert result["current_link_count"] == 1
    assert result["firm_count"] == 1
    database = tmp_path / "local" / "datasets" / "fixture" / "iapd.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("select count(*) from iapd_people").fetchone()[0] == 2
        payload = json.loads(connection.execute(
            "select payload_json from iapd_people where individual_crd='12345'"
        ).fetchone()[0])
    assert payload["employment_history"][0]["organization_name"] == "Prior Firm"
    assert (database.parent / "parquet" / "iapd_people.parquet").is_file()
    current = json.loads((tmp_path / "local" / "current.json").read_text())
    assert current["dataset_version"] == "fixture"


def test_local_store_rejects_count_mismatch_without_activation(tmp_path):
    with pytest.raises(IAPDLocalError, match="dashboard link invariant"):
        build_local_store(
            source_zip=_source_zip(tmp_path),
            source_url="https://example.test/feed.zip",
            snapshot_date=date(2026, 8, 20),
            dataset_version="bad",
            output_root=tmp_path / "local",
            expected_current_links=99,
        )
    assert not (tmp_path / "local" / "datasets" / "bad").exists()


def test_local_store_preserves_national_links_and_validates_dashboard_subset(tmp_path):
    result = build_local_store(
        source_zip=_source_zip(tmp_path), source_url="https://example.test/feed.zip",
        snapshot_date=date(2026, 8, 20), dataset_version="subset",
        output_root=tmp_path / "local", expected_current_links=0,
        dashboard_firm_ids={"11111"},
    )
    assert result["current_link_count"] == 1
    assert result["dashboard_link_count"] == 0
    assert result["dashboard_firm_count"] == 0


def test_local_store_deduplicates_multiple_employments_for_same_firm_person(tmp_path):
    duplicate = SAMPLE_XML.replace(
        b"</CrntEmps>",
        b"<CrntEmp><orgPK>98765</orgPK><orgName>Example Advisory Alternate</orgName></CrntEmp></CrntEmps>",
        1,
    )
    source = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("feed.xml", duplicate)
    result = build_local_store(
        source_zip=source, source_url="https://example.test/duplicate.zip",
        snapshot_date=date(2026, 8, 20), dataset_version="deduped",
        output_root=tmp_path / "local", expected_current_links=1,
    )
    assert result["current_link_count"] == 1


def test_bundles_are_deterministic_complete_and_preserve_nested_details(tmp_path):
    _build(tmp_path)
    first = generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765", "11111"},
    )
    manifest_path = tmp_path / "bundles" / "fixture" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert first["firm_count"] == 2
    assert first["available_bundle_count"] == 1
    assert first["unavailable_bundle_count"] == 1
    assert first["representative_count"] == 1
    entries = {entry["firm_id"]: entry for entry in manifest["entries"]}
    assert entries["11111"]["status"] == "NO_CURRENT_REPRESENTATIVE"
    bundle_path = manifest_path.parent / entries["98765"]["relative_path"]
    first_bytes = bundle_path.read_bytes()
    with gzip.open(bundle_path, "rt") as stream:
        bundle = json.load(stream)
    assert bundle["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert bundle["representatives"][0]["current_employment"]["employer_firm_crd"] == "98765"
    assert bundle["representatives"][0]["has_disclosures"] is True
    assert bundle["representatives"][0]["disclosure_categories"] == ["criminal"]
    assert bundle["representatives"][0]["has_other_business"] is True
    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765", "11111"},
    )
    assert bundle_path.read_bytes() == first_bytes
    assert (tmp_path / "bundles" / "fixture.previous").is_dir()

    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765", "11111"},
    )
    assert (tmp_path / "bundles" / "fixture.previous").is_dir()
    assert (tmp_path / "bundles" / "fixture.previous.1").is_dir()


def test_firm_universe_loader_rejects_identifier_injection(tmp_path):
    database = tmp_path / "firms.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("create table firms(firm_id varchar)")
        connection.execute("insert into firms values ('1'),('2'),(null)")
    assert load_firm_ids(source_duckdb=database, table_name="firms") == {"1", "2"}
    with pytest.raises(ValueError, match="safe SQL identifiers"):
        load_firm_ids(source_duckdb=database, table_name="firms;drop table firms")


class MissingObject(Exception):
    response = {"Error": {"Code": "404"}}


class FakeR2:
    def __init__(self):
        self.objects = {}
        self.put_order = []

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise MissingObject()
        value = self.objects[Key]
        return {"ContentLength": len(value["body"]), "Metadata": value["metadata"]}

    def head_bucket(self, *, Bucket):
        return {}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise MissingObject()
        value = self.objects[Key]
        return {"Body": io.BytesIO(value["body"]), "Metadata": value["metadata"]}

    def put_object(self, *, Bucket, Key, Body, Metadata, **kwargs):
        body = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.objects[Key] = {"body": body, "metadata": Metadata}
        self.put_order.append(Key)
        return {}


def test_r2_publication_is_verified_idempotent_and_activates_manifest_last(tmp_path):
    _build(tmp_path)
    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765", "11111"},
    )
    fake = FakeR2()
    config = R2Config("account", "key", "secret", "bucket")
    manifest = tmp_path / "bundles" / "fixture" / "manifest.json"
    first = publish_bundles_to_r2(manifest_path=manifest, config=config, client=fake)
    assert first["uploaded_bundles"] == 1
    assert first["verified_bundles"] == 1
    assert fake.put_order[-1] == "iapd/fixture/manifest.json"
    second = publish_bundles_to_r2(manifest_path=manifest, config=config, client=fake)
    assert second["uploaded_bundles"] == 0
    assert second["skipped_bundles"] == 1
    assert second["manifest_uploaded"] == 0
    assert second["rollback_manifest_key"] == f"iapd/fixture/manifests/{first['manifest_sha256']}.json"


def test_r2_force_publication_reuploads_every_bundle_and_manifest_last(tmp_path):
    _build(tmp_path)
    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765", "11111"},
    )
    fake = FakeR2()
    config = R2Config("account", "key", "secret", "bucket")
    manifest = tmp_path / "bundles" / "fixture" / "manifest.json"
    local_manifest_bytes = manifest.read_bytes()
    first = publish_bundles_to_r2(manifest_path=manifest, config=config, client=fake)
    fake.put_order.clear()
    forced = publish_bundles_to_r2(
        manifest_path=manifest, config=config, client=fake, force=True,
    )
    assert forced["force"] is True
    assert forced["uploaded_bundles"] == 1
    assert forced["skipped_bundles"] == 0
    assert forced["manifest_uploaded"] == 1
    assert forced["rollback_manifest_key"] == f"iapd/fixture/manifests/{first['manifest_sha256']}.json"
    assert fake.put_order[-1] == "iapd/fixture/manifest.json"
    assert any(key.startswith("iapd/fixture/objects/") for key in fake.put_order)
    assert manifest.read_bytes() == local_manifest_bytes


def test_r2_failed_force_publish_does_not_replace_active_manifest(tmp_path):
    _build(tmp_path)
    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765"},
    )
    fake = FakeR2()
    config = R2Config("account", "key", "secret", "bucket")
    manifest = tmp_path / "bundles" / "fixture" / "manifest.json"
    publish_bundles_to_r2(manifest_path=manifest, config=config, client=fake)
    active_before = fake.objects["iapd/fixture/manifest.json"]["body"]
    original_put = fake.put_object

    def fail_bundle_put(**kwargs):
        if "/objects/" in kwargs["Key"]:
            raise RuntimeError("simulated interrupted upload")
        return original_put(**kwargs)

    fake.put_object = fail_bundle_put
    with pytest.raises(RuntimeError, match="interrupted"):
        publish_bundles_to_r2(
            manifest_path=manifest, config=config, client=fake, force=True,
        )
    assert fake.objects["iapd/fixture/manifest.json"]["body"] == active_before


def test_r2_rejects_malformed_manifest_before_bucket_writes(tmp_path):
    _build(tmp_path)
    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765"},
    )
    manifest = tmp_path / "bundles" / "fixture" / "manifest.json"
    payload = json.loads(manifest.read_text())
    payload["entries"][0]["relative_path"] = "../outside.json.gz"
    manifest.write_text(json.dumps(payload))
    fake = FakeR2()
    with pytest.raises(IAPDLocalError, match="entry is invalid"):
        publish_bundles_to_r2(
            manifest_path=manifest,
            config=R2Config("account", "key", "secret", "bucket"),
            client=fake,
            force=True,
        )
    assert fake.put_order == []


def test_r2_refuses_tampered_bundle(tmp_path):
    _build(tmp_path)
    generate_firm_bundles(
        dataset_version="fixture", local_root=tmp_path / "local",
        output_root=tmp_path / "bundles", firm_ids={"98765"},
    )
    bundle = tmp_path / "bundles" / "fixture" / "firms" / "98765.json.gz"
    bundle.write_bytes(b"tampered")
    with pytest.raises(IAPDLocalError, match="integrity failed"):
        publish_bundles_to_r2(
            manifest_path=tmp_path / "bundles" / "fixture" / "manifest.json",
            config=R2Config("account", "key", "secret", "bucket"),
            client=FakeR2(),
        )


@pytest.mark.parametrize("workers", [0, 65])
def test_r2_rejects_unsafe_worker_counts_before_remote_access(tmp_path, workers):
    fake = FakeR2()
    with pytest.raises(ValueError, match="between 1 and 64"):
        publish_bundles_to_r2(
            manifest_path=tmp_path / "missing.json",
            config=R2Config("account", "key", "secret", "bucket"),
            client=fake,
            workers=workers,
        )
    assert fake.put_order == []
