# TLS material for the Flower channel, held in SSM Parameter Store.
#
# Run scripts/gen_certs.sh before applying with tls_enabled = true. The files are
# read from disk here and delivered to tasks as ECS secrets, so the private key
# is never baked into an image and never printed by a describe-task-definition.
#
# Caveat worth putting in the report: the key passes through Terraform state,
# which is a local file in this project. On a real deployment the state belongs
# in an encrypted S3 backend with a DynamoDB lock table, or the parameters get
# created out of band and referenced by ARN only.

resource "aws_ssm_parameter" "tls_ca" {
  count = local.tls_active ? 1 : 0

  name        = "/${var.project}/tls/ca"
  description = "FedMed self-signed root certificate, pinned by every hospital"
  type        = "SecureString"
  value       = file("${var.certs_dir}/ca.crt")

  tags = { Name = "${var.project} CA certificate" }
}

resource "aws_ssm_parameter" "tls_cert" {
  count = local.tls_active ? 1 : 0

  name        = "/${var.project}/tls/cert"
  description = "FedMed aggregator certificate for fl-server.${var.namespace_name}"
  type        = "SecureString"
  value       = file("${var.certs_dir}/server.crt")

  tags = { Name = "${var.project} server certificate" }
}

resource "aws_ssm_parameter" "tls_key" {
  count = local.tls_active ? 1 : 0

  name        = "/${var.project}/tls/key"
  description = "FedMed aggregator private key"
  type        = "SecureString"
  value       = file("${var.certs_dir}/server.key")

  tags = { Name = "${var.project} server private key" }
}
