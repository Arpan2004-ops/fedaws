#!/usr/bin/env bash
# Build the three images and push them to ECR.
#
#     ./scripts/push_images.sh              # all three
#     ./scripts/push_images.sh api          # just one
#
# The images are built for linux/amd64 explicitly. On an Apple Silicon laptop the
# default build produces arm64 images, and a Fargate task definition pinned to
# X86_64 will then fail at startup with an exec format error that is genuinely
# hard to read.

source "$(dirname "${BASH_SOURCE[0]}")/aws_common.sh"

require aws
require docker
require terraform

TARGETS=("$@")
[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=(server hospital api)

REGION="$(tf_output region)"
ACCOUNT="$(account_id)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

log "signing in to ${REGISTRY}"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

dockerfile_for() {
  case "$1" in
    server)   echo "fl_server/Dockerfile" ;;
    hospital) echo "hospital_node/Dockerfile" ;;
    api)      echo "inference_api/Dockerfile" ;;
    *)        die "unknown image '$1'. Choose from: server, hospital, api" ;;
  esac
}

# fl_server/Dockerfile bakes the held-out test set into the image, so that the
# aggregator needs no read permission on any hospital bucket. Without the file
# the build fails several minutes in, with a message that does not say why.
if [[ " ${TARGETS[*]} " == *" server "* && ! -f "${REPO_ROOT}/data/server/test.npz" ]]; then
  die "data/server/test.npz is missing. Run: python scripts/partition_data.py"
fi

for target in "${TARGETS[@]}"; do
  dockerfile="$(dockerfile_for "${target}")"
  repository="${REGISTRY}/fedmed-${target}"

  log "building fedmed-${target} from ${dockerfile}"
  docker build \
    --platform linux/amd64 \
    -f "${REPO_ROOT}/${dockerfile}" \
    -t "${repository}:latest" \
    "${REPO_ROOT}"

  log "pushing ${repository}:latest"
  docker push "${repository}:latest"
done

log "images pushed"
echo
echo "If you changed the inference API, publish the new image to the function:"
echo "    aws lambda update-function-code --function-name fedmed-inference-api \\"
echo "        --image-uri ${REGISTRY}/fedmed-api:latest"
