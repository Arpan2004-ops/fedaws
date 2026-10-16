#!/usr/bin/env bash
# Stop every FedMed task and release the Cloud Map registration.
#
#     ./scripts/stop_run.sh
#
# Run this as the last command of every lab session. An AWS Academy session
# expires after four hours, but a Fargate task started inside it keeps running
# and keeps billing after the console has logged you out. This script does not
# depend on the state file: it also finds and stops tasks left behind by an
# earlier session.

source "$(dirname "${BASH_SOURCE[0]}")/aws_common.sh"

require aws
require terraform

CLUSTER="$(tf_output cluster_name)"
SD_SERVICE_ID="$(tf_output_optional cloud_map_service_id)"

log "looking for running tasks in ${CLUSTER}"
mapfile -t TASKS < <(aws ecs list-tasks --cluster "${CLUSTER}" --desired-status RUNNING \
  --query 'taskArns[]' --output text | tr '\t' '\n' | sed '/^$/d')

# A task can also be stuck in PENDING while it pulls its image, which still bills.
mapfile -t PENDING < <(aws ecs list-tasks --cluster "${CLUSTER}" --desired-status PENDING \
  --query 'taskArns[]' --output text | tr '\t' '\n' | sed '/^$/d')
TASKS+=("${PENDING[@]}")

if [[ ${#TASKS[@]} -eq 0 ]]; then
  log "no running or pending tasks"
else
  for task in "${TASKS[@]}"; do
    [[ -n "${task}" ]] || continue
    log "stopping ${task##*/}"
    aws ecs stop-task --cluster "${CLUSTER}" --task "${task}" \
      --reason "stopped by stop_run.sh" >/dev/null
  done
fi

if [[ -n "${SD_SERVICE_ID}" ]]; then
  log "deregistering the aggregator from Cloud Map"
  # Not an error if nothing is registered; a run that already finished cleanly
  # leaves no instance behind.
  aws servicediscovery deregister-instance \
    --service-id "${SD_SERVICE_ID}" \
    --instance-id "fl-server" >/dev/null 2>&1 || log "nothing was registered"
fi

rm -f "${STATE_FILE}"

log "done. Confirm with:"
echo "    aws ecs list-tasks --cluster ${CLUSTER}"
