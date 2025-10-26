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
# ./run_demo_fast.sh &
# ./run_demo_best.sh &
./run_grok.sh &
cd ..

# Start frontend
cd frontend
npm start &
cd ..

# Wait for everything
wait
