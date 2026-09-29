# Deploying to AWS (single-VM demo)

One EC2 instance running the full `docker-compose.yml` stack via cloud-init. This is the simplest path to a real deployment, not a production setup.

## Steps

1. Launch an EC2 instance:
   - AMI: Ubuntu 22.04 LTS
   - Instance type: `t3.large` (2 vCPU / 8GB) is enough for the gateway,
     Qdrant, and Ollama running a small quantized model; use a `g4dn.xlarge`
     (has a T4 GPU) if you want real inference throughput instead of a demo.
   - Security group: allow inbound 22 (SSH), 80 (Traefik/HTTP), 3000 (Grafana,
     or tunnel it instead of exposing it publicly).
   - User data: paste `cloud-init.sh` (set `REPO_URL` to your fork first).

2. SSH in and confirm the stack is up:
   ```bash
   ssh ubuntu@<instance-ip>
   cd /opt/codesage-agent && docker compose ps
   ```

3. Pull a model into the running Ollama container:
   ```bash
   docker compose exec ollama ollama pull llama3.1:8b-instruct-q4_0
   ```

4. Hit the API:
   ```bash
   curl -X POST http://<instance-ip>/token -d "username=admin&password=admin"
   ```

## Terraform (optional, not included)

For infrastructure-as-code, wrap the above in a small `main.tf` (VPC, security
group, EC2 instance with the cloud-init script as `user_data`). Left out here
so the demo doesn't require an AWS account to read; the cloud-init script is
the part that actually does the work.

## Cost note

A `t3.large` on-demand is roughly $0.08/hr; stop the instance between demos.
