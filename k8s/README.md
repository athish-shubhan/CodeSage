# Deploying to k3s

These manifests assume `codesage/gateway-api:latest` and
`codesage/retrieval-service:latest` already exist somewhere k3s's
containerd can pull them from. Two ways to get there:

## Option A: local k3s, no registry (fastest for a demo)

Build with the local Docker daemon and import straight into k3s's
containerd, skipping a registry entirely:

```bash
docker build -t codesage/gateway-api:latest ../services/gateway-api
docker build -t codesage/retrieval-service:latest ../services/retrieval-service

docker save codesage/gateway-api:latest | sudo k3s ctr images import -
docker save codesage/retrieval-service:latest | sudo k3s ctr images import -
```

## Option B: a real registry (what you'd do beyond a demo)

Push to any registry (Docker Hub, GHCR, ECR/GCR/ACR) and point the
manifests at it:

```bash
docker build -t ghcr.io/<you>/codesage-gateway-api:latest ../services/gateway-api
docker push ghcr.io/<you>/codesage-gateway-api:latest
# then: kubectl set image deployment/gateway-api gateway-api=ghcr.io/<you>/codesage-gateway-api:latest -n codesage
```

## Apply the manifests

```bash
kubectl apply -k .
kubectl -n codesage get pods -w
```

`ingress.yaml` uses Traefik's `IngressRoute` CRD, which k3s installs by
default (it ships Traefik as its built-in ingress controller), so no extra
controller install is needed.

## Resource footprint

Every deployment sets `resources.requests`/`limits` (see each manifest) so
the scheduler can actually bin-pack the cluster instead of overcommitting;
`ollama`'s GPU limit (`nvidia.com/gpu: 1`) requires the
[NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin)
installed on the cluster; drop that line for a CPU-only node and point
`gateway-api`'s `GATEWAY_LLM_BASE_URL` at a remote/edge inference node
instead (see `../services/edge-inference/README.md`).
