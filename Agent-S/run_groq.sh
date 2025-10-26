#!/usr/bin/env bash

: "${GROQ_API_KEY:?GROQ_API_KEY environment variable must be set}"

source .env
uv run -m src.s3.app \
  --provider openai \
  --model "llama-3.1-8b-instant" \
  --model_url "https://api.groq.com/openai/v1/" \
  --model_api_key "${GROQ_API_KEY}" \
  --ground_provider openai \
  --ground_model "llama-3.1-8b-instant" \
  --ground_url "https://api.groq.com/openai/v1/" \
  --ground_api_key "${GROQ_API_KEY}" \
  --grounding_width 1920 \
  --grounding_height 1080 \
  --model_temperature 1.0 \
  --asi_one_api_key "$ASI_ONE_API_KEY"
