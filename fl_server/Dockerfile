# Aggregation server image.
#
# Build from the repository root so the shared `common/` package is in context:
#     docker build -f fl_server/Dockerfile -t fedmed-server .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The CPU-only PyTorch wheels are roughly a tenth the size of the default CUDA
# ones, which matters for Fargate cold starts and for ECR storage cost.
COPY fl_server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
        --default-timeout 1000 \
        --retries 10 \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        -r requirements.txt

COPY common /app/common
RUN pip install --no-cache-dir /app/common

COPY fl_server/server.py fl_server/strategy.py /app/

# The global test split is not private hospital data, so it ships in the image.
# That keeps the aggregator free of any read permission on a hospital bucket,
# which is the property the whole design rests on.
COPY data/server /workspace/data/server

# Fargate maps this port through the task ENI; hospitals reach it via Cloud Map.
EXPOSE 8080

# Refuse to run as root, so a compromised aggregator cannot rewrite its own image.
RUN useradd --create-home --uid 10001 fedmed && chown -R fedmed /app /workspace
USER fedmed

CMD ["python", "/app/server.py"]
