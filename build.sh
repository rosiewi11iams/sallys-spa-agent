#!/bin/bash

echo "Building Lambda packages..."

# Create packages directory
mkdir -p lambda-packages

# Build MCP Lambda
echo "Building MCP Lambda..."
cd lambda-mcp
pip3 install -r requirements.txt -t . \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  --upgrade
zip -r ../lambda-packages/mcp-lambda.zip . -x "*.pyc" "__pycache__/*" "*.dist-info/*"
cd ..

# Build Chat Lambda
echo "Building Chat Lambda..."
cd lambda-chat
pip3 install -r requirements.txt -t . \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  --upgrade
zip -r ../lambda-packages/chat-lambda.zip . -x "*.pyc" "__pycache__/*" "*.dist-info/*"
cd ..

# Build Voice Lambda
echo "Building Voice Lambda..."
cd lambda-voice
pip3 install -r requirements.txt -t . \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  --upgrade
zip -r ../lambda-packages/voice-lambda.zip . -x "*.pyc" "__pycache__/*" "*.dist-info/*"
cd ..

echo "Build complete!"
