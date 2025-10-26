# agent.py
import os
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Literal
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("Set OPENAI_API_KEY")

OPENAI_URL = os.getenv("OPENAI_CHAT_URL", "https://api.openai.com/v1/chat/completions")
MODEL_ENGINE = os.getenv("MODEL_ENGINE", "gpt-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "64"))

HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "Content-Type": "application/json",
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
    *,
    summary_style: Literal["notification_text", "notification_voice"],
) -> str:
    """
    Build a prompt for OpenAI GPT-5 that produces a concise summary.

    The behaviour depends on ``summary_style``:
        - ``"notification_text"``: <=50 character UI-friendly blurb.
        - ``"notification_voice"``: natural-sounding voice narration (~160 chars).
    """
    style = summary_style.lower()

    if style == "notification_text":
        system_rules = (
            "You generate a SINGLE concise status line for a small screen.\n"
            "- Max 50 characters.\n"
            "- No emojis. Keep concrete and clear.\n"
            "- Avoid filler words. No preamble.\n"
            "- If unsure, respond with 'Thinking'."
        )
        char_limit = 50
        enforce_word_cap = False
    elif style == "notification_voice":
        system_rules = (
            "You narrate a SINGLE natural-sounding voice update.\n"
            "- Aim for <= 160 characters.\n"
            "- Friendly but concise tone.\n"
            "- No emojis.\n"
            "- If unsure, respond with 'Thinking'."
        )
        char_limit = 160
        enforce_word_cap = False
    else:
        system_rules = (
            "You generate a SINGLE ultra-brief action summary.\n"
            "- Max 8 words.\n"
            "- No emojis. Keep concrete.\n"
            "- Prefer verbs. No preamble.\n"
            "- If unsure, respond with 'Thinking'."
        )
        char_limit = None
        enforce_word_cap = True

    trajectory_text = ""
    if history:
        trajectory_text = "\n[Trajectory]\n" + "\n".join(
            f"- {s}" for s in history[-TRAJECTORY_LEN:]
        )

    user_parts: list[dict[str, Any]] = []

    # Current thoughts + optional image(s)
    for item in content:
        if item.get("type") == "text":
            user_parts.append({"type": "text", "text": "[Current]\n" + item["text"]})
        elif item.get("type") == "resource":
            mime_type = item.get("mime_type", "")
            if mime_type.startswith("image/"):
                data_url = f"data:{mime_type};base64,{item['contents']}"
                user_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    }
                )
            else:
                user_parts.append(
                    {
                        "type": "text",
                        "text": f"[Note] Unsupported mime type: {mime_type}",
                    }
                )

    data = {
        "model": MODEL_ENGINE,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_rules + trajectory_text},
            {"role": "user", "content": user_parts or [{"type": "text", "text": ""}]},
        ],
    }

    try:
        resp = requests.post(
            OPENAI_URL, headers=HEADERS, data=json.dumps(data), timeout=60
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return "Thinking"

    payload = resp.json()
    choices = payload.get("choices", [])
    if not choices:
        return "Thinking"

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        text = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    else:
        text = str(content).strip()

    # Enforce the 8-word cap defensively
    if enforce_word_cap:
        words = text.split()
        if len(words) > 8:
            text = " ".join(words[:8])

    if char_limit and len(text) > char_limit:
        text = text[:char_limit].rstrip()

    # If the model returns blank, provide a fallback
    if not text:
        text = "Thinking"

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
    ctx.logger.debug(f"[chat] from={sender} id={msg.msg_id}")

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
    ctx.logger.debug(f"[ack] from={sender} acked={msg.acknowledged_msg_id}")


# Register protocol (publish manifest for discovery)
agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
