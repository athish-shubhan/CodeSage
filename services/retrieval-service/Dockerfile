FROM python:3.11-slim

# Default to the CPU-only torch wheel: PyPI's default `torch` wheel pulls in
# ~1GB of unused NVIDIA/CUDA packages even on a CPU-only host. Pass
# `--build-arg TORCH_VARIANT=cuda` (see docker-compose.gpu.yml /
# services/edge-inference/docker-compose.edge.yml, which both also set
# EMBEDDING_DEVICE=cuda) to get the CUDA-enabled build instead.
ARG TORCH_VARIANT=cpu

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ "$TORCH_VARIANT" = "cpu" ]; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    fi
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ proto/
RUN python -m grpc_tools.protoc \
      -I proto \
      --python_out=. \
      --grpc_python_out=. \
      proto/retrieval.proto

COPY . .

ENV GRPC_PORT=50051 \
    METRICS_PORT=9101 \
    EMBEDDING_DEVICE=cpu

EXPOSE 50051 9101

CMD ["python", "server.py"]
