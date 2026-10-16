#!/usr/bin/env bash
# Build the dashboard against the deployed API and publish it to S3.
#
#     ./scripts/deploy_web.sh
#
# The API URL is baked in at build time as VITE_API_URL, so the published bundle
# is self-contained and the browser never has to be told where the backend lives.

source "$(dirname "${BASH_SOURCE[0]}")/aws_common.sh"

require aws
require terraform
require npm

API_URL="$(tf_output api_url)"
BUCKET="$(tf_output website_bucket)"
SITE_URL="$(tf_output website_url)"

log "API      ${API_URL}"
log "bucket   s3://${BUCKET}"

cd "${REPO_ROOT}/dashboard"

# The per-hospital class balance is a property of how the data was split, not
# something the API knows, so the manifest is copied into the bundle.
if [[ -f "${REPO_ROOT}/data/partition_summary.json" ]]; then
  cp "${REPO_ROOT}/data/partition_summary.json" public/partition_summary.json
  log "bundled the partition manifest"
else
  warn "data/partition_summary.json is missing; hospital cards will fall back to training metrics"
fi

# The centralised baseline is what the federated curve is compared against.
if [[ -f "${REPO_ROOT}/artifacts/centralized_baseline.json" ]]; then
  cp "${REPO_ROOT}/artifacts/centralized_baseline.json" public/centralized_baseline.json
  log "bundled the centralised baseline"
else
  warn "no centralised baseline found; run scripts/train_centralized.py to draw the comparison line"
fi

if [[ ! -d node_modules ]]; then
  log "installing dashboard dependencies"
  npm install
fi

log "building the dashboard"
VITE_API_URL="${API_URL}" npm run build

log "uploading"
# Hashed asset filenames can be cached hard; index.html must not be, or a
# redeploy during the demo will keep serving the previous bundle.
aws s3 sync dist "s3://${BUCKET}" \
  --delete \
  --exclude index.html \
  --cache-control "public,max-age=31536000,immutable" \
  --only-show-errors

aws s3 cp dist/index.html "s3://${BUCKET}/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html" \
  --only-show-errors

cat <<SUMMARY

  Dashboard published.

      ${SITE_URL}

  It is plain HTTP on an S3 website endpoint. That is acceptable here because the
  page holds no credentials and no patient data, and it is called out in
  docs/threat-model.md rather than left as a silent gap.

SUMMARY
