# Debugging Audio Flow: call.py → main.py

## Quick Diagnosis

If `main.py` is not receiving utterances, follow this checklist.

## The Problem You Had

**Issue:** `main.py` wasn't receiving `utterance_start` or `utterance_end` events.

**Root Cause:** 
1. VAD energy calculation was not normalized (raw int16 values instead of 0-1.0 range)
2. VAD threshold was set to 50 (way too high for normalized scale)
3. No audio was being detected, so no utterances were created

**Fix Applied:**
- ✅ Normalized energy calculation: `audio_array / 32768.0`
- ✅ Reset VAD threshold to `0.01` (correct for normalized scale)
- ✅ Added clear logging with emojis to track event flow

## Expected Log Flow

When everything works correctly, you should see:

### 1. In call.py logs:
```
INFO - Speech started (energy: 0.0234, threshold: 0.01)
INFO - ➡️  Sent utterance_start event to main.py
[... audio streaming ...]
INFO - ✅ Sent utterance_end to main.py: 2.35s, 112 chunks
```

### 2. In main.py logs:
```
INFO - 🎤 UTTERANCE START - Beginning audio stream from call.py
INFO - 📦 Audio chunk #1: 4096 bytes
INFO - 📦 Audio chunk #2: 4096 bytes
[... more chunks ...]
INFO - 🏁 UTTERANCE END - Received 458752 bytes from 112 chunks, 2.35s duration
INFO - User said: [transcription here]
```

## Troubleshooting Steps

### Step 1: Check if Audio is Being Captured

**What to look for in call.py logs:**
```
INFO - Audio level debug active - Input: -XX.X dB, Energy: 0.XXXXX, Speaking: False
```

**Diagnosis:**
- **Energy: 0.000000** → No audio signal (problem with input device)
- **Energy: 0.00001-0.005** → Very quiet (might be too quiet to trigger VAD)
- **Energy: 0.01-0.05** → Normal speech levels (should trigger VAD)
- **Energy: 0.1+** → Very loud (good signal)

### Step 2: Check if Speech is Being Detected

**What to look for:**
```
INFO - Speech started (energy: 0.0234, threshold: 0.01)
```

**If you don't see this:**
- Energy is below VAD threshold
- Adjust `VAD_ENERGY_THRESHOLD` in `call.py`:
  - For quiet environments: 0.005-0.008
  - For normal environments: 0.01-0.015
  - For noisy environments: 0.02-0.03

### Step 3: Check if Events are Being Sent

**What to look for:**
```
INFO - ➡️  Sent utterance_start event to main.py
```

**If you see this but main.py doesn't receive it:**
- WebSocket connection issue
- Check main.py connection logs
- Verify both servers are running

### Step 4: Check if Utterances are Completing

**What to look for:**
```
INFO - ✅ Sent utterance_end to main.py: 2.35s, 112 chunks
```

**If utterances start but never end:**
- Silence threshold might be too long
- Reduce `VAD_MAX_SILENCE_DURATION` (try 0.3-0.5s)

**If utterances are cancelled:**
```
INFO - Discarding short utterance (0.12s < 0.30s minimum)
INFO - ❌ UTTERANCE CANCELLED - Reason: too_short, Duration: 0.12s
```
- Utterance is too short
- Reduce `VAD_MIN_SPEECH_DURATION` (try 0.2s)
- Or speak for longer

## VAD Configuration Guide

Located at the top of `call.py`:

```python
VAD_ENERGY_THRESHOLD = 0.01  # Adjust based on environment
VAD_MIN_SPEECH_DURATION = 0.3  # Minimum utterance length
VAD_MAX_SILENCE_DURATION = 0.5  # Max pause before ending
VAD_BUFFER_DURATION = 0.1  # Pre-buffer for speech onset
```

### Tuning VAD_ENERGY_THRESHOLD

Test different values based on your environment:

| Environment | Recommended Range | Description |
|-------------|------------------|-------------|
| Very quiet room | 0.005 - 0.008 | Library, studio |
| Normal room | 0.01 - 0.015 | Office, home |
| Noisy environment | 0.02 - 0.03 | Cafe, street |
| Very noisy | 0.03 - 0.05 | Construction, loud venue |

