# The inference API: a Lambda container image behind an HTTP API Gateway.
#
# Lambda rather than a load-balanced service because the API is idle except
# during a demo. An Application Load Balancer costs about sixteen dollars a month
# whether or not anyone calls it; this combination costs nothing at rest and
# stays inside the free tier at demo volumes.
#
# The trade is cold starts. The image carries PyTorch, so the first request after
# an idle period takes several seconds while the runtime unpacks and the model
# loads from S3. Memory is set high partly for that reason: Lambda scales CPU
# with memory, so more memory makes the cold start noticeably shorter.

resource "aws_lambda_function" "api" {
  count = var.create_lambda ? 1 : 0

  function_name = "${var.project}-inference-api"
  role          = local.lab_role_arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this["api"].repository_url}:${var.api_image_tag}"

  memory_size = 2048
  timeout     = 60

  ephemeral_storage {
    size = 512
  }

  environment {
    variables = {
      STORAGE_BACKEND     = "s3"
      MODELS_BUCKET       = aws_s3_bucket.models.bucket
      ROUNDS_TABLE        = aws_dynamodb_table.rounds.name
      AUDIT_TABLE         = aws_dynamodb_table.audit.name
      MODEL_CACHE_SECONDS = "60"
      AUDIT_ENABLED       = "true"
      CORS_ORIGINS        = "*"
      LOG_LEVEL           = "INFO"
    }
  }

  tags = { Name = "FedMed inference API" }
}

resource "aws_cloudwatch_log_group" "api" {
  count = var.create_lambda ? 1 : 0

  name              = "/aws/lambda/${var.project}-inference-api"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_api" "api" {
  count = var.create_lambda ? 1 : 0

  name          = "${var.project}-api"
  protocol_type = "HTTP"
  description   = "Public entry point for FedMed predictions and round history"

  # The dashboard is a static site on an S3 website endpoint, a different origin
  # from the API, so preflight has to be answered here as well as in FastAPI.
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["content-type"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_integration" "api" {
  count = var.create_lambda ? 1 : 0

  api_id                 = aws_apigatewayv2_api.api[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api[0].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

# One catch-all route. FastAPI already does the routing, so duplicating the path
# table in API Gateway would only create a second place to keep in sync.
resource "aws_apigatewayv2_route" "default" {
  count = var.create_lambda ? 1 : 0

  api_id    = aws_apigatewayv2_api.api[0].id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}

resource "aws_apigatewayv2_route" "root" {
  count = var.create_lambda ? 1 : 0

  api_id    = aws_apigatewayv2_api.api[0].id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}

resource "aws_apigatewayv2_stage" "default" {
  count = var.create_lambda ? 1 : 0

  api_id      = aws_apigatewayv2_api.api[0].id
  name        = "$default"
  auto_deploy = true

  # Access logs make it possible to show, during the demo, that a prediction
  # request carried no query string and therefore leaked nothing through the URL.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access[0].arn
    format = jsonencode({
      requestId      = "$context.requestId"
      httpMethod     = "$context.httpMethod"
      path           = "$context.path"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      latencyMs      = "$context.responseLatency"
    })
  }

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_cloudwatch_log_group" "api_access" {
  count = var.create_lambda ? 1 : 0

  name              = "/aws/apigateway/${var.project}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_permission" "api_gateway" {
  count = var.create_lambda ? 1 : 0

  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api[0].execution_arn}/*/*"
}
