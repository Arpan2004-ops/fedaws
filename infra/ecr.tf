# Container registries, one per component.
#
# These must exist before any image can be pushed, and the Lambda function
# cannot be created until its image is in place. That is why the runbook applies
# this file on its own first:
#
#     terraform apply -target=aws_ecr_repository.this

locals {
  ecr_repositories = ["server", "hospital", "api"]
}

resource "aws_ecr_repository" "this" {
  for_each = toset(local.ecr_repositories)

  name                 = "${var.project}-${each.key}"
  image_tag_mutability = "MUTABLE" # the demo repeatedly overwrites :latest
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project} ${each.key} image"
  }
}

# Untagged layers accumulate every time :latest is overwritten. ECR storage is
# ten cents per gigabyte-month and a PyTorch image is not small, so expiring them
# keeps the bill in the noise.
resource "aws_ecr_lifecycle_policy" "expire_untagged" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Delete untagged images after one day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the five most recent tagged images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = { type = "expire" }
      },
    ]
  })
}
