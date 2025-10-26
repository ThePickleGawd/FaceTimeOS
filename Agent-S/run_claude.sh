#!/usr/bin/env bash

# // llm: {
# //     provider: 'anthropic',
# //     options: {
# //         model: 'claude-sonnet-4-20250514',
# //         apiKey: process.env.ANTHROPIC_API_KEY
# //     }
# // },

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY environment variable must be set}"
source .env
uv run -m src.s3.app \
    --provider anthropic \
    --model claude-sonnet-4-20250514 \
    --ground_provider anthropic \
    --ground_url https://api.anthropic.com \
    --ground_model claude-sonnet-4-20250514 \
    --ground_api_key "${ANTHROPIC_API_KEY}" \
    --grounding_width 1920 \
    --grounding_height 1080 \
    --model_temperature 1.0 \
    #--enable_local_env
