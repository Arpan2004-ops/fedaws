#!/usr/bin/env bash
# Move each hospital's shard into that hospital's own bucket.
#
#     python scripts/partition_data.py     # first, to create the shards
#     ./scripts/upload_data.sh
#
# One shard, one bucket, no shared location. This is the only moment in the whole
# project where images travel anywhere, and after it every image sits in exactly
# one place that only its own hospital reads.

source "$(dirname "${BASH_SOURCE[0]}")/aws_common.sh"

require aws
require terraform

ACCOUNT="$(account_id)"
PROJECT="${PROJECT:-fedmed}"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/data}"

for hospital in a b c; do
  shard="${DATA_DIR}/hospital_${hospital}/shard.npz"
  bucket="${PROJECT}-${ACCOUNT}-data-${hospital}"

  [[ -f "${shard}" ]] || die "missing ${shard}. Run: python scripts/partition_data.py"

  size="$(du -h "${shard}" | cut -f1)"
  log "hospital ${hospital}: ${size} -> s3://${bucket}/shard.npz"
  aws s3 cp "${shard}" "s3://${bucket}/shard.npz" \
    --sse AES256 \
    --only-show-errors
done

log "verifying that each bucket holds exactly one shard"
for hospital in a b c; do
  bucket="${PROJECT}-${ACCOUNT}-data-${hospital}"
  aws s3 ls "s3://${bucket}/" --human-readable
done

cat <<'NOTE'

The aggregator has no reason to read any of these buckets and its image contains
no code path that does. The only dataset it opens is the held-out test split
baked into its own image.
NOTE
