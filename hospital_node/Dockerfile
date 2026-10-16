# Hospital node image.
#
# One image, three running copies, distinguished only by HOSPITAL_ID. No dataset
# is baked in: a node fetches its own shard at startup from its own bucket, so
# the image itself carries no patient data and is safe to share between sites.
#
#     docker build -f hospital_node/Dockerfile -t fedmed-hospital .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY hospital_node/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
        --default-timeout 1000 \
        --retries 10 \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        -r requirements.txt

COPY common /app/common
RUN pip install --no-cache-dir /app/common

COPY hospital_node/client.py /app/

# Shards land here at runtime: a mounted volume locally, ephemeral task storage
# on Fargate. Nothing under this path survives the container.
RUN mkdir -p /workspace/data

RUN useradd --create-home --uid 10001 fedmed && chown -R fedmed /app /workspace
USER fedmed

CMD ["python", "/app/client.py"]
