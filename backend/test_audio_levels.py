#!/usr/bin/env python3
"""Quick test script to verify audio level monitoring is working."""

import socketio
import time

# Create a Socket.IO client
sio = socketio.Client()

# Track if we've received any audio level events
input_levels_received = 0
output_levels_received = 0

@sio.event
def connect():
    print("✅ Connected to audio server")
    print("Requesting to start recording...")
    sio.emit('start_recording')

@sio.event
def disconnect():
    print("❌ Disconnected from audio server")

@sio.on('connected')
def on_connected(data):
    print(f"Server says: {data}")

@sio.on('recording_started')
def on_recording_started(data):
    print("✅ Recording started successfully")
    print("Listening for audio level events...")
    print("(You should see input_audio_level events below if DEBUG_AUDIO_LEVELS=true)")

@sio.on('recording_error')
def on_recording_error(data):
    print(f"❌ Recording error: {data}")

@sio.on('input_audio_level')
def on_input_level(data):
    global input_levels_received
    input_levels_received += 1
    level_db = data.get('level_db', 'N/A')
    energy = data.get('energy', 'N/A')
    is_speaking = data.get('is_speaking', False)
    
    if input_levels_received <= 5 or input_levels_received % 10 == 0:
        status = "🔊 SPEAKING" if is_speaking else "🔇 Silent"
        print(f"📥 Input Level #{input_levels_received}: {level_db} dB | Energy: {energy} | {status}")

@sio.on('output_audio_level')
def on_output_level(data):
    global output_levels_received
    output_levels_received += 1
    level_db = data.get('level_db', 'N/A')
    
    if output_levels_received <= 5 or output_levels_received % 10 == 0:
        print(f"📤 Output Level #{output_levels_received}: {level_db} dB")

if __name__ == '__main__':
    server_url = 'http://localhost:5002'
    
    print("=" * 60)
    print("Audio Level Monitoring Test")
    print("=" * 60)
    print(f"Connecting to: {server_url}")
    print()
    
    try:
        sio.connect(server_url)
        
        # Run for 15 seconds
        print("Running test for 15 seconds...")
        time.sleep(15)
        
        print()
        print("=" * 60)
        print("Test Results:")
        print("=" * 60)
        print(f"Input audio levels received: {input_levels_received}")
        print(f"Output audio levels received: {output_levels_received}")
        print()
        
        if input_levels_received > 0:
            print("✅ SUCCESS: Input audio level monitoring is working!")
        else:
            print("❌ PROBLEM: No input audio levels received")
            print()
            print("Troubleshooting:")
            print("1. Make sure DEBUG_AUDIO_LEVELS=true in your .env file")
            print("2. Restart the audio server (backend/call.py)")
            print("3. Check server logs for 'Audio level debugging: ENABLED'")
            print("4. Make sure recording actually started (check for 'Recording started successfully')")
        
        print()
        print("Stopping recording and disconnecting...")
        sio.emit('stop_recording')
        time.sleep(1)
        sio.disconnect()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("Make sure the audio server is running:")
        print("  cd backend && python call.py")
