.PHONY: up up-gpu up-vllm up-llamacpp down logs pull-model ingest-self test test-retrieval test-eval eval smoke

up:
	docker compose up -d --build

up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

# Alternate LLM backends (see docker-compose.vllm.yml / docker-compose.llamacpp.yml
# for why these exist and how gateway-api swaps between them with no code change).
up-vllm:
	docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d --build --scale ollama=0

up-llamacpp:
	docker compose -f docker-compose.yml -f docker-compose.llamacpp.yml up -d --build --scale ollama=0

down:
	docker compose down

logs:
	docker compose logs -f

pull-model:
	docker compose exec ollama ollama pull $${LLM_MODEL:-llama3.1:8b-instruct-q4_0}

# Indexes this repo itself as a demo corpus (mounted read-only into retrieval-service).
ingest-self:
	python3 scripts/ingest_repo.py --repo-path /data/codesage-agent

test:
	cd services/gateway-api && python3 -m pytest tests/ -q

test-retrieval:
	cd services/retrieval-service && python3 -m pytest tests/ -q

test-eval:
	cd eval && python3 -m pytest tests/ -q

# Runs the retrieval ablation against the ingested corpus (requires `make ingest-self` first)
# and writes eval/report.md.
eval:
	python3 -m grpc_tools.protoc -I services/retrieval-service/proto \
		--python_out=eval --grpc_python_out=eval \
		services/retrieval-service/proto/retrieval.proto
	cd eval && python3 run_eval.py --strategy hybrid
	cd eval && python3 ablation.py

smoke:
	bash scripts/smoke_test.sh
