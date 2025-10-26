"""Flask server for audio recording and streaming with VAD and interruption handling."""
from __future__ import annotations

import base64
import logging
import os
import queue
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

# Voice Activity Detection (VAD) configuration
# Energy is normalized RMS (0.0 to 1.0 scale after dividing by 32768)
# Typical values: silence < 0.005, speech 0.01-0.05, loud 0.05+
VAD_ENERGY_THRESHOLD = 0.01  # Energy threshold for voice detection (normalized scale)
VAD_MIN_SPEECH_DURATION = 0.3  # Minimum speech duration in seconds
VAD_MAX_SILENCE_DURATION = 1.5  # Maximum silence before ending utterance
VAD_BUFFER_DURATION = 0.1  # Pre-buffer duration to capture speech onset

# Optional: Specify device names from environment
# For system audio capture, use something like "BlackHole 2ch"
INPUT_DEVICE_NAME = os.getenv("AUDIO_INPUT_DEVICE", None)
OUTPUT_DEVICE_NAME1 = os.getenv("AUDIO_OUTPUT_DEVICE1", None)
OUTPUT_DEVICE_NAME2 = os.getenv("AUDIO_OUTPUT_DEVICE2", None)

# Debug configuration
DEBUG_AUDIO_LEVELS = os.getenv("DEBUG_AUDIO_LEVELS", "false").lower() == "true"
print(f"[STARTUP] DEBUG_AUDIO_LEVELS environment variable: {os.getenv('DEBUG_AUDIO_LEVELS', 'NOT SET')}")
print(f"[STARTUP] DEBUG_AUDIO_LEVELS resolved to: {DEBUG_AUDIO_LEVELS}")


