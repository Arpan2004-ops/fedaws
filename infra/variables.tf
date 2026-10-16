variable "project" {
  description = "Name prefix for every resource this stack creates."
  type        = string
  default     = "fedmed"
}

variable "region" {
  description = "AWS region. Keep this at us-east-1 for AWS Academy Learner Lab accounts, which are pinned there."
  type        = string
  default     = "us-east-1"
}

variable "course_tag" {
  description = "Free-text tag so the whole stack is easy to find in Cost Explorer."
  type        = string
  default     = "cloud-computing-project"
}

variable "lab_role_arn" {
  description = <<-DESC
    Execution and task role for every compute resource.

    An AWS Academy Learner Lab cannot create IAM roles, so the stack reuses the
    pre-provisioned LabRole. Leave this empty and the stack builds the standard
    Learner Lab ARN from the current account id. On a normal account, point it at
    a role you created that can read the buckets and write to DynamoDB, ECR,
    CloudWatch Logs and SSM.
  DESC
  type        = string
  default     = ""
}

variable "hospital_ids" {
  description = "One private data bucket and one task is created per id."
  type        = list(string)
  default     = ["a", "b", "c"]
}

variable "task_cpu" {
  description = "Fargate CPU units per task. 1024 = 1 vCPU."
  type        = string
  default     = "1024"
}

variable "task_memory" {
  description = "Fargate memory in MiB. Must be a legal pairing with task_cpu."
  type        = string
  default     = "2048"
}

variable "num_rounds" {
  description = "Federated rounds per training run."
  type        = number
  default     = 10
}

variable "local_epochs" {
  description = "Local passes over a hospital's own data between two aggregations."
  type        = number
  default     = 1
}

variable "dp_enabled" {
  description = "Clip client updates and add Gaussian noise to the aggregate."
  type        = bool
  default     = true
}

variable "dp_noise_multiplier" {
  description = "Gaussian noise scale relative to the clipping norm. Higher means more privacy and lower accuracy."
  type        = number
  default     = 0.05
}

variable "dp_clip_norm" {
  description = "L2 norm each client update is clipped to before aggregation."
  type        = number
  default     = 1.0
}

variable "tls_enabled" {
  description = <<-DESC
    Encrypt the Flower gRPC channel.

    Requires that scripts/gen_certs.sh has been run, because the certificate
    files are read from certs_dir and stored in SSM Parameter Store. It also
    requires Cloud Map, since a hospital validates the aggregator's certificate
    against the DNS name and a Fargate task's IP changes on every run.
  DESC
  type        = bool
  default     = false
}

variable "certs_dir" {
  description = "Directory holding ca.crt, server.crt and server.key, relative to infra/."
  type        = string
  default     = "../certs"
}

variable "enable_cloud_map" {
  description = "Create a private DNS namespace so hospitals can reach the aggregator by name instead of by IP."
  type        = bool
  default     = true
}

variable "namespace_name" {
  description = "Private DNS namespace. Must match the name in the TLS certificate's SAN list."
  type        = string
  default     = "fedmed.local"
}

variable "create_lambda" {
  description = <<-DESC
    Create the inference Lambda and its API Gateway.

    Set this to false for the very first apply: the function needs an image that
    only exists after the ECR repositories have been created and pushed to. See
    docs/runbook.md for the two-phase order.
  DESC
  type        = bool
  default     = true
}

variable "api_image_tag" {
  description = "Tag of the inference API image in ECR."
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  description = "CloudWatch log retention. Short retention keeps the free tier comfortable."
  type        = number
  default     = 7
}

variable "enable_public_website" {
  description = "Serve the dashboard from an S3 static website. Turn off if the account blocks public buckets."
  type        = bool
  default     = true
}
