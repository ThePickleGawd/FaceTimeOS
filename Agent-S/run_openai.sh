#!/usr/bin/env bash

: "${OPENAI_API_KEY:?OPENAI_API_KEY environment variable must be set}"

agent_s --provider openai \
    --model gpt-5 \
    --ground_provider openai \
    --ground_url https://api.openai.com/v1/ \
    --ground_model gpt-5 \
    --ground_api_key "${OPENAI_API_KEY}" \
    --grounding_width 1920 \
    --grounding_height 1080 \
    --model_temperature 1.0 \
    #--enable_local_env