# load GROK_API_KEY into the shell
source .env
uv run -m src.s3.app \
  --provider openai \
  --model "grok-4-fast-non-reasoning" \
  --model_url "https://api.x.ai/v1/" \
  --model_api_key "$GROK_API_KEY" \
  --ground_provider openai \
  --ground_model "grok-4-fast-non-reasoning" \
  --ground_url "https://api.x.ai/v1/" \
  --ground_api_key "$GROK_API_KEY" \