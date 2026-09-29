#!/bin/bash
# Quantizes an f16/f32 GGUF model to a smaller GGUF quant level using
# llama.cpp's own `llama-quantize` tool, via its Docker image so nothing
# needs to be built locally.
#
# This is the concrete quantization step behind the pre-quantized model tags
# used elsewhere in this repo (e.g. Ollama's `...-q4_0` tags do the same
# thing under the hood): fewer bits per weight -> smaller memory footprint
# and faster inference, at some quality cost. Q4_K_M is a common
# quality/size middle ground; Q5_K_M/Q8_0 trade size for quality, Q2_K/Q3_K
# trade quality for size.
#
# Usage:
#   ./scripts/quantize_gguf.sh models/mistral-7b-instruct.f16.gguf \
#                              models/mistral-7b-instruct.Q4_K_M.gguf \
#                              Q4_K_M
set -euo pipefail

IN_FILE="${1:?usage: quantize_gguf.sh <input.gguf> <output.gguf> <quant-type, e.g. Q4_K_M>}"
OUT_FILE="${2:?usage: quantize_gguf.sh <input.gguf> <output.gguf> <quant-type, e.g. Q4_K_M>}"
QUANT_TYPE="${3:-Q4_K_M}"

MODELS_DIR="$(cd "$(dirname "$IN_FILE")" && pwd)"
IN_NAME="$(basename "$IN_FILE")"
OUT_NAME="$(basename "$OUT_FILE")"

docker run --rm \
  -v "$MODELS_DIR:/models" \
  ghcr.io/ggml-org/llama.cpp:full \
  --quantize "/models/$IN_NAME" "/models/$OUT_NAME" "$QUANT_TYPE"

echo "Wrote $OUT_FILE ($(du -h "$OUT_FILE" 2>/dev/null | cut -f1))"
