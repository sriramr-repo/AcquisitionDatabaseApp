import pytest
from src.refresh_preflight import database_identity, expected_ledger, validate_ledger


def test_pooled_and_direct_identity():
    assert database_identity("postgres://a:secret@ep-a-pooler.example/db") == database_identity("postgresql://b:other@ep-a.example/db")
    assert "secret" not in str(database_identity("postgres://a:secret@ep-a.example/db"))


@pytest.mark.parametrize("url", ["", "postgres://localhost/db", "postgres://127.0.0.1/db", "https://example/db", "postgres://example/"])
def test_reject_missing_or_local_target(url):
    with pytest.raises(ValueError):
        database_identity(url)


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
    monkeypatch.setattr(sys,'argv',['preflight','--dry-run'])
    monkeypatch.setattr(module,'preflight',lambda **kwargs:{'status':'passed'})
    monkeypatch.setattr(module,'discover_sources',lambda:{'sec':{'url':'https://www.sec.gov/older.zip','fallback_used':True}})
    with pytest.raises(SystemExit) as error:module.main()
    assert error.value.code==1
    assert 'fallback publication is blocked' in capsys.readouterr().out
