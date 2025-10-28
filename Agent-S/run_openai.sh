source .env
uv run -m src.s3.app \
    --provider openai \
    --model gpt-5-nano \
    --model_url https://api.openai.com/v1/ \
    --model_api_key "$OPENAI_API_KEY" \
    --ground_provider openai \
    --ground_url https://api.openai.com/v1/ \
    --ground_model gpt-5-nano \
    --ground_api_key "$OPENAI_API_KEY" \
    --model_temperature 1.0 \
    #--enable_local_env
