#!/usr/bin/env bash
source .env
uv run -m src.s3.app \
  --provider openai \
  --model "grok-4-fast-non-reasoning" \
  --model_url "https://api.x.ai/v1/" \
  --model_api_key "$GROK_API_KEY" \
  --ground_provider huggingface \
  --ground_url https://umd80oz2cvp7m0p8.us-east-1.aws.endpoints.huggingface.cloud/v1/ \
  --ground_model ui-tars-1.5-7b \
  --grounding_width 1920 \
  --grounding_height 1080 \
  --model_temperature 1.0 \
  --asi_one_api_key "$ASI_ONE_API_KEY"
  #--enable_local_env
