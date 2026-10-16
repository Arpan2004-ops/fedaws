# The federation itself: one Fargate cluster, two task definitions, and the
# network rules that decide who may talk to whom.
#
# Nothing here runs on its own. Both task definitions are launched as one-off
# tasks by scripts/start_run.sh and exit when the run finishes, which is what
# keeps a training run to a few cents. There are deliberately no ECS services,
# because a service would restart the aggregator forever and bill for it.

resource "aws_ecs_cluster" "this" {
  name = var.project

  setting {
    name  = "containerInsights"
    value = "disabled" # Container Insights bills per metric and is not needed here
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = var.log_retention_days
}

# The aggregator accepts gRPC only from the hospital security group. It is not
# reachable from the internet even though the task sits in a public subnet with
# a public IP, because there is no rule that admits any other source.
resource "aws_security_group" "server" {
  name        = "${var.project}-server"
  description = "FedMed aggregation server: gRPC in from hospitals only"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "Pull images from ECR and write to S3, DynamoDB and CloudWatch"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-server" }
}

resource "aws_security_group" "hospital" {
  name        = "${var.project}-hospital"
  description = "FedMed hospital node: outbound only, nothing may dial in"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "Reach the aggregator, ECR and the bucket owned by this hospital"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-hospital" }
}

# Declared as a separate rule rather than inline, so the two groups can reference
# each other without a cycle.
resource "aws_security_group_rule" "server_from_hospitals" {
  type                     = "ingress"
  description              = "Flower gRPC from hospital nodes"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.server.id
  source_security_group_id = aws_security_group.hospital.id
}

# Cloud Map gives the aggregator a stable name, fl-server.fedmed.local, which is
# what the TLS certificate is issued for. A one-off task does not register
# itself, so scripts/start_run.sh registers the task's private IP against this
# service once the task is running and deregisters it afterwards.
resource "aws_service_discovery_private_dns_namespace" "this" {
  count = var.enable_cloud_map ? 1 : 0

  name        = var.namespace_name
  description = "Private namespace for the FedMed federation"
  vpc         = data.aws_vpc.default.id
}

resource "aws_service_discovery_service" "server" {
  count = var.enable_cloud_map ? 1 : 0

  name = "fl-server"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this[0].id

    dns_records {
      ttl  = 10 # short, because the address changes with every run
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }
}

resource "aws_ecs_task_definition" "server" {
  family                   = "${var.project}-server"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = local.lab_role_arn
  task_role_arn            = local.lab_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    merge({
      name      = "fl-server"
      image     = "${aws_ecr_repository.this["server"].repository_url}:latest"
      essential = true

      portMappings = [{
        containerPort = 8080
        protocol      = "tcp"
      }]

      environment = [
        for key, value in merge(local.common_env, {
          BIND_ADDRESS = "0.0.0.0:8080"
          RUN_ID       = "placeholder" # overridden per run by start_run.sh
        }) : { name = key, value = value }
      ]

      # Certificate material arrives as SSM secrets, so the private key never
      # appears in the task definition, in the image, or in terminal output.
      secrets = local.server_tls_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "server"
        }
      }
    }, local.server_tls_entrypoint)
  ])
}

# One definition serves all three hospitals. HOSPITAL_ID, DATA_BUCKET and
# SERVER_ADDRESS are supplied as container overrides at launch, which is why
# adding a fourth hospital needs no infrastructure change at all.
resource "aws_ecs_task_definition" "hospital" {
  family                   = "${var.project}-hospital"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = local.lab_role_arn
  task_role_arn            = local.lab_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    merge({
      name      = "hospital"
      image     = "${aws_ecr_repository.this["hospital"].repository_url}:latest"
      essential = true

      environment = [
        for key, value in merge(local.common_env, {
          HOSPITAL_ID    = "placeholder"
          DATA_BUCKET    = "placeholder"
          SERVER_ADDRESS = local.server_dns_name != "" ? "${local.server_dns_name}:8080" : "placeholder:8080"
          SHARD_KEY      = "shard.npz"
          SHARD_PATH     = "/tmp/shard.npz"
        }) : { name = key, value = value }
      ]

      secrets = local.hospital_tls_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "hospital"
        }
      }
    }, local.hospital_tls_entrypoint)
  ])
}
