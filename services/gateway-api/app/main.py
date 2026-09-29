from fastapi import Depends, FastAPI
from fastapi.security import OAuth2PasswordRequestForm
from prometheus_fastapi_instrumentator import Instrumentator

from app import llm_client, rag_client
from app.auth import login_for_token
from app.config import settings
from app.routers import agent, chat, ingest, ws

app = FastAPI(title="CodeSage Gateway API", version="0.1.0")

app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(ws.router)
app.include_router(agent.router)

# Exposes /metrics for Prometheus to scrape (request counts, latency histograms).
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.post("/token")
async def token(form: OAuth2PasswordRequestForm = Depends()) -> dict:
    access_token = login_for_token(form)
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/livez")
async def livez() -> dict:
    """Liveness probe: is this process itself alive? Deliberately checks no
    downstream dependency. A stalled LLM backend should not cause k8s/Docker
    to kill and restart an otherwise-healthy gateway pod."""
    return {"gateway": "ok"}


@app.get("/healthz")
async def healthz() -> dict:
    """Readiness probe: aggregates the LLM and retrieval dependencies, since
    this pod shouldn't receive traffic until both are reachable."""
    llm_ok = await llm_client.health()
    retrieval = await rag_client.health()
    return {
        "gateway": "ok",
        "llm_backend": settings.llm_backend,
        "llm_status": "ok" if llm_ok else "unreachable",
        "retrieval": retrieval,
    }
