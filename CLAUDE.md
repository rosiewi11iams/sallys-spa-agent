# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a serverless spa chatbot application that uses AWS Lambda, API Gateway, DynamoDB, and the Anthropic Claude API. The architecture implements a Model Context Protocol (MCP) pattern where business logic tools (service queries) are separated from the conversational AI handler.

## Architecture

**Two-Lambda Design:**
- `lambda-mcp/` - MCP Tools Lambda: Provides business logic tools (get services, search by price, categorize)
- `lambda-chat/` - Chat Handler Lambda: Orchestrates Claude API calls and invokes MCP Lambda for tool execution

**Key Pattern:** The chat handler formats MCP tools into Claude's tool format, processes tool_use responses from Claude, invokes the MCP Lambda to execute tools, and sends tool results back to Claude for natural language responses.

**Data Flow:**
1. User message → API Gateway → Chat Lambda
2. Chat Lambda retrieves conversation history from DynamoDB
3. Chat Lambda calls MCP Lambda to list available tools
4. Chat Lambda sends user message + tools to Claude API
5. If Claude requests tool use, Chat Lambda invokes MCP Lambda
6. MCP Lambda reads from S3 (services.json) and returns results
7. Chat Lambda sends tool results back to Claude
8. Final response saved to DynamoDB and returned to user

**Infrastructure:** Terraform provisions all AWS resources (S3, DynamoDB, Lambda functions, API Gateway, IAM roles)

## Build and Deploy

**Build Lambda packages:**
```bash
./build.sh
```
This creates zip files in `lambda-packages/` for both Lambda functions with all dependencies bundled.

**Deploy to AWS:**
```bash
cd terraform
terraform init
terraform plan
terraform apply
```

**Required variables:**
- Set `anthropic_api_key` in `terraform/terraform.tfvars`
- AWS credentials must be configured (via AWS CLI or environment variables)

**Output:** After deployment, Terraform outputs the API endpoint URL and a test curl command.

## Configuration

**Environment Variables (set by Terraform):**
- Chat Lambda: `ANTHROPIC_API_KEY`, `MCP_LAMBDA_NAME`, `CONVERSATIONS_TABLE`
- MCP Lambda: `BUCKET_NAME`

**Services Data:** Edit `services.json` to modify spa services. After editing, run `terraform apply` to upload changes to S3.

## Development

**Testing MCP tools locally:**
You can test tool functions in `lambda-mcp/lambda_function.py` by importing and calling them directly in a Python REPL after mocking S3 client.

**Modifying conversation behavior:**
Edit the system prompt in `lambda-chat/lambda_function.py` (lines 114-123) to change the chatbot's personality or instructions.

**Adding new tools:**
1. Add function to `lambda-mcp/lambda_function.py`
2. Register in `TOOLS` dictionary with name, description, and parameters
3. Rebuild and redeploy both Lambdas

**Python version:** Lambda functions use Python 3.11 runtime.

## Key Files

- `services.json` - Spa services catalog (uploaded to S3)
- `build.sh` - Builds both Lambda deployment packages
- `lambda-chat/lambda_function.py` - Main chat orchestration with Claude API
- `lambda-mcp/lambda_function.py` - Business logic tools and service queries
- `terraform/main.tf` - Complete infrastructure as code

## AWS Resources Created

- S3 bucket: `spa-services-{random}` (stores services.json)
- DynamoDB table: `spa-conversations` (conversation history)
- Lambda functions: `spa-mcp-tools`, `spa-chat-handler`
- API Gateway HTTP API with POST /chat endpoint
- IAM role with policies for Lambda execution, S3 access, DynamoDB access, and cross-Lambda invocation
