# The dashboard, served as an S3 static website.
#
# A CloudFront distribution would add HTTPS and a nicer domain, but it also adds
# fifteen minutes to every deploy while the distribution propagates, and the
# course credit does not benefit. The website endpoint is plain HTTP, which is
# acceptable here only because the dashboard carries no credentials and no
# patient data. Say so in the report rather than leaving it implicit.

resource "aws_s3_bucket" "web" {
  count = var.enable_public_website ? 1 : 0

  bucket        = "${local.name_prefix}-web"
  force_destroy = true

  tags = {
    Name      = "FedMed dashboard"
    DataClass = "public"
  }
}

resource "aws_s3_bucket_website_configuration" "web" {
  count = var.enable_public_website ? 1 : 0

  bucket = aws_s3_bucket.web[0].id

  index_document {
    suffix = "index.html"
  }

  # A single-page app has no server-side routes, so a missing key should render
  # the app rather than an XML error document.
  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_public_access_block" "web" {
  count = var.enable_public_website ? 1 : 0

  bucket = aws_s3_bucket.web[0].id

  # This is the one bucket in the stack that is meant to be readable by anyone.
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "web_public_read" {
  count = var.enable_public_website ? 1 : 0

  bucket = aws_s3_bucket.web[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadForWebsite"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.web[0].arn}/*"
    }]
  })

  # Without this ordering the policy is rejected while the block is still on.
  depends_on = [aws_s3_bucket_public_access_block.web]
}
