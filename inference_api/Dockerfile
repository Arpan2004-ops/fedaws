# Inference API image, built on the AWS Lambda Python base so the same artifact
# runs as a Lambda function and as a local container.
#
#     docker build -f inference_api/Dockerfile -t fedmed-api .
#     docker run -p 9000:8080 fedmed-api          # Lambda runtime emulator
FROM public.ecr.aws/lambda/python:3.11

ENV PIP_DEFAULT_TIMEOUT=1000 \
    PIP_NO_CACHE_DIR=1

COPY inference_api/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir \
        --default-timeout 1000 \
        --retries 10 \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY common ${LAMBDA_TASK_ROOT}/common
RUN pip install --no-cache-dir ${LAMBDA_TASK_ROOT}/common

COPY inference_api/app.py ${LAMBDA_TASK_ROOT}/app.py

# Mangum translates the API Gateway payload into an ASGI scope for FastAPI.
CMD ["app.handler"]