class AudioManager:
    """Manages audio recording and playback with VAD and interruption handling."""

    def __init__(self, input_device: Optional[str] = None, output_device1: Optional[str] = None, output_device2: Optional[str] = None):
        self.recording = False
        self.recording_thread: Optional[threading.Thread] = None
        self.socketio: Optional[SocketIO] = None
        self.audio_chunks_sent = 0
        self.input_device_index = self._find_device(input_device, "input") if input_device else None
        self.output_device_index_idle = self._find_device(output_device1, "output") if output_device1 else None
        self.output_device_index_recording = self._find_device(output_device2, "output") if output_device2 else None
        
        # VAD state management
        self.vad_buffer = queue.Queue(maxsize=100)
        self.current_utterance = []
        self.is_speaking = False
        self.silence_frames = 0
        self.speech_frames = 0
        self.pre_buffer = []
        self.pre_buffer_size = int(VAD_BUFFER_DURATION * DEFAULT_SAMPLE_RATE / CHUNK_SIZE)
        
        # Playback interruption control
        self.playback_active = False
        self.playback_interrupt_event = threading.Event()
        self.current_playback_stream = None
        
        # Audio level monitoring for debugging
        self.debug_audio_levels = DEBUG_AUDIO_LEVELS
        self.last_input_level_emit = 0
        self.last_output_level_emit = 0
        self.level_emit_interval = 0.1  # Emit levels every 100ms
        self.input_level_emit_count = 0  # Counter for debug logging
        
        logger.info(f"AudioManager initialized")
        logger.info(f"Sample rate: {DEFAULT_SAMPLE_RATE}Hz, Channels: {DEFAULT_CHANNELS}, Chunk size: {CHUNK_SIZE}")
        logger.info(f"Audio level debugging: {'ENABLED' if self.debug_audio_levels else 'DISABLED'}")
        
        default_device = sd.default.device
        default_input_index = None
        default_output_index = None
        if default_device is not None:
            try:
                default_input_index = default_device[0]
                default_output_index = default_device[1]
            except TypeError:
                default_input_index = default_output_index = default_device
        
        if input_device:
            if self.input_device_index is not None:
                device_info = sd.query_devices(self.input_device_index)
                logger.info(f"Input device: {input_device} (index {self.input_device_index})")
                logger.info(f"  - Channels: {device_info['max_input_channels']}, Sample rate: {device_info['default_samplerate']}Hz")
            else:
                logger.warning(f"Input device '{input_device}' not found, using system default")
        else:
            if default_input_index is not None:
                try:
                    device_info = sd.query_devices(default_input_index)
                    logger.info(f"Using system default input: {device_info['name']} (index {default_input_index})")
                except Exception as exc:
                    logger.warning(
                        "Unable to query system default input device (%s): %s",
                        default_input_index,
                        exc
                    )
            else:
                logger.warning("System default input device not available")
        
        def _log_output_device(label: str, device_name: Optional[str], device_index: Optional[int]) -> None:
            if not device_name:
                return
            if device_index is not None:
                device_info = sd.query_devices(device_index)
                logger.info(f"{label} output device: {device_name} (index {device_index})")
                logger.info(f"  - Channels: {device_info['max_output_channels']}, Sample rate: {device_info['default_samplerate']}Hz")
            else:
                logger.warning(f"{label} output device '{device_name}' not found, using system default")

        _log_output_device("Idle", output_device1, self.output_device_index_idle)
        _log_output_device("Recording", output_device2, self.output_device_index_recording)

        default_device_info = None
        if default_output_index is not None:
            try:
                default_device_info = sd.query_devices(default_output_index)
            except Exception as exc:
                logger.warning(
                    "Unable to query system default output device (%s): %s",
                    default_output_index,
                    exc
                )
                default_output_index = None

        if not output_device1 and not output_device2:
            if default_device_info is not None:
                logger.info(f"Using system default output: {default_device_info['name']} (index {default_output_index})")
        else:
            if self.output_device_index_idle is None and default_device_info is not None:
                logger.info(
                    f"Idle output falling back to system default: {default_device_info['name']} (index {default_output_index})"
                )
            if self.output_device_index_recording is None and default_device_info is not None:
                logger.info(
                    f"Recording output falling back to system default: {default_device_info['name']} (index {default_output_index})"
                )

        if self.output_device_index_idle is None:
            self.output_device_index_idle = default_output_index
        if self.output_device_index_recording is None:
            self.output_device_index_recording = default_output_index

        if default_output_index is None:
            logger.warning("System default output device not available; sounddevice will choose at playback")
        
        if self.debug_audio_levels:
            logger.info("Audio level monitoring enabled for debugging")
    
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
    
    def _calculate_audio_level_db(self, audio_data: np.ndarray) -> float:
        """Calculate audio level in dB from audio data."""
        # Calculate RMS (root mean square)
        audio_float = audio_data.astype(np.float32)
        rms = np.sqrt(np.mean(audio_float ** 2))
        
        # Convert to dB (with small epsilon to avoid log(0))
        # Normalize by int16 max value (32768)
        normalized_rms = rms / 32768.0
        if normalized_rms < 1e-10:
            return -100.0  # Very quiet
        db = 20 * np.log10(normalized_rms)
        return float(db)

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
        """Callback for audio input stream with VAD processing."""
        if status:
            logger.warning(f"Audio callback status: {status}")
        
        # Calculate energy for VAD (normalize by int16 max value)
        audio_array = indata.astype(np.float32) / 32768.0  # Normalize to -1.0 to 1.0
        energy = np.sqrt(np.mean(audio_array ** 2))
        
        # Emit audio levels for debugging (throttled)
        if self.debug_audio_levels and self.socketio:
            current_time = time.time()
            if current_time - self.last_input_level_emit >= self.level_emit_interval:
                audio_level_db = self._calculate_audio_level_db(indata)
                self.socketio.emit('input_audio_level', {
                    'level_db': round(audio_level_db, 2),
                    'energy': round(float(energy), 6),
                    'is_speaking': self.is_speaking
                }, namespace='/')
                self.last_input_level_emit = current_time
                self.input_level_emit_count += 1
                # Log every 50 emissions (about every 5 seconds) to confirm it's working
                if self.input_level_emit_count % 50 == 1:
                    logger.info(f"Audio level debug active - Input: {audio_level_db:.1f} dB, Energy: {energy:.6f}, Speaking: {self.is_speaking} (emitted {self.input_level_emit_count} times)")
        elif self.debug_audio_levels and not self.socketio:
            # Log once if socketio is not available
            if not hasattr(self, '_socketio_warning_logged'):
                logger.warning("DEBUG_AUDIO_LEVELS enabled but socketio not available")
                self._socketio_warning_logged = True
        
        # Maintain pre-buffer for capturing speech onset
        self.pre_buffer.append(indata.copy())
        if len(self.pre_buffer) > self.pre_buffer_size:
            self.pre_buffer.pop(0)
        
        # Voice Activity Detection
        if energy > VAD_ENERGY_THRESHOLD:
            # Speech detected
            if not self.is_speaking:
                # Start of utterance
                self.is_speaking = True
                self.silence_frames = 0
                # Add pre-buffer to capture speech onset
                self.current_utterance = list(self.pre_buffer)
                logger.info(f"Speech started (energy: {energy:.4f}, threshold: {VAD_ENERGY_THRESHOLD})")
                
                # Send utterance_start event
                self._send_utterance_start()
                
                # Send pre-buffer chunks
                for chunk in self.pre_buffer:
                    self._send_audio_chunk(chunk)
                
                # Interrupt any ongoing playback
                if self.playback_active:
                    self.interrupt_playback()
            
            # Send current audio chunk
            self._send_audio_chunk(indata.copy())
            self.current_utterance.append(indata.copy())
            self.speech_frames += 1
            
        else:
            # Silence detected
            if self.is_speaking:
                # Still send silence chunks during trailing silence
                self._send_audio_chunk(indata.copy())
                self.current_utterance.append(indata.copy())
                self.silence_frames += 1
                
                # Check if silence duration exceeds threshold
                silence_duration = self.silence_frames * CHUNK_SIZE / DEFAULT_SAMPLE_RATE
                if silence_duration > VAD_MAX_SILENCE_DURATION:
                    # End of utterance
                    speech_duration = len(self.current_utterance) * CHUNK_SIZE / DEFAULT_SAMPLE_RATE
                    
                    if speech_duration > VAD_MIN_SPEECH_DURATION:
                        # Valid utterance, send utterance_end
                        self._send_utterance_end(speech_duration)
                    else:
                        logger.info(f"Discarding short utterance ({speech_duration:.2f}s < {VAD_MIN_SPEECH_DURATION}s minimum)")
                        # Send utterance_cancelled event
                        if self.socketio:
                            self.socketio.emit('utterance_cancelled', {
                                'reason': 'too_short',
                                'duration': speech_duration
                            }, namespace='/')
                    
                    # Reset state
                    self.is_speaking = False
                    self.current_utterance = []
                    self.silence_frames = 0
                    self.speech_frames = 0

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

    def _send_utterance_start(self):
        """Send utterance_start event to main.py."""
        if not self.socketio:
            return
        
        self.socketio.emit('utterance_start', {
            'timestamp': time.time()
        }, namespace='/')
        logger.info("➡️  Sent utterance_start event to main.py")
    
    def _send_audio_chunk(self, audio_chunk: np.ndarray):
        """Send a single audio chunk to main.py."""
        if not self.socketio:
            return
        
        # Convert to bytes and encode
        audio_bytes = audio_chunk.astype(np.int16).tobytes()
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        self.socketio.emit('audio_chunk', {
            'audio': audio_b64,
            'size': len(audio_bytes)
        }, namespace='/')
    
    def _send_utterance_end(self, duration: float):
        """Send utterance_end event to main.py."""
        if not self.socketio:
            return
        
        self.socketio.emit('utterance_end', {
            'duration': duration,
            'timestamp': time.time(),
            'total_chunks': len(self.current_utterance)
        }, namespace='/')
        logger.info(f"✅ Sent utterance_end to main.py: {duration:.2f}s, {len(self.current_utterance)} chunks")
        self.audio_chunks_sent += 1
    
    def interrupt_playback(self):
        """Interrupt ongoing audio playback."""
        if self.playback_active:
            logger.info("Interrupting playback due to user speech")
            self.playback_interrupt_event.set()
            sd.stop()
            self.playback_active = False
            
            # Notify main.py about interruption
            if self.socketio:
                self.socketio.emit('playback_interrupted', {}, namespace='/')
    
    def output_audio(self, audio_bytes: bytes):
        """Output audio bytes with interruption support."""
        try:
            logger.debug(f"Starting audio output: {len(audio_bytes)} bytes")
            self.playback_active = True
            self.playback_interrupt_event.clear()
            
            # Convert bytes to numpy array (int16 samples)
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Reshape interleaved stereo data to (N, 2) for sounddevice
            if DEFAULT_CHANNELS == 2:
                audio_array = audio_array.reshape(-1, 2)
            elif DEFAULT_CHANNELS == 1:
                # Keep as 1D for mono
                pass
            
            # Play audio in chunks to allow interruption
            chunk_samples = CHUNK_SIZE * 4  # Larger chunks for smoother playback
            for i in range(0, len(audio_array), chunk_samples):
                if self.playback_interrupt_event.is_set():
                    logger.info("Playback interrupted")
                    break
                    
                chunk = audio_array[i:i+chunk_samples]
                
                # Emit output audio levels for debugging (throttled)
                if self.debug_audio_levels and self.socketio:
                    current_time = time.time()
                    if current_time - self.last_output_level_emit >= self.level_emit_interval:
                        # Convert chunk to int16 for level calculation if needed
                        chunk_int16 = chunk if chunk.dtype == np.int16 else chunk.astype(np.int16)
                        audio_level_db = self._calculate_audio_level_db(chunk_int16)
                        self.socketio.emit('output_audio_level', {
                            'level_db': round(audio_level_db, 2)
                        }, namespace='/')
                        self.last_output_level_emit = current_time
                
                device_index = self.output_device_index_recording if self.recording else self.output_device_index_idle
                sd.play(chunk, samplerate=DEFAULT_SAMPLE_RATE, device=device_index)
                sd.wait()
            
            if not self.playback_interrupt_event.is_set():
                logger.info(f"Audio playback completed: {len(audio_bytes)} bytes")
            
            self.playback_active = False
            
        except Exception as e:
            logger.error(f"Error outputting audio: {e}", exc_info=True)
            self.playback_active = False


