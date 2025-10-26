# Audio Level Monitoring - Debug Console

This debug feature provides real-time visualization of audio levels for both input (recording) and output (playback).

## Setup

1. **Enable Debug Mode**
   
   Set the environment variable in your `.env` file:
   ```bash
   DEBUG_AUDIO_LEVELS=true
   ```

2. **Start the Audio Server**
   
   ```bash
   cd backend
   python call.py
   ```

3. **Open the Debug Console**
   
   Open `backend/audio_level_monitor.html` in your web browser:
   ```bash
   open backend/audio_level_monitor.html
   ```
   
   Or navigate to: `file:///path/to/backend/audio_level_monitor.html`

## Usage

### In the Debug Console:

1. **Click "Connect"** - Establishes websocket connection to the audio server (default: localhost:5002)
2. **Click "Start Recording"** - Begins audio recording and displays input levels
3. **Click "Stop Recording"** - Stops recording

### What You'll See:

#### Input Audio Level (Recording)
- **Real-time dB meter**: Visual bar showing audio input levels
- **Numeric dB value**: Precise decibel reading
- **Energy level**: Raw energy calculation used for Voice Activity Detection (VAD)
- **Speech status**: Shows "Speaking" when speech is detected, "Silent" otherwise
- **Peak value**: Highest input level recorded during session

#### Output Audio Level (Playback)
- **Real-time dB meter**: Visual bar showing audio output levels during playback
- **Numeric dB value**: Precise decibel reading
- **Peak value**: Highest output level recorded during session

### Color Coding:

- 🔵 **Blue** (-60 to -30 dB): Quiet - audio is present but low
- 🟢 **Green** (-30 to -12 dB): Normal - good audio levels
- 🟠 **Orange** (-12 to -6 dB): Good - strong signal
- 🔴 **Red** (above -6 dB): Too loud - risk of clipping/distortion

## WebSocket Events

When `DEBUG_AUDIO_LEVELS=true`, the audio server emits these events:

### `input_audio_level`
Emitted every 100ms during recording:
```json
{
  "level_db": -23.45,
  "energy": 0.012345,
  "is_speaking": true
}
```

### `output_audio_level`
Emitted every 100ms during playback:
```json
{
  "level_db": -18.92
}
```

## Performance Notes

- Audio levels are throttled to emit every 100ms to reduce CPU and network overhead
- When `DEBUG_AUDIO_LEVELS=false` (default), no level calculations or emissions occur
- This feature is intended for **debugging only** and should be disabled in production

## Troubleshooting

### No audio levels showing
- Verify `DEBUG_AUDIO_LEVELS=true` is set in `.env`
- Restart the audio server after changing environment variables
- Check browser console for websocket connection errors
- Verify the server is running on port 5002 (or your configured port)

### Connection failed
- Ensure the audio server is running (`python backend/call.py`)
- Check that the port in the HTML file matches your `CALL_SERVICE_PORT` setting
- Look for firewall or CORS issues in browser console

### Levels seem incorrect
- dB values are relative to int16 audio format (±32768)
- A value of 0 dB represents full scale (very loud)
- Most speech falls in the -40 to -15 dB range
- Background noise is typically below -50 dB

## Technical Details

**dB Calculation:**
```
RMS = sqrt(mean(audio_samples^2))
normalized_RMS = RMS / 32768.0
dB = 20 * log10(normalized_RMS)
```

**Update Interval:** 100ms (10 Hz)
**Measurement Range:** -100 dB to 0 dB
**Audio Format:** int16, 48kHz, stereo
