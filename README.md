# FaceTimeOS: Mac-use AI Voice Agents

Control your entire Mac with AI voice Agents, via:

1. **FaceTime**: Text your Mac asking to start a FaceTime, it start a session and share screen. Then, talk naturally to instruct any computer-related task.
2. **iMessage**: Text any other prompt, it will fulfill your task

## FaceTime Demo

<a href="https://www.youtube.com/watch?v=zN96RdE0OSg" target="_blank">
  <picture>
    <img src="https://img.youtube.com/vi/zN96RdE0OSg/maxresdefault.jpg" alt="Project Demo (YouTube)" />
  </picture>
</a>

> Click the image to watch the full demo on YouTube.

## iMessage Demo

https://github.com/user-attachments/assets/77a8fe7f-ca2f-4002-9a24-dcf0cfffc0de

## Overview

Our project is organized into three folders

1. `Agent-S` — Our fork of the current SoTA computer-use agent framework. [Original Repo](https://github.com/simular-ai/Agent-S)
2. `backend` - Flask server to handle iMessage/FaceTime and generate voice transcriptions and replies
3. `frontend` — UI to prompt and view current actions of Agent S

![FaceTimeOS System Diagram](docs/diagram.png)

## Why FaceTimeOS?

#### 1. Seamless Remote Control

Why download clunky remote desktop apps when you can simply **FaceTime your Mac**?  
FaceTimeOS lets you call or message your computer directly through **native Apple interfaces** — no extra setup, no third-party tools, just the simplicity of FaceTime and iMessage.

#### 2. Human-Level Intelligence

Powered by our extended **Agent S3** framework, FaceTimeOS achieves **state-of-the-art (OSWorld-verified)** performance on common computer-use tasks — surpassing existing systems like OpenAI or Anthropic’s Computer-Use Agents.  
We bring **human-level computer interaction** to everyone, accessible from anywhere in the world.
