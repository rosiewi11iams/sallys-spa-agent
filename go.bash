#!/bin/bash

source .venv/bin/activate
aws dynamodb delete-item --table-name spa-conversations --key '{"session_id": {"S": "local-test"}}'
python3 test.py
