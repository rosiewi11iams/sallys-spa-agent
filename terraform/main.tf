terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Random suffix for unique naming
resource "random_id" "suffix" {
  byte_length = 4
}

# S3 Bucket for services data
resource "aws_s3_bucket" "spa_data" {
  bucket = "spa-services-${random_id.suffix.hex}"
}

# Upload services.json
resource "aws_s3_object" "services" {
  bucket = aws_s3_bucket.spa_data.id
  key    = "services.json"
  source = "../services.json"
  etag   = filemd5("../services.json")
}

# DynamoDB for conversation history
resource "aws_dynamodb_table" "conversations" {
  name           = "spa-conversations"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "spa-lambda-role-${random_id.suffix.hex}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "lambda_policy" {
  name = "spa-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.spa_data.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.conversations.arn
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = "*"
      }
    ]
  })
}

# MCP Lambda Function
resource "aws_lambda_function" "mcp_tools" {
  filename      = "../lambda-packages/mcp-lambda.zip"
  function_name = "spa-mcp-tools"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 256

  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.spa_data.id
    }
  }

  source_code_hash = filebase64sha256("../lambda-packages/mcp-lambda.zip")
}

# Chat Lambda Function
resource "aws_lambda_function" "chat_handler" {
  filename      = "../lambda-packages/chat-lambda.zip"
  function_name = "spa-chat-handler"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 60
  memory_size   = 512

  environment {
    variables = {
      ANTHROPIC_API_KEY   = var.anthropic_api_key
      MCP_LAMBDA_NAME     = aws_lambda_function.mcp_tools.function_name
      CONVERSATIONS_TABLE = aws_dynamodb_table.conversations.name
    }
  }

  source_code_hash = filebase64sha256("../lambda-packages/chat-lambda.zip")
}

# API Gateway
resource "aws_apigatewayv2_api" "spa_api" {
  name          = "spa-chat-api"
  protocol_type = "HTTP"
  
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["POST", "OPTIONS"]
    allow_headers = ["content-type"]
  }
}

# Integration with Chat Lambda
resource "aws_apigatewayv2_integration" "chat_integration" {
  api_id             = aws_apigatewayv2_api.spa_api.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.chat_handler.invoke_arn
  payload_format_version = "2.0"
}

# Route for chat
resource "aws_apigatewayv2_route" "chat_route" {
  api_id    = aws_apigatewayv2_api.spa_api.id
  route_key = "POST /chat"
  target    = "integrations/${aws_apigatewayv2_integration.chat_integration.id}"
}

# Default stage
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.spa_api.id
  name        = "$default"
  auto_deploy = true
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "api_gateway_chat" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.chat_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.spa_api.execution_arn}/*/*"
}

# Outputs
output "api_endpoint" {
  value = "${aws_apigatewayv2_api.spa_api.api_endpoint}/chat"
  description = "Chat API endpoint"
}

output "s3_bucket" {
  value = aws_s3_bucket.spa_data.id
}

output "test_curl_command" {
  value = <<EOT
curl -X POST ${aws_apigatewayv2_api.spa_api.api_endpoint}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What services do you have?", "session_id": "test-123"}'
EOT
}
