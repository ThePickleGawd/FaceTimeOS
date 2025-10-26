"""Flask server for audio recording and streaming."""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# Load environment variables
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=DOTENV_PATH)

logger = logging.getLogger(__name__)

# Audio configuration
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2
CHUNK_SIZE = 1024

# Optional: Specify device names from environment
# For system audio capture, use something like "BlackHole 2ch"
INPUT_DEVICE_NAME = os.getenv("AUDIO_INPUT_DEVICE", None)
OUTPUT_DEVICE_NAME = os.getenv("AUDIO_OUTPUT_DEVICE", None)


class AudioManager:
    """Manages audio recording and playback."""

    def __init__(self, input_device: Optional[str] = None, output_device: Optional[str] = None):
        self.recording = False
        self.recording_thread: Optional[threading.Thread] = None
        self.socketio: Optional[SocketIO] = None
        self.audio_chunks_sent = 0
        self.input_device_index = self._find_device(input_device, "input") if input_device else None
        self.output_device_index = self._find_device(output_device, "output") if output_device else None
        
        logger.info(f"AudioManager initialized")
        logger.info(f"Sample rate: {DEFAULT_SAMPLE_RATE}Hz, Channels: {DEFAULT_CHANNELS}, Chunk size: {CHUNK_SIZE}")
        
        if input_device:
            if self.input_device_index is not None:
                device_info = sd.query_devices(self.input_device_index)
                logger.info(f"Input device: {input_device} (index {self.input_device_index})")
                logger.info(f"  - Channels: {device_info['max_input_channels']}, Sample rate: {device_info['default_samplerate']}Hz")
            else:
                logger.warning(f"Input device '{input_device}' not found, using system default")
        else:
            default_input = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
            if default_input is not None:
                device_info = sd.query_devices(default_input)
                logger.info(f"Using system default input: {device_info['name']} (index {default_input})")
        
        if output_device:
            if self.output_device_index is not None:
                device_info = sd.query_devices(self.output_device_index)
                logger.info(f"Output device: {output_device} (index {self.output_device_index})")
                logger.info(f"  - Channels: {device_info['max_output_channels']}, Sample rate: {device_info['default_samplerate']}Hz")
            else:
                logger.warning(f"Output device '{output_device}' not found, using system default")
        else:
            default_output = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
            if default_output is not None:
                device_info = sd.query_devices(default_output)
                logger.info(f"Using system default output: {device_info['name']} (index {default_output})")
    
    def _find_device(self, device_name: str, device_type: str) -> Optional[int]:
        """Find device index by name."""
        logger.debug(f"Searching for {device_type} device: {device_name}")
        devices = sd.query_devices()
        for idx, device in enumerate(devices):
            if device_name.lower() in device["name"].lower():
                if device_type == "input" and device["max_input_channels"] > 0:
                    logger.debug(f"Found {device_type} device '{device['name']}' at index {idx}")
                    return idx
                elif device_type == "output" and device["max_output_channels"] > 0:
                    logger.debug(f"Found {device_type} device '{device['name']}' at index {idx}")
                    return idx
        logger.debug(f"{device_type.capitalize()} device '{device_name}' not found")
        return None

    def _recording_worker(self):
        """Worker thread for continuous audio recording."""
        logger.info("Recording worker thread started")
        try:
            with sd.InputStream(
                samplerate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=self.input_device_index,
                callback=self._audio_callback
            ) as stream:
                logger.info(f"Audio stream opened: active={stream.active}, channels={stream.channels}")
                while self.recording:
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Recording error: {e}", exc_info=True)
        finally:
            self.recording = False
            logger.info(f"Recording worker stopped. Total chunks sent: {self.audio_chunks_sent}")

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for audio input stream."""
        if status:
            logger.warning(f"Audio callback status: {status}")
        
        # Convert audio to bytes
        audio_bytes = indata.astype(np.int16).tobytes()
        
        # Emit via websocket if connected
        if self.socketio:
            # Encode as base64 for websocket transmission
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            self.socketio.emit('audio_stream', {'audio': audio_b64}, namespace='/')
            self.audio_chunks_sent += 1
            if self.audio_chunks_sent % 100 == 0:
                logger.debug(f"Sent {self.audio_chunks_sent} audio chunks ({len(audio_bytes)} bytes/chunk)")

    def start_recording(self) -> bool:
        """Start recording from the configured input device."""
        if self.recording:
            logger.warning("Recording already in progress")
            return False
        
        self.audio_chunks_sent = 0
        self.recording = True
        self.recording_thread = threading.Thread(target=self._recording_worker, daemon=True)
        self.recording_thread.start()
        logger.info(f"Started recording from device index {self.input_device_index}")
        return True

    def stop_recording(self) -> bool:
        """Stop recording."""
        if not self.recording:
            logger.warning("Not currently recording")
            return False
        
        logger.info("Stopping recording...")
        self.recording = False
        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
            if self.recording_thread.is_alive():
                logger.warning("Recording thread did not stop cleanly")
        
        logger.info(f"Recording stopped. Total chunks sent: {self.audio_chunks_sent}")
        return True

    def output_audio(self, audio_bytes: bytes):
        """Output audio bytes through the configured output device."""
        try:
            logger.debug(f"Outputting audio: {len(audio_bytes)} bytes")
            # Convert bytes to numpy array (int16 samples)
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Reshape interleaved stereo data to (N, 2) for sounddevice
            if DEFAULT_CHANNELS == 2:
                audio_array = audio_array.reshape(-1, 2)
            elif DEFAULT_CHANNELS == 1:
                # Keep as 1D for mono
                pass
            
            logger.debug(f"Playing audio array: shape={audio_array.shape}, device={self.output_device_index}")
            # Play audio using the configured output device
            sd.play(audio_array, samplerate=DEFAULT_SAMPLE_RATE, device=self.output_device_index)
            sd.wait()
            
            logger.info(f"Audio playback completed: {len(audio_bytes)} bytes")
            
        except Exception as e:
            logger.error(f"Error outputting audio: {e}", exc_info=True)


# Initialize Flask app and extensions
app = Flask(__name__)
CORS(app)
# Increase max message size to 10MB to handle large audio files
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10_000_000)

# Initialize audio manager
audio_manager = AudioManager(input_device=INPUT_DEVICE_NAME, output_device=OUTPUT_DEVICE_NAME)
audio_manager.socketio = socketio

logger.info(f"Audio manager configured: input={INPUT_DEVICE_NAME}, output={OUTPUT_DEVICE_NAME}")


@app.route('/devices', methods=['GET'])
def list_devices():
    """List available audio devices."""
    devices = sd.query_devices()
    device_list = []
    for idx, device in enumerate(devices):
        device_list.append({
            "index": idx,
            "name": device["name"],
            "input_channels": device["max_input_channels"],
            "output_channels": device["max_output_channels"],
            "default_samplerate": device["default_samplerate"]
        })
    return jsonify({"devices": device_list}), 200


@socketio.on('connect')
def handle_connect():
    """Handle websocket connection."""
    from flask import request
    logger.info(f"Client connected from {request.sid}")
    emit('connected', {'status': 'Connected to audio server'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle websocket disconnection."""
    from flask import request
    logger.info(f"Client disconnected: {request.sid}")
    # Auto-stop recording if client disconnects
    if audio_manager.recording:
        logger.info("Auto-stopping recording due to client disconnect")
        audio_manager.stop_recording()


