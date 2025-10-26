# Audio Streaming Architecture

## Overview

The audio system now uses a **streaming architecture** where audio is sent in real-time chunks rather than waiting for complete utterances. This provides several benefits:

- **Lower latency**: Audio processing can begin before the user finishes speaking
- **Better responsiveness**: The system can react immediately to speech
- **Memory efficiency**: No need to buffer entire utterances in call.py
- **Flexibility**: main.py controls how to handle the audio stream

## Architecture Flow

```
User Speech → call.py (VAD) → WebSocket Stream → main.py (Processing)
```

### 1. call.py (Audio Capture & VAD)

**Responsibilities:**
- Capture audio from input device
- Perform Voice Activity Detection (VAD)
- Stream audio chunks in real-time
- Signal utterance boundaries

**Events Emitted:**

#### `utterance_start`
Emitted when speech is detected (VAD triggered)
```json
{
  "timestamp": 1698284523.123
}
```

#### `audio_chunk`
Emitted continuously during speech (real-time streaming)
```json
{
  "audio": "base64_encoded_audio_data",
  "size": 4096
}
```

**Frequency:** Every audio callback (typically ~21ms at 48kHz with 1024 samples)

#### `utterance_end`
Emitted when silence threshold is reached
```json
{
  "duration": 2.5,
  "timestamp": 1698284525.623,
  "total_chunks": 120
}
```

#### `utterance_cancelled`
Emitted when utterance is too short to process
```json
{
  "reason": "too_short",
  "duration": 0.2
}
```

### 2. main.py (Audio Processing)

**Responsibilities:**
- Accumulate audio chunks into complete utterances
- Transcribe complete audio
- Process transcripts with Agent-S
- Generate and send responses

**Event Handlers:**

- `on_utterance_start()`: Initialize buffer for new utterance
- `on_audio_chunk()`: Accumulate incoming audio chunks
- `on_utterance_end()`: Process complete utterance
- `on_utterance_cancelled()`: Clean up cancelled utterances

## Implementation Details

### call.py Audio Callback Flow

```python
def _audio_callback(self, indata, frames, time_info, status):
    1. Calculate energy for VAD
    2. Check if energy > threshold:
       - If first speech frame:
         a. Send utterance_start event
         b. Send pre-buffer chunks (to capture speech onset)
         c. Interrupt playback if active
       - Send current audio_chunk
    3. If silence detected during speech:
       - Continue sending audio_chunks (includes trailing silence)
       - If silence duration > threshold:
         a. Check if utterance duration > minimum
         b. Send utterance_end or utterance_cancelled
         c. Reset state
```

### main.py Buffer Management

```python
# Global state
current_utterance_chunks = []  # List of audio byte chunks
utterance_start_time = None    # Timestamp when utterance started

on_utterance_start():
    - Reset buffer to []
    - Record start timestamp

on_audio_chunk(chunk):
    - Decode base64 audio
    - Append to current_utterance_chunks[]
    - Log progress (optional)

on_utterance_end():
    - Join all chunks: audio_bytes = b''.join(current_utterance_chunks)
    - Transcribe complete audio
    - Process with Agent-S
    - Generate response
    - Clear buffer and reset state
```

## Timing & Performance

### Typical Utterance Flow

| Time | Event | Data Size | Action |
|------|-------|-----------|--------|
| 0.0s | `utterance_start` | - | Buffer initialized |
| 0.02s | `audio_chunk` | 4KB | First chunk |
| 0.04s | `audio_chunk` | 4KB | Second chunk |
| ... | ... | ... | ... |
| 2.5s | `utterance_end` | - | Process complete audio |

### Audio Chunk Details

- **Sample Rate:** 48,000 Hz
- **Channels:** 2 (stereo)
- **Bit Depth:** 16-bit int16
- **Chunk Size:** 1,024 samples
- **Chunk Duration:** ~21ms
- **Chunk Byte Size:** 4,096 bytes (1024 samples × 2 channels × 2 bytes)

### Network Overhead

- **Base64 Encoding:** Increases size by ~33%
- **Chunk Transfer Size:** ~5.5 KB per chunk (including JSON overhead)
- **Chunks per Second:** ~47 chunks/sec
- **Bandwidth:** ~260 KB/sec during active speech

## VAD Configuration

Voice Activity Detection thresholds (configurable in `call.py`):

```python
VAD_ENERGY_THRESHOLD = 0.01      # Energy threshold for detecting speech
VAD_MIN_SPEECH_DURATION = 0.3    # Minimum utterance duration (seconds)
VAD_MAX_SILENCE_DURATION = 0.8   # Max silence before ending utterance
VAD_BUFFER_DURATION = 0.1        # Pre-buffer to capture speech onset
```

