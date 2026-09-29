import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client.http.exceptions import UnexpectedResponse  # noqa: E402

import vector_store  # noqa: E402


def test_search_returns_empty_list_when_collection_missing():
    """Guards the common first-run case: querying before anything has been
    ingested should degrade to 'no matches', not an unhandled 404."""
    fake_client = MagicMock()
    fake_client.search.side_effect = UnexpectedResponse(
        status_code=404, reason_phrase="Not Found", content=b"collection not found", headers=None
    )

    with patch("vector_store.get_client", return_value=fake_client):
        result = vector_store.search("nonexistent", [0.1, 0.2], top_k=5)

    assert result == []


def test_search_reraises_non_404_errors():
    fake_client = MagicMock()
    fake_client.search.side_effect = UnexpectedResponse(
        status_code=500, reason_phrase="Internal Server Error", content=b"boom", headers=None
    )

    with patch("vector_store.get_client", return_value=fake_client):
        try:
            vector_store.search("codebase", [0.1, 0.2], top_k=5)
            assert False, "expected UnexpectedResponse to propagate"
        except UnexpectedResponse:
            pass
