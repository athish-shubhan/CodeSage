# Edge inference node

Optional split-deployment mode: run `ollama`, `retrieval-service`, and `qdrant`
on a machine with a GPU (a home workstation, a spot GPU instance, a Jetson-class
edge device) while `gateway-api`, `traefik`, `prometheus`, and `grafana` stay on
a small always-on cloud VM.

Why split this way:
- The cloud VM is cheap (no GPU) and is the only thing that needs a public IP
  and TLS.
- The GPU box does the expensive work (embeddings + LLM inference) and can be
  powered on/off independently, or swapped for a bigger box, without touching
  the public-facing gateway.
- Talks over the same gRPC/HTTP boundaries used in the single-box setup; the
  gateway-api code does not change, only the target host/port env vars do.

## Bring up the edge node

```bash
docker compose -f docker-compose.edge.yml up -d
ollama pull llama3.1:8b-instruct-q4_0   # or run inside the ollama container
```

## Point the cloud gateway at it

On the cloud VM, set in `.env` (see `deploy/aws/README.md`):

```
GATEWAY_LLM_BASE_URL=http://<edge-box-ip-or-vpn-hostname>:11434/v1
GATEWAY_RETRIEVAL_GRPC_TARGET=<edge-box-ip-or-vpn-hostname>:50051
```

For anything beyond a demo, put a WireGuard tunnel or VPC peering link between
the two boxes instead of exposing 11434/50051 to the public internet.
