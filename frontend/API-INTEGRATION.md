# Current Action API Integration

This document explains how to integrate your Flask server (or any backend) with the Cluely widget to display real-time action updates.

## Overview

The Cluely Electron app runs an HTTP server on port `3456` that accepts POST requests containing the current action being performed by your agent. These actions are displayed in the widget UI.

## Endpoint

```
POST http://localhost:3456/api/currentaction
```

### Request Format

- **Method**: POST
- **Content-Type**: text/plain
- **Body**: Plain text string describing the current action

### Response Format

```json
{
  "success": true,
  "received": "Opening calendar app..."
}
```

## Usage Examples

### Python (Flask/requests)

```python
import requests

def send_current_action(action: str):
    """Send current action update to Cluely widget"""
    response = requests.post(
        'http://localhost:3456/api/currentaction',
        data=action,
        headers={'Content-Type': 'text/plain'}
    )
    return response.json()

# Example usage
send_current_action("Opening calendar app...")
send_current_action("Creating new event...")
send_current_action("Event created successfully!")
```

### JavaScript/Node.js

```javascript
const http = require('http');

function sendCurrentAction(action) {
  const options = {
    hostname: 'localhost',
    port: 3456,
    path: '/api/currentaction',
    method: 'POST',
    headers: {
      'Content-Type': 'text/plain',
      'Content-Length': Buffer.byteLength(action)
    }
  };

  const req = http.request(options, (res) => {
    res.on('data', (chunk) => {
      console.log(`Response: ${chunk}`);
    });
  });

  req.write(action);
  req.end();
}

// Example usage
sendCurrentAction("Opening calendar app...");
```

### cURL

```bash
curl -X POST http://localhost:3456/api/currentaction \
  -H "Content-Type: text/plain" \
  -d "Opening calendar app..."
```

## How It Works

1. **Flask Server** → Sends action string via POST to `http://localhost:3456/api/currentaction`
2. **Electron Backend** → Receives the action and forwards it to the React frontend via IPC
3. **React Frontend** → Updates the UI to display the current action

### UI Display

The action will appear:
- In the **command bar** as the agent status (e.g., "Opening calendar app...")
- In the **chat popup** as a detailed message (when opened)
- The Start button automatically switches to **Pause** when action is received
- A blue pulsing indicator shows the agent is active

## Testing

Two test scripts are provided:

### Node.js Test
```bash
node test-action-api.js
```

### Python Test
```bash
python3 test-action-api.py
```

Both scripts send a series of test actions to demonstrate the integration.

## Integration with Your Flask Agent

In your Flask server, call the API whenever your agent performs an action:

```python
from your_agent import Agent
import requests

agent = Agent()

def update_widget(action):
    requests.post(
        'http://localhost:3456/api/currentaction',
        data=action,
        headers={'Content-Type': 'text/plain'}
    )

# Example: Creating a calendar event
update_widget("Agent is thinking...")
result = agent.plan_task("create lunch event tomorrow")

update_widget("Opening calendar app...")
agent.open_app("calendar")

update_widget("Creating new event...")
agent.create_event("Lunch", "tomorrow", "12pm")

update_widget("Event created successfully!")
```

## Error Handling

The API returns appropriate HTTP status codes:
- `200 OK` - Action received successfully
- `400 Bad Request` - Invalid request format
- `404 Not Found` - Invalid endpoint

Always handle errors gracefully in your integration code.

## Notes

- The server automatically starts when the Cluely app launches
- No authentication is required (localhost only)
- Actions are displayed immediately in the UI
- Previous action is replaced when a new one is sent
- The agent status clears when the action completes
