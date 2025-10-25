# Computer Use Mac Agents. Control with FaceTime or iMessage!

## Overview

Agent S enables multimodal computer-use control via REST APIs.  
It includes three main components:

1. **Agent S Server** — handles agent actions and prompts.
2. **Flask Server** — bridges Agent S and the UI.
3. **UI Server** — displays agent state and relays user input.

---

## 🧠 Agent S Server

### `POST /api/chat`

- **Body:** `string`
- **Behavior:** Stops any current task, loads the new prompt, then starts.

### `GET /api/stop`

- Cancels the current prompt and stops the agent.

### `GET /api/pause`

- Pauses the current task but keeps context.
- When resumed, it continues from the same prompt.

### `GET /api/resume`

- Resumes from the paused state.

---

## ⚙️ Flask Server

### For **Agent S** to call

#### `POST /api/completetask`

- Takes a screenshot and sends it to the user.
- May include other post-task actions.

#### `POST /api/currentaction`

- Sends the agent’s current “action” to the UI Server.

### For **UI Server** to call

#### `POST /api/chat`

- **Body:** `string`
- Sends user prompt to the Agent S Server.

#### `GET /api/stop`, `GET /api/pause`, `GET /api/resume`

- Propagate control commands to Agent S.

---

## 💻 UI Server

### `POST /api/currentaction`

- **Body:** `dict`
- Receives the agent’s current action from the Flask Server.
- Displays it in a Cluely-style widget.

---

## 🗣️ Davyn POST Format

Example request:

```json
{
  "original": "REFLECTION: Case 1. The trajectory is not going according to plan.\n\nThe hotkey was executed, but the Settings/Preferences view did not open—the editor still shows code tabs and no Settings tab or pane. Repeating the same shortcut may indicate a loop without progress, possibly due to focus being in the terminal or the shortcut not registering. Modify your approach rather than repeating the same hotkey.",
  "mode": "text",
  "message": "Thinking...",
  "Speech": "We are currently facing trajectory issues… I’m here to help!"
}
```
