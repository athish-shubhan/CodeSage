# Deploying to GCP (single-VM demo)

Same shape as the AWS path (`../aws/README.md`), using a Compute Engine VM
with startup-script instead of cloud-init user-data.

```bash
gcloud compute instances create codesage-demo \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --machine-type=e2-standard-2 \
  --tags=http-server \
  --metadata-from-file startup-script=../aws/cloud-init.sh

gcloud compute firewall-rules create allow-codesage-http \
  --allow=tcp:80,tcp:3000 --target-tags=http-server
```

For GPU-backed inference, use an `a2` or `g2` machine type with an attached
GPU and the NVIDIA driver startup script GCP documents for Compute Engine,
then run the retrieval-service/Ollama pair as the "edge" node
(`services/edge-inference/`) while this VM stays CPU-only and public-facing.
