# Shared lookups and naming.
#
# The stack deliberately uses the account's default VPC and its public subnets.
# Fargate tasks need a route to ECR, S3 and CloudWatch; the alternative to public
# subnets with public IPs is a NAT Gateway, which costs about thirty dollars a
# month and would consume a third of the course credit while sitting idle.
# Inbound access is closed by security group rules instead.

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Bucket names are globally unique, so the account id is appended rather than
  # a random suffix. That keeps names stable across destroy and re-apply cycles,
  # which matters when a lab session expires mid-project.
  name_prefix = "${var.project}-${local.account_id}"

  # AWS Academy pre-creates LabRole with the permissions the lab allows.
  lab_role_arn = var.lab_role_arn != "" ? var.lab_role_arn : "arn:aws:iam::${local.account_id}:role/LabRole"

  server_dns_name = var.enable_cloud_map ? "fl-server.${var.namespace_name}" : ""

  # TLS needs a stable hostname for certificate validation, which only Cloud Map
  # provides here. Asking for TLS without Cloud Map is a configuration error and
  # is caught at plan time rather than at three in the morning before the demo.
  tls_active = var.tls_enabled && var.enable_cloud_map

  common_env = {
    NUM_ROUNDS           = tostring(var.num_rounds)
    NUM_HOSPITALS        = tostring(length(var.hospital_ids))
    LOCAL_EPOCHS         = tostring(var.local_epochs)
    STORAGE_BACKEND      = "s3"
    AWS_REGION           = var.region
    MODELS_BUCKET        = aws_s3_bucket.models.bucket
    ROUNDS_TABLE         = aws_dynamodb_table.rounds.name
    AUDIT_TABLE          = aws_dynamodb_table.audit.name
    DP_ENABLED           = var.dp_enabled ? "true" : "false"
    DP_NOISE_MULTIPLIER  = tostring(var.dp_noise_multiplier)
    DP_CLIP_NORM         = tostring(var.dp_clip_norm)
    TLS_ENABLED          = local.tls_active ? "true" : "false"
    PUSH_CLOUDWATCH      = "true"
    CLOUDWATCH_NAMESPACE = var.project
  }

  # Secret references are built by splatting over the count-guarded parameters
  # rather than by indexing them. A conditional such as
  # `tls_active ? aws_ssm_parameter.tls_ca[0].arn : ...` fails at plan time when
  # the count is zero, because Terraform still evaluates the index. Splatting an
  # empty list simply yields an empty list.
  server_tls_secrets = concat(
    [for arn in aws_ssm_parameter.tls_ca[*].arn : { name = "TLS_CA_PEM", valueFrom = arn }],
    [for arn in aws_ssm_parameter.tls_cert[*].arn : { name = "TLS_CERT_PEM", valueFrom = arn }],
    [for arn in aws_ssm_parameter.tls_key[*].arn : { name = "TLS_KEY_PEM", valueFrom = arn }],
  )

  hospital_tls_secrets = [
    for arn in aws_ssm_parameter.tls_ca[*].arn : { name = "TLS_CA_PEM", valueFrom = arn }
  ]

  # ECS rejects a container definition that carries an explicit null for
  # entryPoint or command, so the TLS bootstrap is merged in as extra keys only
  # when it is actually needed rather than being set to null when it is not.
  #
  # The bootstrap exists because the Python processes want certificate files
  # while ECS delivers SSM secrets as environment variables. A short shell prelude
  # writes them into the task's own ephemeral storage, which is destroyed with
  # the task, and then hands control to the application.
  server_tls_entrypoint = local.tls_active ? {
    entryPoint = ["/bin/sh", "-c"]
    command = [join(" && ", [
      "mkdir -p /tmp/certs",
      "printf '%s' \"$TLS_CA_PEM\" > /tmp/certs/ca.crt",
      "printf '%s' \"$TLS_CERT_PEM\" > /tmp/certs/server.crt",
      "printf '%s' \"$TLS_KEY_PEM\" > /tmp/certs/server.key",
      "export TLS_CA_PATH=/tmp/certs/ca.crt TLS_CERT_PATH=/tmp/certs/server.crt TLS_KEY_PATH=/tmp/certs/server.key",
      "exec python /app/server.py",
    ])]
  } : {}

  hospital_tls_entrypoint = local.tls_active ? {
    entryPoint = ["/bin/sh", "-c"]
    command = [join(" && ", [
      "mkdir -p /tmp/certs",
      "printf '%s' \"$TLS_CA_PEM\" > /tmp/certs/ca.crt",
      "export TLS_CA_PATH=/tmp/certs/ca.crt",
      "exec python /app/client.py",
    ])]
  } : {}
}

resource "terraform_data" "tls_precondition" {
  # A plan-time guard rail rather than a runtime surprise.
  lifecycle {
    precondition {
      condition     = !var.tls_enabled || var.enable_cloud_map
      error_message = "tls_enabled requires enable_cloud_map, because certificate validation needs the stable DNS name fl-server.${var.namespace_name}."
    }
  }
}
