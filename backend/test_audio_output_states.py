#!/usr/bin/env python3
"""Test script to verify audio output works in both recording states."""

import base64
import logging
import os
import sys
import time
from pathlib import Path
from threading import Event

import requests
import socketio
from dotenv import load_dotenv

# Load environment variables
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=DOTENV_PATH)

# Call service configuration
CALL_SERVICE_HOST = os.getenv("CALL_SERVICE_HOST", "127.0.0.1")
CALL_SERVICE_PORT = int(os.getenv("CALL_SERVICE_PORT", "5002"))
BASE_URL = f"http://{CALL_SERVICE_HOST}:{CALL_SERVICE_PORT}"

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Suppress socketio logs
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)


def send_audio(audio_file: Path) -> dict:
    """Send audio file to call service and return response."""
    from pydub import AudioSegment
    
    # Load and convert audio
    audio = AudioSegment.from_file(str(audio_file))
    audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
    audio_bytes = audio.raw_data
    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
    
    # Send to call service
    response = requests.post(
        f"{BASE_URL}/audio_input",
        json={'audio': audio_b64},
        headers={'Content-Type': 'application/json'},
        timeout=30
    )
    return response.json()


class RecordingController:
    """Control recording state via socketio."""
    
    def __init__(self, url: str):
        self.url = url
        self.sio = socketio.Client()
        self.connected = Event()
        self.recording_started = Event()
        self.recording_stopped = Event()
        
        @self.sio.on('connect')
        def on_connect():
            logger.debug("WebSocket connected")
            self.connected.set()
        
        @self.sio.on('connected')
        def on_connected(data):
            logger.debug(f"Received connected event: {data}")
        
        @self.sio.on('recording_started')
        def on_recording_started(data):
            logger.debug(f"Recording started: {data}")
            self.recording_started.set()
        
        @self.sio.on('recording_stopped')
        def on_recording_stopped(data):
            logger.debug(f"Recording stopped: {data}")
            self.recording_stopped.set()
        
        @self.sio.on('disconnect')
        def on_disconnect():
            logger.debug("WebSocket disconnected")
    
    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to the call service."""
        try:
            self.sio.connect(self.url)
            if self.connected.wait(timeout):
                return True
            logger.error("Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def start_recording(self, timeout: float = 2.0) -> bool:
        """Start recording."""
        self.recording_started.clear()
        self.sio.emit('start_recording', {})
        return self.recording_started.wait(timeout)
    
    def stop_recording(self, timeout: float = 2.0) -> bool:
        """Stop recording."""
        self.recording_stopped.clear()
        self.sio.emit('stop_recording', {})
        return self.recording_stopped.wait(timeout)
    
    def disconnect(self):
        """Disconnect from the call service."""
        if self.sio.connected:
            self.sio.disconnect()


def main():
    """Test audio output in both recording states."""
    audio_file = Path(__file__).parent / "chimes.mp3"
    
    if not audio_file.exists():
        logger.error(f"Test audio file not found: {audio_file}")
        logger.info("Please ensure chimes.mp3 exists in the backend directory")
        return
    
    logger.info("=" * 60)
    logger.info("Testing Audio Output in Different Recording States")
    logger.info("=" * 60)
    
    test1_passed = False
    test2_passed = False
    
    # Test 1: Audio output when NOT recording
    logger.info("\n📢 TEST 1: Audio output when NOT recording")
    logger.info("Expected device: MacBook Pro Speakers (AUDIO_OUTPUT_DEVICE1)")
    logger.info("-" * 60)
    
    try:
        result = send_audio(audio_file)
        logger.info(f"Response: {result}")
        logger.info(f"Recording state: {result.get('recording', 'unknown')}")
        
        if result.get('recording') == False:
            logger.info("✅ PASS: Audio sent while NOT recording")
            test1_passed = True
        else:
            logger.warning("⚠️  Unexpected: recording state is not False")
        
    except Exception as e:
        logger.error(f"❌ FAIL: {e}")
    
    time.sleep(2)
    
    # Test 2: Audio output when recording
    logger.info("\n📢 TEST 2: Audio output when recording")
    logger.info("Expected device: BlackHole 2ch (AUDIO_OUTPUT_DEVICE2)")
    logger.info("-" * 60)
    
    controller = RecordingController(BASE_URL)
    
    try:
        # Connect to call service
        logger.info("Connecting to call service via WebSocket...")
        if not controller.connect():
            logger.error("❌ FAIL: Could not connect to call service")
            logger.error("Make sure the call service is running: python backend/call.py")
            logger.info("\n" + "=" * 60)
            logger.info("📋 Summary")
            logger.info("=" * 60)
            logger.info(f"✅ Test 1 (NOT recording): {'PASSED' if test1_passed else 'FAILED'}")
            logger.info("❌ Test 2 (recording): FAILED - Could not connect")
            return
        
        logger.info("✅ Connected to call service")
        
        # Start recording
        logger.info("Starting recording...")
        if not controller.start_recording():
            logger.error("❌ FAIL: Could not start recording")
            controller.disconnect()
            return
        
        logger.info("✅ Recording started")
        time.sleep(0.5)  # Give it a moment to stabilize
        
        # Send audio while recording
        logger.info("Sending audio while recording is active...")
        result = send_audio(audio_file)
        logger.info(f"Response: {result}")
        logger.info(f"Recording state: {result.get('recording', 'unknown')}")
        
        if result.get('recording') == True:
            logger.info("✅ PASS: Audio sent while recording is active")
            test2_passed = True
        else:
            logger.warning("⚠️  Unexpected: recording state is not True")
        
        # Stop recording
        time.sleep(1)
        logger.info("Stopping recording...")
        if controller.stop_recording():
            logger.info("✅ Recording stopped")
        
        # Disconnect
        controller.disconnect()
        
    except Exception as e:
        logger.error(f"❌ FAIL: {e}")
        controller.disconnect()
    
    logger.info("\n" + "=" * 60)
    logger.info("📋 Summary")
    logger.info("=" * 60)
    logger.info(f"Test 1 (NOT recording): {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    logger.info(f"Test 2 (recording):     {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    logger.info("\nCheck the call.py service logs for device selection details:")
    logger.info("  - 'Output device selection: recording=<True/False>'")
    logger.info("  - 'device_name=<device name>'")


if __name__ == "__main__":
    main()
