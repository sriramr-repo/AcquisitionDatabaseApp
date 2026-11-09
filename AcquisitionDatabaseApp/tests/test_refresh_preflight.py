import pytest
from src.refresh_preflight import (
    database_fingerprint,
    database_identity,
    expected_ledger,
    matching_database_identity,
    required_database_urls,
    validate_approved_fingerprint,
    validate_ledger,
)


def test_pooled_and_direct_identity():
    pooled = database_identity("postgres://a:secret@ep-a-pooler.example/db")
    direct = database_identity("postgresql://b:other@ep-a.example/db")
    assert pooled == direct
    assert database_fingerprint(pooled) == database_fingerprint(direct)
    assert "secret" not in str(pooled)


@pytest.mark.parametrize("url", ["", "postgres://localhost/db", "postgres://127.0.0.1/db", "https://example/db", "postgres://example/"])
def test_reject_missing_or_local_target(url):
    with pytest.raises(ValueError):
        database_identity(url)


def test_database_urls_are_both_explicit_and_match():
    with pytest.raises(ValueError, match="PUBLISHER_DATABASE_URL"):
        required_database_urls({"DATABASE_URL": "postgres://prod.example/db"})
    with pytest.raises(ValueError, match="identities differ"):
        matching_database_identity("postgres://prod.example/db", "postgres://stage.example/db")


def test_database_target_must_match_approved_fingerprint():
    identity = database_identity("postgres://prod.example/db")
    expected = database_fingerprint(identity)
    assert validate_approved_fingerprint(identity, expected) == expected
    with pytest.raises(ValueError, match="64-character"):
        validate_approved_fingerprint(identity, "not-a-fingerprint")
    with pytest.raises(ValueError, match="approved production"):
        validate_approved_fingerprint(identity, "0" * 64)


def test_print_target_fingerprint_is_redacted(monkeypatch, capsys):
    import sys
    from src import refresh_preflight as module

    target = "postgres://operator:super-secret@prod.example/db"
    monkeypatch.setenv("DATABASE_URL", target)
    monkeypatch.setenv("PUBLISHER_DATABASE_URL", target)
    monkeypatch.setattr(sys, "argv", ["preflight", "--print-target-fingerprint"])
    module.main()
    output = capsys.readouterr().out
    assert "prod.example" in output
    assert "super-secret" not in output
    assert database_fingerprint(database_identity(target)) in output


def test_ledger_requires_hash_order_and_timestamp():
    expected = [("a", 1), ("b", 2)]
    validate_ledger(expected, expected)
    for actual in ([('a', 1)], [('b', 2), ('a', 1)], [('a', 1), ('bad', 2)], [('a', 1), ('b', 3)]):
        with pytest.raises(ValueError):
            validate_ledger(actual, expected)


def test_local_ledger_available():
    ledger = expected_ledger()
    assert len(ledger) >= 22
    assert len({row[0] for row in ledger}) == len(ledger)


def test_fallback_discovery_blocks_even_with_valid_database(monkeypatch,capsys):
    import sys
    from src import refresh_preflight as module
    target = "postgres://fixture.example/fixture"
    identity = module.database_identity(target)
    monkeypatch.setenv("DATABASE_URL", target)
    monkeypatch.setenv("PUBLISHER_DATABASE_URL", target)
    monkeypatch.setenv("SCM_PRODUCTION_DATABASE_FINGERPRINT", module.database_fingerprint(identity))
    monkeypatch.setattr(sys,'argv',['preflight','--dry-run'])
    monkeypatch.setattr(module,'preflight',lambda **kwargs:{'status':'passed'})
    monkeypatch.setattr(module,'discover_sources',lambda:{'sec':{'url':'https://www.sec.gov/older.zip','fallback_used':True}})
    with pytest.raises(SystemExit) as error:module.main()
    assert error.value.code==1
    assert 'fallback publication is blocked' in capsys.readouterr().out
