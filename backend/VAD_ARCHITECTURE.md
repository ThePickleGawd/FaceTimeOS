# Voice Activity Detection (VAD) Architecture

## Overview
The system now implements intelligent Voice Activity Detection (VAD) to create a more natural conversation flow for FaceTime calls. Instead of continuously streaming audio, the system detects complete utterances and handles interruptions gracefully.

## Key Components

### 1. Voice Activity Detection (call.py)
- **Energy-based VAD**: Detects speech based on audio energy levels
- **Pre-buffering**: Captures audio before speech onset to avoid clipping
- **Utterance detection**: Groups speech segments into complete utterances
- **Configurable thresholds**:
  - `VAD_ENERGY_THRESHOLD`: 0.01 (energy level to detect speech)
  - `VAD_MIN_SPEECH_DURATION`: 0.3s (minimum valid utterance)
  - `VAD_MAX_SILENCE_DURATION`: 0.8s (silence before ending utterance)
  - `VAD_BUFFER_DURATION`: 0.1s (pre-buffer to capture onset)

### 2. Interruption Handling
- **Automatic interruption**: When user starts speaking, any ongoing AI playback stops
- **Playback tracking**: System tracks when AI is speaking
- **Event notification**: Main service is notified when playback is interrupted
- **Chunked playback**: Audio plays in chunks to allow quick interruption

### 3. Communication Flow

```
User Speaks → VAD Detects → Utterance Complete → Send to main.py
                ↓
         (If AI speaking)
                ↓
         Interrupt Playback
```

## WebSocket Events

### New Events
- **`user_utterance`**: Complete user speech segment with duration
- **`playback_interrupted`**: Notification that AI speech was interrupted

### Modified Behavior
- **`audio_input`**: Now supports interruption during playback
- **`start_recording`**: Initiates VAD-based recording
- **`stop_recording`**: Cleanly stops VAD processing

## Benefits

1. **Natural Conversations**: Users can interrupt the AI naturally
2. **Better Transcription**: Complete utterances improve ASR accuracy
3. **Reduced Latency**: No need to process continuous audio chunks
4. **Lower Bandwidth**: Only meaningful audio is transmitted
5. **Cleaner Architecture**: Separation of concerns between services

## Testing

Run the test script to verify the integration:

```bash
# Terminal 1: Start call service
cd backend
python call.py

# Terminal 2: Start main service
cd backend
python main.py

# Terminal 3: Run tests
cd backend
python test_vad_integration.py
```

## Configuration

Adjust VAD sensitivity in `call.py`:

```python
# More sensitive (picks up quieter speech)
VAD_ENERGY_THRESHOLD = 0.005

# Less sensitive (requires louder speech)
VAD_ENERGY_THRESHOLD = 0.02

# Faster response (shorter utterances)
VAD_MAX_SILENCE_DURATION = 0.5

# Slower response (longer pauses allowed)
VAD_MAX_SILENCE_DURATION = 1.2
```

## Debugging

Monitor logs for VAD behavior:
- "Speech started" - VAD detected voice
- "Sent utterance" - Complete utterance transmitted
- "Interrupting playback" - User interrupted AI
- "Discarding short utterance" - Noise filtered out

## Architecture Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   FaceTime   │────▶│   call.py    │────▶│   main.py    │
│    Audio     │     │     VAD      │     │   Business   │
│              │     │  Detection   │     │    Logic     │
└──────────────┘     └──────────────┘     └──────────────┘
                             │                     │
                             │  user_utterance    │
                             │────────────────────▶│
                             │                     │
                             │   audio_input      │
                             │◀────────────────────│
                             │                     │
                      ┌──────▼──────┐              │
                      │ Interruption│              │
                      │   Handler   │              │
                      └─────────────┘              │
                             │                     │
                             │ playback_interrupted│
                             │────────────────────▶│
```

## Future Improvements

1. **Adaptive VAD**: Adjust thresholds based on ambient noise
2. **Multi-language support**: Language-specific VAD parameters
3. **Emotion detection**: Detect urgency/emotion in interruptions
4. **Echo cancellation**: Better handling of system audio feedback
5. **WebRTC integration**: For browser-based calls
