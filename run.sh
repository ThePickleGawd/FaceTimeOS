# Kill all background jobs on script exit
trap 'kill $(jobs -p) 2>/dev/null' EXIT

# Start backend server
cd backend
uv run main.py &
uv run imessage_bridge.py &
uv run call.py &
cd ..

# Start Agent S
cd Agent-S
./run_grok.sh &
cd ..

# Start frontend UI
cd frontend
npm start &
cd ..

wait  # wait for background jobs (so trap works)
