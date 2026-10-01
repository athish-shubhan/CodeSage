import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import rag_client  # noqa: E402


@pytest.mark.asyncio
async def test_channel_is_reused_across_calls_on_the_same_loop():
    await rag_client.close()
    first = rag_client._stub()
    channel = rag_client._channel
    rag_client._stub()
    assert rag_client._channel is channel
    assert first is not None
    await rag_client.close()
    assert rag_client._channel is None


@pytest.mark.asyncio
async def test_unreachable_retrieval_service_reports_unhealthy_instead_of_raising(monkeypatch):
    await rag_client.close()
    monkeypatch.setattr(rag_client.settings, "retrieval_grpc_target", "127.0.0.1:1")
    result = await rag_client.health()
    assert result["ok"] is False
    await rag_client.close()
