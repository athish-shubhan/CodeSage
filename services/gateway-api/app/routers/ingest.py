import grpc
from fastapi import APIRouter, Depends

from app import rag_client
from app.auth import current_user
from app.errors import downstream_http_exception
from app.models import IngestRequest, IngestResponse

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestResponse)
async def ingest(req: IngestRequest, user: str = Depends(current_user)) -> IngestResponse:
    """Kick off indexing of a repo mounted into the retrieval-service container."""
    try:
        result = await rag_client.ingest_repo(req.repo_path, req.collection, req.include_globs)
    except grpc.aio.AioRpcError as exc:
        raise downstream_http_exception(exc) from exc
    return IngestResponse(**result)