### How to Find the Right Threshold

1. **Enable audio level monitoring** in `.env`:
   ```
   DEBUG_AUDIO_LEVELS=true
   ```

2. **Start recording** and observe energy levels:
   ```
   INFO - Audio level debug active - Input: -32.1 dB, Energy: 0.0156, Speaking: False
   ```

3. **Speak naturally** and note the energy values:
   - Background silence: 0.001-0.005
   - Your speech: 0.01-0.05
   
4. **Set threshold** to ~70% of your speech energy:
   - If speech is 0.02, set threshold to 0.014
   - If speech is 0.05, set threshold to 0.035

## Common Issues

### Issue 1: Energy always 0.000000

**Cause:** No audio input
**Solutions:**
- Check input device in `.env`: `AUDIO_INPUT_DEVICE=BlackHole 16ch`
- Verify device exists in startup logs
- Make sure audio is actually playing through that device
- Use system sound settings to test the device

### Issue 2: Speech detected but immediately cancelled

**Symptoms:**
```
INFO - Speech started (energy: 0.0234, threshold: 0.01)
INFO - Discarding short utterance (0.12s < 0.30s minimum)
```

**Cause:** Not speaking long enough
**Solutions:**
- Reduce `VAD_MIN_SPEECH_DURATION` to 0.2 or 0.15
- Speak for at least 0.3 seconds

### Issue 3: Utterances never end

**Symptoms:**
```
INFO - Speech started (energy: 0.0234, threshold: 0.01)
[... but never ends ...]
```

**Cause:** Background noise keeping VAD active
**Solutions:**
- Increase `VAD_ENERGY_THRESHOLD` (filter out noise)
- Decrease `VAD_MAX_SILENCE_DURATION` (end sooner)
- Improve input audio quality (reduce ambient noise)

### Issue 4: main.py receives start but not end

**Symptoms:**
```
[main.py] 🎤 UTTERANCE START - Beginning audio stream
[main.py] 📦 Audio chunk #1: 4096 bytes
[... but no UTTERANCE END ...]
```

**Cause:** call.py never sends utterance_end
**Solutions:**
- Check call.py logs for utterance_end
- If call.py sent it, WebSocket issue
- If call.py didn't send it, see Issue 3 above

### Issue 5: "Total chunks sent: 0"

**Symptoms:**
```
INFO - Recording stopped. Total chunks sent: 0
```

**Cause:** No valid utterances were detected
**Solutions:**
- Check energy levels (see Step 1 above)
- Lower VAD threshold
- Verify audio input device
- Speak longer than minimum duration

## Testing Commands

### Test 1: Verify Audio Input
```bash
# Terminal 1: Start call.py with debug
cd backend
python call.py

# Look for:
# - "Audio level debugging: ENABLED"
# - Energy levels > 0.000000 when audio plays
```

### Test 2: Test Speech Detection
```bash
# Terminal 1: call.py (already running)
# Terminal 2: Start main.py
cd backend
python main.py

# Speak clearly for 2-3 seconds
# Look for the emoji flow in both terminals
```

### Test 3: Open Audio Level Monitor
```bash
open backend/audio_level_monitor.html

# Click Connect, then Start Recording
# Speak and watch the input meter
# Verify energy levels match what you see in logs
```

## Quick Fix Checklist

- [ ] `DEBUG_AUDIO_LEVELS=true` in `.env`
- [ ] Both servers restarted after code changes
- [ ] Audio input device configured correctly
- [ ] Energy levels > 0.000000 when audio plays
- [ ] Energy levels > VAD threshold when speaking
- [ ] "Speech started" appears in call.py logs
- [ ] "➡️ Sent utterance_start" appears in call.py logs
- [ ] "🎤 UTTERANCE START" appears in main.py logs
- [ ] Audio chunks streaming (📦 in main.py logs)
- [ ] "✅ Sent utterance_end" appears in call.py logs
- [ ] "🏁 UTTERANCE END" appears in main.py logs
- [ ] Transcription appears in main.py logs

## Need More Help?

1. Share your logs from both call.py and main.py
2. Note the energy levels you're seeing
3. Describe your audio setup (input device, environment)
4. Check if the audio level monitor shows activity
