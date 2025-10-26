# Troubleshooting Audio Level Monitoring

## Quick Diagnosis

Run this test script to verify audio level monitoring:

```bash
cd backend
python test_audio_levels.py
```

This will connect to the audio server and report whether audio levels are being received.

## Step-by-Step Troubleshooting

### 1. Verify Environment Variable

Check that `.env` file contains:
```bash
DEBUG_AUDIO_LEVELS=true
```

**Note:** Make sure there are NO spaces around the `=` sign, and the value is exactly `true` (lowercase).

Verify it's loaded:
```bash
cd backend
grep DEBUG_AUDIO_LEVELS ../.env
```

### 2. Restart the Audio Server

The server must be restarted after any `.env` changes:

```bash
# Stop the server if running (Ctrl+C)
# Then start it again:
cd backend
python call.py
```

### 3. Check Startup Logs

When the server starts, you should see these messages:

```
[STARTUP] DEBUG_AUDIO_LEVELS environment variable: true
[STARTUP] DEBUG_AUDIO_LEVELS resolved to: True
...
INFO - Starting audio call server on 0.0.0.0:5002
INFO - DEBUG_AUDIO_LEVELS: True
...
INFO - AudioManager initialized
INFO - Sample rate: 48000Hz, Channels: 2, Chunk size: 1024
INFO - Audio level debugging: ENABLED
```

**If you see `DISABLED` or `False`:**
- The `.env` file wasn't loaded correctly
- Make sure you're starting the server from the `backend/` directory
- Check for typos in the `.env` file

### 4. Check During Recording

When recording is active and audio levels are being emitted, you should see periodic logs:

```
INFO - Audio level debug active - Input: -42.3 dB, Energy: 0.000234, Speaking: False (emitted 1 times)
INFO - Audio level debug active - Input: -38.1 dB, Energy: 0.000512, Speaking: True (emitted 51 times)
```

These appear every ~5 seconds if audio levels are being detected.

**If you don't see these logs:**
- Recording might not have started successfully
- No audio is being captured (check your audio input device)
- The `socketio` object might not be initialized

### 5. Verify WebSocket Connection

Check the HTML console in your browser (F12 → Console):

```javascript
// You should see:
Connected to audio server

// And NOT see:
WebSocket connection failed
CORS error
```

### 6. Common Issues

#### Issue: "DEBUG_AUDIO_LEVELS: False" in logs
**Solution:** 
- Double-check `.env` file (must be `true`, not `True` or `TRUE`)
- Restart the server
- Make sure you're editing the correct `.env` file at `/Users/calvin/Documents/Coding/calhacks-25/.env`

#### Issue: No startup messages about DEBUG_AUDIO_LEVELS
**Solution:**
- Your server code might be outdated
- Make sure the recent changes to `call.py` are saved
- Check the file modification time: `ls -la backend/call.py`

#### Issue: "Recording already in progress" error
**Solution:**
- Stop the recording first: Click "Stop Recording" in the HTML console
- Or restart the server

#### Issue: HTML console shows "Connected" but no audio levels
**Solution:**
- Check if recording actually started (should see "Recording started successfully")
- Look at the server logs to see if audio levels are being emitted there
- Try the `test_audio_levels.py` script to rule out browser issues

#### Issue: Audio input device not working
**Solution:**
- Check that the correct device is configured in `.env`:
  ```bash
  AUDIO_INPUT_DEVICE=BlackHole 16ch
  ```
- Verify the device exists: Run server and check "Available audio devices" in logs
- Test with system default by commenting out the `AUDIO_INPUT_DEVICE` line

### 7. Enable Detailed Logging

For even more detailed logging, modify the server startup:

```python
# In backend/call.py, change:
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

This will show DEBUG level messages including every audio level emission.

### 8. Manual Test

To manually test if the server is working:

```bash
# Terminal 1: Start server
cd backend
python call.py

# Terminal 2: Run test script
cd backend
python test_audio_levels.py

# Terminal 3: Check what environment is loaded
cd backend
python -c "from dotenv import load_dotenv; import os; from pathlib import Path; load_dotenv(Path(__file__).resolve().parent.parent / '.env'); print(f'DEBUG_AUDIO_LEVELS={os.getenv(\"DEBUG_AUDIO_LEVELS\", \"NOT SET\")}')"
```

## Expected Behavior

When everything is working correctly:

1. **Server startup:** Shows `DEBUG_AUDIO_LEVELS: True` and `Audio level debugging: ENABLED`
2. **During recording:** Periodic log messages showing audio levels every ~5 seconds
3. **In HTML console:** Real-time meter bars updating 10 times per second
4. **Test script output:** Reports receiving input_audio_level events

## Still Not Working?

If you've tried all the above and it's still not working:

1. Check if there's a `.env.example` or other env file that might be overriding
2. Try hardcoding `DEBUG_AUDIO_LEVELS = True` directly in `call.py` (line 43) to bypass env loading
3. Verify Python can import all required packages: `pip list | grep -E 'flask|socketio|numpy|sounddevice'`
4. Check for any error messages in the full server logs
5. Try running the server with `python -u call.py` to ensure unbuffered output

## Debug Checklist

- [ ] `.env` file contains `DEBUG_AUDIO_LEVELS=true`
- [ ] Server restarted after `.env` change
- [ ] Startup logs show `DEBUG_AUDIO_LEVELS: True`
- [ ] Startup logs show `Audio level debugging: ENABLED`
- [ ] Recording started successfully (no errors)
- [ ] Audio input device is correct and connected
- [ ] WebSocket connection successful in browser
- [ ] Test script successfully receives audio levels
