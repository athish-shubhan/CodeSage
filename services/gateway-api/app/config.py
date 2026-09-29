from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # LLM backend is any server that speaks the OpenAI-compatible
    # /v1/chat/completions API. Ollama, vLLM, and llama.cpp's `llama-server`
    # all implement it, so switching backends is just an env var change,
    # not a code change. `llm_backend` only affects logging/health-check
    # framing; `llm_base_url` is what actually selects the server.
    llm_backend: str = "ollama"  # one of: ollama | vllm | llamacpp
    llm_base_url: str = "http://ollama:11434/v1"
    llm_model: str = "llama3.1:8b-instruct-q4_0"
    llm_model_fast: str = ""  # optional smaller/quicker model for simple agent tasks, see app/agent/model_router.py
    llm_api_key: str = "not-needed"  # local servers ignore this; some SDKs require it be present

    retrieval_grpc_target: str = "retrieval-service:50051"
    default_collection: str = "codebase"
    top_k: int = 5

    # demo credentials for the JWT /token endpoint; swap for a real user
    # store (Postgres, an IdP, etc.) before this ever handles real users.
    demo_username: str = "admin"
    demo_password: str = "admin"

    class Config:
        env_prefix = "GATEWAY_"


settings = Settings()
