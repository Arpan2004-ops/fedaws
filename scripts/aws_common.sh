#!/usr/bin/env bash
# Shared helpers for the AWS scripts. Sourced, never executed directly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
STATE_FILE="${REPO_ROOT}/.fedmed-run"

# Git Bash rewrites arguments that look like paths, which corrupts ECS ARNs and
# CloudWatch log group names such as /ecs/fedmed.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is not on PATH. See docs/runbook.md for prerequisites."
}

# Read a single Terraform output. Fails loudly rather than returning an empty
# string, because an empty cluster name silently launches nothing.
tf_output() {
  local name="$1"
  local value
  value="$(terraform -chdir="${INFRA_DIR}" output -raw "${name}" 2>/dev/null || true)"
  [[ -n "${value}" ]] || die "Terraform output '${name}' is empty. Has 'terraform apply' finished?"
  printf '%s' "${value}"
}

# Same, but tolerates an empty result for genuinely optional outputs.
tf_output_optional() {
  terraform -chdir="${INFRA_DIR}" output -raw "$1" 2>/dev/null || true
}

# Turn the subnet_ids output into the bare comma-separated form the
# awsvpcConfiguration argument expects.
tf_subnets_csv() {
  terraform -chdir="${INFRA_DIR}" output -json subnet_ids \
    | tr -d '[]" \n\r\t'
}

# Build the --network-configuration argument. Public IPs are required because
# the tasks sit in public subnets with no NAT Gateway; inbound access is closed
# by the security groups regardless.
network_config() {
  local security_group="$1"
  printf 'awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=ENABLED}' \
    "$(tf_subnets_csv)" "${security_group}"
}

# Private IP of a running task, found through its elastic network interface.
task_private_ip() {
  local cluster="$1" task_arn="$2" eni

  eni="$(aws ecs describe-tasks --cluster "${cluster}" --tasks "${task_arn}" \
    --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" \
    --output text)"
  [[ -n "${eni}" && "${eni}" != "None" ]] || die "Could not find the network interface for task ${task_arn}"

  aws ec2 describe-network-interfaces --network-interface-ids "${eni}" \
    --query 'NetworkInterfaces[0].PrivateIpAddress' --output text
}

# Read newline-separated input into the named array. `mapfile` would be shorter
# but it needs bash 4, and macOS still ships bash 3.2 as /bin/bash.
read_lines_into() {
  local target="$1" line
  eval "${target}=()"
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    eval "${target}+=(\"\${line}\")"
  done
}

account_id() {
  aws sts get-caller-identity --query Account --output text
}

# Build a containerOverrides environment list from NAME=VALUE pairs.
# Emits JSON, so values containing spaces or quotes still survive.
env_overrides_json() {
  python_bin="$(command -v python3 || command -v python)"
  [[ -n "${python_bin}" ]] || die "python is required to build the task overrides"
  "${python_bin}" -c '
import json, sys
pairs = []
for item in sys.argv[1:]:
    name, _, value = item.partition("=")
    pairs.append({"name": name, "value": value})
print(json.dumps(pairs))
' "$@"
}
