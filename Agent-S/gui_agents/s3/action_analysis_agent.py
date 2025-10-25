# agent.py
import os
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests
from uagents import Agent, Context, Protocol
from uagents_core.storage import ExternalStorage

# Chat protocol imports (ASI1 Chat)
from uagents_core.contrib.protocols.chat import (
    chat_protocol_spec,
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    ResourceContent,
    StartSessionContent,
    MetadataContent,
)

# -------- Config --------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError("Set ANTHROPIC_API_KEY")

CLAUDE_URL = "https://api.anthropic.com/v1/messages"
MODEL_ENGINE = os.getenv("MODEL_ENGINE", "claude-3-5-haiku-latest")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "64"))

HEADERS = {
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

# Where Agentverse-hosted chat uploads are fetched
STORAGE_URL = os.getenv("AGENTVERSE_URL", "https://agentverse.ai") + "/v1/storage"

# -------- Memory: trajectory per sender --------
# Keep the last N summaries to provide context for future messages
TRAJECTORY_LEN = int(os.getenv("TRAJECTORY_LEN", "8"))
trajectory = defaultdict(lambda: deque(maxlen=TRAJECTORY_LEN))


def summarize_action(
    content: list[dict[str, Any]],
    history: list[str],
) -> str:
    """
    Build a tiny prompt for Anthropic that enforces:
    - one short line (<= 8 words)
    - uses prior trajectory for context
    - can include an image (base64) via 'resource' items
    """
    processed_content: list[dict[str, Any]] = []

    # Hard constraint instruction first
    system_rules = (
        "You generate a SINGLE ultra-brief action summary.\n"
        "- Max 8 words.\n"
        "- No emojis. Keep concrete.\n"
        "- Prefer verbs. No preamble.\n"
        "- If unsure, say 'Action unclear'."
    )
    # Anthropic's "system" goes in the top-level field; we emulate by prefixing text.
    processed_content.append({"type": "text", "text": f"[Rules]\n{system_rules}"})

    if history:
        processed_content.append(
            {
                "type": "text",
                "text": "[Trajectory]\n"
                + "\n".join(f"- {s}" for s in history[-TRAJECTORY_LEN:]),
            }
        )

    # Current thoughts + optional image(s)
    for item in content:
        if item.get("type") == "text":
            processed_content.append(
                {"type": "text", "text": "[Current]\n" + item["text"]}
            )
        elif item.get("type") == "resource":
            mime_type = item.get("mime_type", "")
            if mime_type.startswith("image/"):
                processed_content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": item[
                                "contents"
                            ],  # base64 string from Agentverse storage
                        },
                    }
                )
            else:
                processed_content.append(
                    {
                        "type": "text",
                        "text": f"[Note] Unsupported mime type: {mime_type}",
                    }
                )

    data = {
        "model": MODEL_ENGINE,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": processed_content}],
    }

    try:
        resp = requests.post(
            CLAUDE_URL, headers=HEADERS, data=json.dumps(data), timeout=60
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return "Action unclear"

    payload = resp.json()
    chunks = payload.get("content", [])
    text = chunks[0].get("text", "").strip() if chunks else ""

    # Enforce the 8-word cap defensively
    words = text.split()
    if len(words) > 8:
        text = " ".join(words[:8])

    # If the model returns blank, be deterministic
    if not text:
        text = "Action unclear"

    return text


# -------- Agent & Protocol --------
agent = Agent()
chat_proto = Protocol(spec=chat_protocol_spec)


def create_text_chat(text: str) -> ChatMessage:
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(type="text", text=text)],
    )


def create_metadata(metadata: dict[str, str]) -> ChatMessage:
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[MetadataContent(type="metadata", metadata=metadata)],
    )


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    ctx.logger.info(f"[chat] from={sender} id={msg.msg_id}")

    # Ack ASAP
    await ctx.send(
        sender,
        ChatAcknowledgement(
            acknowledged_msg_id=msg.msg_id, timestamp=datetime.now(timezone.utc)
        ),
    )

    # Build model content: text + (optional) images fetched from Agent Storage
    prompt_content: list[dict[str, Any]] = []

    for item in msg.content:
        if isinstance(item, StartSessionContent):
            # Signal that we can handle attachments (images)
            await ctx.send(sender, create_metadata({"attachments": "true"}))

            # Optional: reset trajectory on new session
            trajectory[sender].clear()

        elif isinstance(item, TextContent):
            # Treat any incoming text as the agent's "current mental thoughts"
            prompt_content.append({"type": "text", "text": item.text})

        elif isinstance(item, ResourceContent):
            # Download the uploaded resource (e.g., image) from Agentverse storage
            try:
                storage = ExternalStorage(
                    identity=ctx.agent.identity, storage_url=STORAGE_URL
                )
                data = storage.download(str(item.resource_id))
                prompt_content.append(
                    {
                        "type": "resource",
                        "mime_type": data["mime_type"],
                        "contents": data["contents"],  # base64
                    }
                )
            except Exception as ex:
                ctx.logger.error(f"Resource download failed: {ex}")
                await ctx.send(sender, create_text_chat("Action unclear"))
                return

    if not prompt_content:
        await ctx.send(sender, create_text_chat("Action unclear"))
        return

    # Summarize using trajectory for context
    history = list(trajectory[sender])
    summary = summarize_action(prompt_content, history)

    # Update trajectory memory
    trajectory[sender].append(summary)

    # Return the short, single-line summary
    await ctx.send(sender, create_text_chat(summary))


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"[ack] from={sender} acked={msg.acknowledged_msg_id}")


# Register protocol (publish manifest for discovery)
agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
