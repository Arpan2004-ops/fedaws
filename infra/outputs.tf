# Everything the scripts and the dashboard need to find the deployed stack.
# scripts/start_run.sh reads these with `terraform output -json`.

output "region" {
  value = var.region
}

output "cluster_name" {
  value       = aws_ecs_cluster.this.name
  description = "ECS cluster that runs the aggregator and the hospitals."
}

output "server_task_definition" {
  value       = aws_ecs_task_definition.server.family
  description = "Task definition family for the aggregator."
}

output "hospital_task_definition" {
  value       = aws_ecs_task_definition.hospital.family
  description = "Task definition family shared by every hospital."
}

output "subnet_ids" {
  value       = data.aws_subnets.default.ids
  description = "Subnets tasks are launched into."
}

output "server_security_group" {
  value = aws_security_group.server.id
}

output "hospital_security_group" {
  value = aws_security_group.hospital.id
}

output "hospital_buckets" {
  value       = { for id, bucket in aws_s3_bucket.hospital_data : id => bucket.bucket }
  description = "Private data bucket for each hospital, keyed by hospital id."
}

output "models_bucket" {
  value       = aws_s3_bucket.models.bucket
  description = "Versioned bucket holding every global checkpoint."
}

output "rounds_table" {
  value = aws_dynamodb_table.rounds.name
}

output "audit_table" {
  value = aws_dynamodb_table.audit.name
}

output "ecr_repository_urls" {
  value       = { for key, repo in aws_ecr_repository.this : key => repo.repository_url }
  description = "Push targets for the three images."
}

output "cloud_map_service_id" {
  # join over a splat yields "" when the resource was not created, and never
  # fails the way an index into an empty list does.
  value       = join("", aws_service_discovery_service.server[*].id)
  description = "Service the aggregator's IP is registered against at run time."
}

output "server_dns_name" {
  value       = local.server_dns_name
  description = "Name hospitals dial, and the name in the TLS certificate."
}

output "tls_active" {
  value       = local.tls_active
  description = "Whether the gRPC channel is encrypted in this deployment."
}

output "log_group" {
  value = aws_cloudwatch_log_group.ecs.name
}

output "api_url" {
  value       = join("", aws_apigatewayv2_api.api[*].api_endpoint)
  description = "Base URL of the inference API. Feed this to the dashboard build."
}

output "website_url" {
  value       = join("", [for endpoint in aws_s3_bucket_website_configuration.web[*].website_endpoint : "http://${endpoint}"])
  description = "Public dashboard URL."
}

output "website_bucket" {
  value = join("", aws_s3_bucket.web[*].bucket)
}