@socketio.on('start_recording')
def handle_start_recording(_data=None):
    """Start audio recording via websocket."""
    from flask import request
    logger.info(f"Start recording requested by {request.sid}")
    success = audio_manager.start_recording()
    if success:
        logger.info("Recording started successfully")
        emit('recording_started', {'status': 'recording_started'})
    else:
        logger.error("Failed to start recording")
        emit('recording_error', {'message': 'Failed to start recording or already recording'})


@socketio.on('stop_recording')
def handle_stop_recording(_data=None):
    """Stop audio recording via websocket."""
    from flask import request
    logger.info(f"Stop recording requested by {request.sid}")
    success = audio_manager.stop_recording()
    if success:
        logger.info("Recording stopped successfully")
        emit('recording_stopped', {'status': 'recording_stopped'})
    else:
        logger.error("Failed to stop recording - not currently recording")
        emit('recording_error', {'message': 'Not currently recording'})


@socketio.on('*')
def catch_all(event, data):
    """Catch all events for debugging."""
    from flask import request
    logger.info(f"Event received: '{event}' from {request.sid}")

@socketio.on('audio_input')
def handle_audio_input(data):
    """Handle incoming audio data to be output through the server."""
    from flask import request
    logger.info(f"Audio input event received from {request.sid}")
    try:
        # Decode base64 audio
        audio_b64 = data.get('audio') if data else None
        if not audio_b64:
            logger.warning(f"No audio data received from {request.sid}")
            emit('error', {'message': 'No audio data received'})
            return
        
        audio_bytes = base64.b64decode(audio_b64)
        logger.info(f"Received audio input from {request.sid}: {len(audio_bytes)} bytes")

        # Output audio using current defaults in a separate thread to avoid blocking
        threading.Thread(target=audio_manager.output_audio, args=(audio_bytes,), daemon=True).start()
        
        emit('audio_received', {'status': 'Audio received and queued for output'})
        
    except Exception as e:
        logger.error(f"Error handling audio input: {e}", exc_info=True)
        emit('error', {'message': f'Error processing audio: {str(e)}'})


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Suppress werkzeug polling logs
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    host = os.getenv("CALL_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("CALL_SERVICE_PORT", "5002"))
    
    logger.info(f"Starting audio call server on {host}:{port}")
    logger.info(f"Available audio devices:")
    devices = sd.query_devices()
    for idx, device in enumerate(devices):
        if device['max_input_channels'] > 0 or device['max_output_channels'] > 0:
            logger.info(f"  [{idx}] {device['name']}: in={device['max_input_channels']}, out={device['max_output_channels']}")
    
    logger.info("SocketIO server initialized with max message size: 10MB")

    socketio.run(app, host=host, port=port, debug=True, log_output=False)
