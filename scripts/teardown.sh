#!/usr/bin/env bash
# Delete the entire stack.
#
#     ./scripts/teardown.sh
#
# Run this after the final demo. Nothing in the stack bills much at rest, but ECR
# storage and any forgotten task do add up over weeks, and an AWS Academy account
# that runs out of credit locks you out of your own project.

source "$(dirname "${BASH_SOURCE[0]}")/aws_common.sh"

require aws
require terraform

warn "This destroys every bucket, table, image and log group in the FedMed stack."
read -r -p "Type the word destroy to continue: " CONFIRMATION
[[ "${CONFIRMATION}" == "destroy" ]] || die "cancelled"

# Tasks hold on to network interfaces, which blocks security group deletion.
log "stopping anything that is still running"
"${REPO_ROOT}/scripts/stop_run.sh" || warn "stop_run.sh reported a problem, continuing"

log "waiting for the network interfaces to be released"
sleep 30

log "destroying the Terraform stack"
terraform -chdir="${INFRA_DIR}" destroy -auto-approve

log "stack destroyed. Confirm the bill has stopped in the Billing console."
