#!/usr/bin/env python3
"""Test script for VAD-based FaceTime call integration."""

import base64
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import requests
import socketio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_test_audio(duration_seconds=2, frequency=440):
    """Generate a test tone for testing audio playback."""
    sample_rate = 48000
    channels = 2
    
    # Generate a sine wave
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
    audio = np.sin(2 * np.pi * frequency * t) * 0.3  # 30% volume
    
    # Convert to int16
    audio_int16 = (audio * 32767).astype(np.int16)
    
    # Make stereo
    stereo_audio = np.column_stack((audio_int16, audio_int16))
    
    return stereo_audio.tobytes()


class CallServiceTester:
    """Test client for the call service."""
    
    def __init__(self, main_url="http://localhost:8003", call_url="http://localhost:5002"):
        self.main_url = main_url
        self.call_url = call_url
        self.sio = socketio.Client()
        self.setup_handlers()
        
    def setup_handlers(self):
        """Setup socket.io event handlers."""
        
        @self.sio.on('connect')
        def on_connect():
            logger.info("Connected to call service")
            
        @self.sio.on('disconnect')
        def on_disconnect():
            logger.info("Disconnected from call service")
            
        @self.sio.on('user_utterance')
        def on_utterance(data):
            duration = data.get('duration', 0)
            audio_b64 = data.get('audio', '')
            audio_size = len(base64.b64decode(audio_b64)) if audio_b64 else 0
            logger.info(f"Received utterance: {audio_size} bytes, {duration:.2f}s duration")
            
        @self.sio.on('playback_interrupted')
        def on_interrupted(data):
            logger.info("Playback was interrupted by user speech")
            
        @self.sio.on('recording_started')
        def on_recording_started(data):
            logger.info("Recording started")
            
        @self.sio.on('recording_stopped')
        def on_recording_stopped(data):
            logger.info("Recording stopped")
    
    def test_call_lifecycle(self):
        """Test starting and ending a call."""
        logger.info("\n=== Testing Call Lifecycle ===")
        
        # Check initial status
        response = requests.get(f"{self.main_url}/api/call_status")
        status = response.json()
        logger.info(f"Initial status: {status}")
        
        # Start a call
        logger.info("Starting call...")
        response = requests.post(
            f"{self.main_url}/api/call_started",
            json={"caller": "test_user", "call_id": "test_123"}
        )
        result = response.json()
        logger.info(f"Call start result: {result}")
        
        # Check status again
        response = requests.get(f"{self.main_url}/api/call_status")
        status = response.json()
        logger.info(f"Status after start: {status}")
        
        # Wait a bit
        time.sleep(2)
        
        # End the call
        logger.info("Ending call...")
        response = requests.post(
            f"{self.main_url}/api/call_ended",
            json={"call_id": "test_123"}
        )
        result = response.json()
        logger.info(f"Call end result: {result}")
        
        # Final status
        response = requests.get(f"{self.main_url}/api/call_status")
        status = response.json()
        logger.info(f"Final status: {status}")
    
    def test_direct_websocket(self):
        """Test direct WebSocket connection to call.py."""
        logger.info("\n=== Testing Direct WebSocket Connection ===")
        
        try:
            # Connect to call service
            logger.info(f"Connecting to {self.call_url}...")
            self.sio.connect(self.call_url)
            
            # Start recording
            logger.info("Starting recording via WebSocket...")
            self.sio.emit('start_recording')
            time.sleep(1)
            
            # Send test audio
            logger.info("Sending test audio...")
            test_audio = generate_test_audio(duration_seconds=1, frequency=440)
            audio_b64 = base64.b64encode(test_audio).decode('utf-8')
            self.sio.emit('audio_input', {'audio': audio_b64})
            
            # Wait for playback
            logger.info("Waiting for playback...")
            time.sleep(2)
            
            # Send another tone
            logger.info("Sending second test tone...")
            test_audio = generate_test_audio(duration_seconds=1, frequency=880)
            audio_b64 = base64.b64encode(test_audio).decode('utf-8')
            self.sio.emit('audio_input', {'audio': audio_b64})
            
            time.sleep(2)
            
            # Stop recording
            logger.info("Stopping recording...")
            self.sio.emit('stop_recording')
            time.sleep(1)
            
            # Disconnect
            logger.info("Disconnecting...")
            self.sio.disconnect()
            
        except Exception as e:
            logger.error(f"WebSocket test failed: {e}")
    
    def test_audio_through_main(self):
        """Test sending audio through main.py."""
        logger.info("\n=== Testing Audio Through Main Service ===")
        
        # First start a call
        response = requests.post(
            f"{self.main_url}/api/call_started",
            json={"caller": "audio_test", "call_id": "audio_123"}
        )
        
        if response.status_code != 200:
            logger.error("Failed to start call")
            return
        
        logger.info("Call started successfully")
        
        # Generate test audio
        test_audio = generate_test_audio(duration_seconds=2, frequency=660)
        audio_b64 = base64.b64encode(test_audio).decode('utf-8')
        
        # Send audio through main.py
        logger.info("Sending audio to main.py...")
        response = requests.post(
            f"{self.main_url}/api/send_audio_to_call",
            json={"audio": audio_b64}
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Audio sent successfully: {result}")
        else:
            logger.error(f"Failed to send audio: {response.status_code} - {response.text}")
        
        # Wait for playback
        time.sleep(3)
        
        # End call
        response = requests.post(
            f"{self.main_url}/api/call_ended",
            json={"call_id": "audio_123"}
        )
        logger.info("Call ended")
    
    def run_all_tests(self):
        """Run all tests."""
        logger.info("Starting VAD Integration Tests")
        logger.info("=" * 50)
        
        # Test 1: Call lifecycle
        self.test_call_lifecycle()
        time.sleep(2)
        
        # Test 2: Direct WebSocket
        self.test_direct_websocket()
        time.sleep(2)
        
        # Test 3: Audio through main
        self.test_audio_through_main()
        
        logger.info("\n" + "=" * 50)
        logger.info("Tests completed!")


def main():
    """Main test function."""
    # Check if services are running
    try:
        response = requests.get("http://localhost:8003/api/call_status", timeout=2)
        logger.info("Main service is running")
    except:
        logger.error("Main service (port 8003) is not running. Please start it first.")
        sys.exit(1)
    
    try:
        response = requests.get("http://localhost:5002/devices", timeout=2)
        logger.info("Call service is running")
    except:
        logger.error("Call service (port 5002) is not running. Please start it first.")
        sys.exit(1)
    
    # Run tests
    tester = CallServiceTester()
    tester.run_all_tests()


if __name__ == "__main__":
    main()
