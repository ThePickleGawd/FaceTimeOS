#!/usr/bin/env bash

source .env
uv run -m src.s3.app \
  --provider openai \
  --model gpt-5 \
  --ground_provider huggingface \
  --ground_url https://umd80oz2cvp7m0p8.us-east-1.aws.endpoints.huggingface.cloud/v1/ \
  --ground_model ui-tars-1.5-7b \
  --grounding_width 1920 \
  --grounding_height 1080 \
  --model_temperature 1.0 \
  #--enable_local_env
