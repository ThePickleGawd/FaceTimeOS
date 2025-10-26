# MacOS AI Agent

Control your entire Mac with AI Agents, via:

1. **FaceTime**: Call MacOSAgent, it will answer and share screen. Then, talk naturally to instruct any computer-related task.
2. **iMessage**: Text MacOSAgent, it will fulfill your prompt

TODO: Demo GIF here

## Overview

Our project is organized into three folders

1. `Agent-S` — Our fork of the current SoTA computer-use agent framework. [Original Repo](https://github.com/simular-ai/Agent-S)
2. `backend` - Flask server to handle iMessage/FaceTime and generate voice transcriptions and replies
3. `frontend` — UI to prompt and view current actions of Agent S

![FaceTimeOS System Diagram](docs/diagram.png)
