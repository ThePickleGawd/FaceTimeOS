#!/bin/bash
set -e

# Kill all background jobs on exit or Ctrl+C
trap 'kill 0' EXIT INT

# Start backend services
cd backend
uv run main.py &
uv run imessage_bridge.py &
uv run call.py &
cd ..

# Start Agent S
cd Agent-S
# ./run_demo_fast.sh & # What we used in demo video. Needs UI-TARS on Hugging Face
# ./run_demo_best.sh & # Agent S3 settings. Needs UI-TARS on Hugging Face
./run_grok.sh & # Fastest option (recommended)
# ./run_openai.sh & # Likely most widely available option
cd ..

# Start frontend
cd frontend
npm start &
cd ..

# Wait for everything
wait
