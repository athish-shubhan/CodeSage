FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ proto/
RUN python -m grpc_tools.protoc \
      -I proto \
      --python_out=. \
      --grpc_python_out=. \
      proto/retrieval.proto

COPY app/ app/

EXPOSE 8000

# Run as an unprivileged user. Numeric, so Kubernetes' runAsNonRoot can verify
# it; with a home directory, so the embedding model's runtime download
# (~/.cache/huggingface) has somewhere writable to go. Nothing writes under /app.
RUN useradd --create-home --uid 10001 --user-group app
USER 10001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
