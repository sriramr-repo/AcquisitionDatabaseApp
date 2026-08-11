import pytest
from unittest.mock import MagicMock, patch
from src.change_detector import ChangeDetector

@pytest.fixture
def mock_storage():
    return MagicMock()

def test_compare_versions_missing_tables(mock_storage):
    detector = ChangeDetector(storage=mock_storage)
    mock_conn = mock_storage.get_connection.return_value
    mock_conn.execute.return_value.fetchall.return_value = []
    
    result = detector.compare_versions("old", "new")
    assert "error" in result
    assert "Missing tables" in result["error"]


def test_compare_versions_no_changes(mock_storage):
    detector = ChangeDetector(storage=mock_storage)
    mock_conn = mock_storage.get_connection.return_value
    
    # Mock SHOW TABLES
    mock_conn.execute.side_effect = [
        MagicMock(fetchall=lambda: [("silver_firms_old",), ("silver_firms_new",)]),
        MagicMock(df=lambda: MagicMock(columns=["firm_id", "name"], values=[[1, "Firm A"]])), # old
        MagicMock(df=lambda: MagicMock(columns=["firm_id", "name"], values=[[1, "Firm A"]]))  # new
    ]
    
    with patch("src.change_detector.PathResolver.silver_table", side_effect=lambda e, v: f"silver_{e}_{v}"):
        # Mocking logic for df processing
        import pandas as pd
        old_df = pd.DataFrame({"firm_id": [1], "name": ["Firm A"]})
        new_df = pd.DataFrame({"firm_id": [1], "name": ["Firm A"]})
        
        # Reset side_effect for real use
        mock_conn.execute.side_effect = None
        mock_conn.execute.return_value.fetchall.return_value = [("silver_firms_old",), ("silver_firms_new",)]
        mock_conn.execute.return_value.df.side_effect = [old_df, new_df]
        
        result = detector.compare_versions("old", "new")
        assert result["summary"]["added_count"] == 0
        assert result["summary"]["removed_count"] == 0
        assert result["summary"]["modified_count"] == 0


def test_compare_versions_with_changes(mock_storage):
    detector = ChangeDetector(storage=mock_storage)
    mock_conn = mock_storage.get_connection.return_value
    
    import pandas as pd
    old_df = pd.DataFrame({"firm_id": [1, 2], "name": ["Firm A", "Firm B"]})
    new_df = pd.DataFrame({"firm_id": [1, 3], "name": ["Firm A Modified", "Firm C"]})
    
    mock_conn.execute.return_value.fetchall.return_value = [("silver_firms_old",), ("silver_firms_new",)]
    mock_conn.execute.return_value.df.side_effect = [old_df, new_df]
    
    with patch("src.change_detector.PathResolver.silver_table", side_effect=lambda e, v: f"silver_{e}_{v}"):
        result = detector.compare_versions("old", "new")
        assert result["summary"]["added_count"] == 1 # ID 3
        assert result["summary"]["removed_count"] == 1 # ID 2
        assert result["summary"]["modified_count"] == 1 # ID 1
        assert result["modified"][0]["id"] == 1
        assert result["modified"][0]["changes"]["name"]["new"] == "Firm A Modified"

def test_get_version_history(mock_storage):
    detector = ChangeDetector(storage=mock_storage)
    mock_conn = mock_storage.get_connection.return_value
    mock_conn.execute.return_value.fetchall.return_value = [
        ("silver_firms_v1",), ("silver_firms_v2",), ("other_table",)
    ]
    
    history = detector.get_version_history("firms")
    assert history == ["v1", "v2"]