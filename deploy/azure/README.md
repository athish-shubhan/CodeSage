# Deploying to Azure (single-VM demo)

Same shape as the AWS and GCP paths (`../aws/README.md`, `../gcp/README.md`):
one VM running the full `docker-compose.yml` stack via a cloud-init script.

```bash
az group create --name codesage-rg --location eastus

az vm create \
  --resource-group codesage-rg \
  --name codesage-demo \
  --image Ubuntu2204 \
  --size Standard_D2s_v5 \
  --admin-username azureuser \
  --generate-ssh-keys \
  --custom-data ../aws/cloud-init.sh

az vm open-port --resource-group codesage-rg --name codesage-demo --port 80
az vm open-port --resource-group codesage-rg --name codesage-demo --port 3000  # Grafana; or tunnel instead
```

`--custom-data` runs the same cloud-init script used for AWS (Azure supports
the same cloud-init contract on Ubuntu images), so there's nothing
Azure-specific to write beyond the resource group / VM / firewall rules
above.

For GPU-backed inference instead of a CPU-only demo, use an `NC`-family size
(e.g. `Standard_NC4as_T4_v3`) with the NVIDIA extension
(`az vm extension set --name NvidiaGpuDriverLinux ...`), and run that VM as
the "edge" node (`services/edge-inference/`) while a small CPU VM stays
public-facing.
