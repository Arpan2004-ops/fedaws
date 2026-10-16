# Buckets and tables.
#
# The important structural claim of the whole project lives here: each hospital
# gets its own bucket. There is no shared "raw images" bucket anywhere in the
# stack, so there is no location a curious operator could go to read the pooled
# dataset. The aggregator is given the models bucket and nothing else.

resource "aws_s3_bucket" "hospital_data" {
  for_each = toset(var.hospital_ids)
  bucket   = "${local.name_prefix}-data-${each.key}"

  # A teaching stack gets torn down and rebuilt often; without this a destroy
  # fails on any bucket that still holds a shard.
  force_destroy = true

  tags = {
    Name       = "Hospital ${upper(each.key)} private imaging data"
    DataClass  = "sensitive"
    HospitalId = each.key
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "hospital_data" {
  for_each = aws_s3_bucket.hospital_data
  bucket   = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "hospital_data" {
  for_each = aws_s3_bucket.hospital_data
  bucket   = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "hospital_data" {
  for_each = aws_s3_bucket.hospital_data
  bucket   = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Deny any request that is not TLS. Learner Lab accounts share one role across
# every task, so this policy is the enforceable half of the isolation story: it
# is attached to the bucket itself rather than to a caller.
resource "aws_s3_bucket_policy" "hospital_data_tls_only" {
  for_each = aws_s3_bucket.hospital_data
  bucket   = each.value.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyUnencryptedTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        each.value.arn,
        "${each.value.arn}/*",
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.hospital_data]
}

# Global model checkpoints. Versioning turns the bucket into an audit log: every
# round is a distinct object, and a checkpoint cannot be silently replaced.
resource "aws_s3_bucket" "models" {
  bucket        = "${local.name_prefix}-models"
  force_destroy = true

  tags = {
    Name      = "Federated global model checkpoints"
    DataClass = "derived"
  }
}

resource "aws_s3_bucket_versioning" "models" {
  bucket = aws_s3_bucket.models.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "models" {
  bucket = aws_s3_bucket.models.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "models" {
  bucket = aws_s3_bucket.models.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Old checkpoint versions pile up across demo runs and are never looked at again.
resource "aws_s3_bucket_lifecycle_configuration" "models" {
  bucket = aws_s3_bucket.models.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 14
    }
  }

  depends_on = [aws_s3_bucket_versioning.models]
}

# One item per federated round. run_id partitions the table so several demo runs
# coexist and the dashboard can ask for a specific one.
resource "aws_dynamodb_table" "rounds" {
  name         = "${var.project}-rounds"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "round"

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "round"
    type = "N"
  }

  point_in_time_recovery {
    enabled = false # a teaching dataset; recovery would only add cost
  }

  tags = {
    Name = "Federated training round history"
  }
}

# Prediction audit trail. The partition key is a SHA-256 of the uploaded bytes,
# so the table proves that a given image was submitted without storing anything
# the image could be reconstructed from.
resource "aws_dynamodb_table" "audit" {
  name         = "${var.project}-audit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_hash"
  range_key    = "timestamp"

  attribute {
    name = "request_hash"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "Inference audit trail (hashes only)"
  }
}