# Initialize Flask app and extensions
app = Flask(__name__)
CORS(app)
# Increase max message size to 10MB to handle large audio files
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10_000_000)

# Initialize audio manager
audio_manager = AudioManager(
    input_device=INPUT_DEVICE_NAME,
    output_device1=OUTPUT_DEVICE_NAME1,
    output_device2=OUTPUT_DEVICE_NAME2
)
audio_manager.socketio = socketio

logger.info(
    "Audio manager configured: input=%s, idle_output=%s, recording_output=%s",
    INPUT_DEVICE_NAME,
    OUTPUT_DEVICE_NAME1,
    OUTPUT_DEVICE_NAME2
)


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
    logger.info(f"DEBUG_AUDIO_LEVELS: {DEBUG_AUDIO_LEVELS}")
    logger.info(f"Available audio devices:")
    devices = sd.query_devices()
    for idx, device in enumerate(devices):
        if device['max_input_channels'] > 0 or device['max_output_channels'] > 0:
            logger.info(f"  [{idx}] {device['name']}: in={device['max_input_channels']}, out={device['max_output_channels']}")
    
    logger.info("SocketIO server initialized with max message size: 10MB")

    socketio.run(app, host=host, port=port, debug=True, log_output=False, allow_unsafe_werkzeug=True)
