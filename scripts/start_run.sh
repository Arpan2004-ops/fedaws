#!/usr/bin/env bash
# Launch one federated training run on Fargate.
#
#     ./scripts/start_run.sh                       # ten rounds, defaults from Terraform
#     ROUNDS=20 DP_NOISE=0.2 ./scripts/start_run.sh
#     ./scripts/start_run.sh --follow              # stream the aggregator log
#
# The sequence matters. The aggregator has to be listening and have a resolvable
# address before any hospital dials in, and a one-off Fargate task does not
# register itself in Cloud Map the way a service would. So the script starts the
# aggregator, waits for it, reads its private IP off the task's network
# interface, publishes that IP under fl-server.fedmed.local, and only then starts
# the hospitals.
#
# Everything exits on its own when the rounds finish. Nothing here creates an ECS
# service, so there is no process that will quietly bill overnight.

source "$(dirname "${BASH_SOURCE[0]}")/aws_common.sh"

require aws
require terraform

FOLLOW=false
[[ "${1:-}" == "--follow" ]] && FOLLOW=true

RUN_ID="${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)}"
ROUNDS="${ROUNDS:-}"
LOCAL_EPOCHS="${LOCAL_EPOCHS:-}"
DP_ENABLED="${DP_ENABLED:-}"
DP_NOISE="${DP_NOISE:-}"
DP_CLIP="${DP_CLIP:-}"

CLUSTER="$(tf_output cluster_name)"
SERVER_TD="$(tf_output server_task_definition)"
HOSPITAL_TD="$(tf_output hospital_task_definition)"
SERVER_SG="$(tf_output server_security_group)"
HOSPITAL_SG="$(tf_output hospital_security_group)"
LOG_GROUP="$(tf_output log_group)"
REGION="$(tf_output region)"
SD_SERVICE_ID="$(tf_output_optional cloud_map_service_id)"
SERVER_DNS="$(tf_output_optional server_dns_name)"
TLS_ACTIVE="$(tf_output_optional tls_active)"
ACCOUNT="$(account_id)"
PROJECT="${PROJECT:-fedmed}"

# Optional per-run overrides. Anything left empty keeps the value baked into the
# task definition by Terraform, so a plain run needs no environment at all.
server_env=("RUN_ID=${RUN_ID}")
hospital_env=("RUN_ID=${RUN_ID}")
for pair in "NUM_ROUNDS=${ROUNDS}" "LOCAL_EPOCHS=${LOCAL_EPOCHS}" \
            "DP_ENABLED=${DP_ENABLED}" "DP_NOISE_MULTIPLIER=${DP_NOISE}" \
            "DP_CLIP_NORM=${DP_CLIP}"; do
  [[ "${pair#*=}" != "" ]] && server_env+=("${pair}")
done
for pair in "LOCAL_EPOCHS=${LOCAL_EPOCHS}"; do
  [[ "${pair#*=}" != "" ]] && hospital_env+=("${pair}")
done

log "run id ${RUN_ID}"
log "cluster ${CLUSTER} in ${REGION}"
[[ "${TLS_ACTIVE}" == "true" ]] && log "gRPC channel is TLS encrypted" || warn "gRPC channel is in plaintext (tls_enabled = false)"

# ---------------------------------------------------------------------------
log "starting the aggregation server"
SERVER_TASK_ARN="$(aws ecs run-task \
  --cluster "${CLUSTER}" \
  --launch-type FARGATE \
  --task-definition "${SERVER_TD}" \
  --count 1 \
  --network-configuration "$(network_config "${SERVER_SG}")" \
  --overrides "{\"containerOverrides\":[{\"name\":\"fl-server\",\"environment\":$(env_overrides_json "${server_env[@]}")}]}" \
  --started-by "${RUN_ID}" \
  --query 'tasks[0].taskArn' --output text)"

[[ -n "${SERVER_TASK_ARN}" && "${SERVER_TASK_ARN}" != "None" ]] || die "the aggregator task failed to launch"
log "aggregator task ${SERVER_TASK_ARN##*/}"

log "waiting for the aggregator to reach RUNNING (usually 30 to 60 seconds)"
aws ecs wait tasks-running --cluster "${CLUSTER}" --tasks "${SERVER_TASK_ARN}"

SERVER_IP="$(task_private_ip "${CLUSTER}" "${SERVER_TASK_ARN}")"
log "aggregator private IP ${SERVER_IP}"

# ---------------------------------------------------------------------------
if [[ -n "${SD_SERVICE_ID}" ]]; then
  log "registering ${SERVER_DNS} -> ${SERVER_IP} in Cloud Map"
  aws servicediscovery register-instance \
    --service-id "${SD_SERVICE_ID}" \
    --instance-id "fl-server" \
    --attributes "AWS_INSTANCE_IPV4=${SERVER_IP}" >/dev/null
  SERVER_ADDRESS="${SERVER_DNS}:8080"
  # The record has a ten second TTL but the resolver still needs a moment.
  sleep 10
else
  warn "Cloud Map is disabled, hospitals will dial the IP directly"
  [[ "${TLS_ACTIVE}" == "true" ]] && die "TLS needs the Cloud Map DNS name; set tls_enabled = false or enable_cloud_map = true"
  SERVER_ADDRESS="${SERVER_IP}:8080"
fi

# ---------------------------------------------------------------------------
HOSPITAL_TASK_ARNS=()
for hospital in a b c; do
  bucket="${PROJECT}-${ACCOUNT}-data-${hospital}"
  log "starting hospital ${hospital} against ${bucket}"

  overrides=("${hospital_env[@]}" "HOSPITAL_ID=${hospital}" "DATA_BUCKET=${bucket}" "SERVER_ADDRESS=${SERVER_ADDRESS}")
  arn="$(aws ecs run-task \
    --cluster "${CLUSTER}" \
    --launch-type FARGATE \
    --task-definition "${HOSPITAL_TD}" \
    --count 1 \
    --network-configuration "$(network_config "${HOSPITAL_SG}")" \
    --overrides "{\"containerOverrides\":[{\"name\":\"hospital\",\"environment\":$(env_overrides_json "${overrides[@]}")}]}" \
    --started-by "${RUN_ID}" \
    --query 'tasks[0].taskArn' --output text)"
  [[ -n "${arn}" && "${arn}" != "None" ]] || die "hospital ${hospital} failed to launch"
  HOSPITAL_TASK_ARNS+=("${arn}")
done

# Remember what was started so stop_run.sh can clean up without guessing.
{
  echo "RUN_ID=${RUN_ID}"
  echo "CLUSTER=${CLUSTER}"
  echo "SERVER_TASK_ARN=${SERVER_TASK_ARN}"
  echo "HOSPITAL_TASK_ARNS=${HOSPITAL_TASK_ARNS[*]}"
  echo "SD_SERVICE_ID=${SD_SERVICE_ID}"
} > "${STATE_FILE}"

cat <<SUMMARY

  Run ${RUN_ID} is live.

  Watch it:
    aws logs tail ${LOG_GROUP} --follow --since 5m
    aws ecs list-tasks --cluster ${CLUSTER} --desired-status RUNNING

  Results land in:
    s3://$(tf_output models_bucket)/global/
    DynamoDB table $(tf_output rounds_table), partition key ${RUN_ID}

  Stop everything early:
    ./scripts/stop_run.sh

SUMMARY

if [[ "${FOLLOW}" == "true" ]]; then
  log "streaming logs, press Ctrl-C to detach (the run keeps going)"
  aws logs tail "${LOG_GROUP}" --follow --since 5m
fi