## Benefits of Streaming Architecture

### 1. **Lower Latency**
- Audio chunks available immediately
- Can start processing before user finishes speaking
- Enables real-time features (e.g., live transcription)

### 2. **Better Resource Management**
- call.py doesn't buffer entire utterances
- main.py controls memory allocation
- Can implement backpressure if needed

### 3. **Flexibility**
- main.py can process chunks individually or batched
- Easy to add streaming transcription in future
- Can implement early interruption detection

### 4. **Debugging**
- Clear event boundaries make debugging easier
- Can monitor chunk flow in real-time
- Audio level monitoring works seamlessly

## Future Enhancements

### Potential Improvements

1. **Streaming Transcription**
   - Process audio chunks as they arrive
   - Provide real-time transcription feedback
   - Enable faster response times

2. **Chunk Compression**
   - Compress audio before base64 encoding
   - Reduce network bandwidth
   - Trade CPU for network

3. **Adaptive VAD**
   - Adjust thresholds based on environment
   - Learn user's speech patterns
   - Improve detection accuracy

4. **Backpressure Handling**
   - Monitor main.py processing speed
   - Pause streaming if buffer grows too large
   - Prevent memory overflow

## Migration Notes

### Old Architecture (Deprecated)
```python
# call.py sent complete utterances
@sio.on('user_utterance')
def on_user_utterance(data):
    audio_b64 = data.get('audio')
    # Process complete audio
```

### New Architecture (Current)
```python
# Streaming with separate events
@sio.on('utterance_start')
def on_utterance_start(data): ...

@sio.on('audio_chunk')
def on_audio_chunk(data): ...

@sio.on('utterance_end')
def on_utterance_end(data): ...
```

The old `user_utterance` event is **no longer emitted** and can be removed from client code.

## Testing

### Test Streaming Flow

1. Start call.py: `cd backend && python call.py`
2. Start main.py: `cd backend && python main.py`
3. Speak into the configured input device
4. Monitor logs:
   ```
   [call.py] Speech started
   [call.py] Sent utterance_start event
   [main.py] User utterance started - beginning audio stream
   [main.py] Received audio chunk: 4096 bytes (total chunks: 1)
   [main.py] Received audio chunk: 4096 bytes (total chunks: 2)
   ...
   [call.py] Sent utterance_end: 2.50s, 120 chunks
   [main.py] Utterance complete: 491520 bytes from 120 chunks, 2.50s duration
   [main.py] User said: [transcription]
   ```

### Verify Chunk Flow

Check that:
- ✅ `utterance_start` fires before any `audio_chunk`
- ✅ `audio_chunk` events stream continuously during speech
- ✅ `utterance_end` fires after silence threshold
- ✅ Total bytes in main.py matches expected size
- ✅ No chunks lost (verify chunk count matches)

## Troubleshooting

### Issue: No audio chunks received

**Possible Causes:**
- WebSocket connection not established
- VAD threshold too high (no speech detected)
- Audio input device not working

**Solution:**
- Check WebSocket connection logs
- Lower `VAD_ENERGY_THRESHOLD` temporarily
- Verify input device in call.py logs

### Issue: Chunks received but utterance never ends

**Possible Causes:**
- Background noise keeping VAD active
- `VAD_MAX_SILENCE_DURATION` too long
- Energy calculation issue

**Solution:**
- Increase `VAD_ENERGY_THRESHOLD` to reduce noise sensitivity
- Decrease `VAD_MAX_SILENCE_DURATION`
- Check audio levels with debug console

### Issue: Utterances cut off too early

**Possible Causes:**
- `VAD_MAX_SILENCE_DURATION` too short
- Natural pauses in speech detected as silence

**Solution:**
- Increase `VAD_MAX_SILENCE_DURATION` (try 1.0-1.5s)
- Monitor energy levels during natural pauses

## Performance Metrics

Expected performance on typical hardware:

- **Latency (speech → utterance_start):** < 50ms
- **Chunk delivery rate:** ~47 chunks/second
- **Memory per chunk:** ~4KB
- **Memory per 5s utterance:** ~1MB
- **CPU overhead (call.py):** < 5%
- **CPU overhead (main.py):** < 2%

## Summary

The streaming architecture provides:
- ✅ Real-time audio delivery
- ✅ Lower memory footprint
- ✅ Better debugging visibility
- ✅ Foundation for future enhancements
- ✅ Cleaner separation of concerns

The system maintains the same end-to-end functionality while improving performance and flexibility.
