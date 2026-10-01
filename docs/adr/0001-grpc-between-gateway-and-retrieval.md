# 0001: gRPC between gateway-api and retrieval-service

**Status:** accepted

## Context

The gateway (public, stateless, cheap) and the retrieval-service (embedding model, index, needs CPU/GPU and disk) are split so they can run on different machines: a small cloud VM and a GPU or on-prem box. The call between them happens on every chat and agent tool call.

## Options

1. REST/JSON over HTTP.
2. gRPC with a shared `.proto`.
3. Keep retrieval in-process in the gateway.

## Decision

gRPC (`proto/retrieval.proto`), with one long-lived channel per gateway process, keepalive, and a retry policy limited to `UNAVAILABLE`.

## Why

- The proto is the contract. Both services generate code from it, so a renamed field breaks the build rather than a request at runtime.
- In-process retrieval would force the gateway to carry torch and the embedding model, which defeats the cloud/edge split.
- REST would work, but adds hand-written request/response validation on both sides for no benefit on an internal-only link.

## Trade-offs

- Generated stubs must be rebuilt in each service (`protoc` in both Dockerfiles and CI). They are gitignored, so a stale checkout must regenerate before running tests.
- Two copies of the proto exist, one per service directory, so each Docker build context is self-contained. The `proto-sync` CI job fails if they differ.

## Consequences

The first version opened a new channel per call. `scripts/bench_grpc_channel.py` measured that against a shared channel on loopback (1000 calls, 3 runs): p50 0.57 ms vs 0.24 ms, p99 0.77 ms vs 0.29 ms. The absolute saving is small next to a search, but the shared channel is also what makes keepalive and the retry policy meaningful, and on a real cloud-to-edge link each new channel costs at least one extra network round trip (not measured here).

The retry policy is only safe because every RPC is idempotent, including `IngestRepo` since ADR 0004.
