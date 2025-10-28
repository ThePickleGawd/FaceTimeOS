from __future__ import annotations

import argparse
import datetime
import io
import logging
import os
import platform
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple
from typing_extensions import Literal

import pyautogui
from PIL import Image
from flask import Flask, Request, jsonify, request
import requests

from src.s3.agents.agent_s import AgentS3
from src.s3.agents.grounding import OSWorldACI
from src.s3.utils.local_env import LocalEnv

current_platform = platform.system().lower()

app = Flask(__name__)


@dataclass
class AgentState:
    """Runtime flags and synchronization primitives for Agent-S."""

    running: bool = False
    paused: bool = False
    prompt: Optional[str] = None
    thread: Optional[threading.Thread] = field(default=None, repr=False)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    pause_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self) -> None:
        self.pause_event.set()

    def to_dict(self) -> dict:
        return {"running": self.running, "paused": self.paused, "prompt": self.prompt}


STATE = AgentState()
STATE_LOCK = threading.Lock()

AGENT: Optional[AgentS3] = None
GROUNDING_AGENT: Optional[OSWorldACI] = None
LOCAL_ENV: Optional[LocalEnv] = None
SCALED_DIMENSIONS: Tuple[int, int] = (0, 0)
NOTIFICATION_HISTORY_LIMIT = 20
NOTIFICATION_HISTORY: deque[str] = deque(maxlen=NOTIFICATION_HISTORY_LIMIT)
SUMMARY_HISTORY_LIMIT = 10
SUMMARY_HISTORY: deque[str] = deque(maxlen=SUMMARY_HISTORY_LIMIT)


def _load_env_config() -> dict:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    config: dict[str, str] = {}
    if not env_path.exists():
        return config
    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return config


def _normalize_host(host: str) -> str:
    host = host.strip()
    if host in {"", "0.0.0.0"}:
        return "127.0.0.1"
    return host


ENV_CONFIG = _load_env_config()
SERVER_HOST = _normalize_host(ENV_CONFIG.get("SERVER_HOST", "127.0.0.1"))
SERVER_PORT = ENV_CONFIG.get("SERVER_PORT", "8003")
AGENT_HOST = _normalize_host(ENV_CONFIG.get("AGENT_HOST", "127.0.0.1"))
AGENT_PORT = ENV_CONFIG.get("AGENT_PORT", "8001")
CURRENT_ACTION_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/currentaction"

ASI_ONE_ENDPOINT = (
    os.getenv("ASI_ONE_ENDPOINT", "https://api.asi1.ai/v1/chat/completions").strip()
    or "https://api.asi1.ai/v1/chat/completions"
)
ASI_ONE_MODEL = os.getenv("ASI_ONE_MODEL", "asi1-mini").strip() or "asi1-mini"
ASI_ONE_AGENT_HANDLE = (
    os.getenv("ASI_ONE_AGENT_HANDLE", "@computer-use-action-analysis").strip()
    or "@computer-use-action-analysis"
)
ASI_ONE_API_KEY = os.getenv("ASI_ONE_API_KEY", "").strip()
USE_FETCH_AI = False
try:
    ASI_ONE_TIMEOUT = float(os.getenv("ASI_ONE_TIMEOUT", "4.0"))
except ValueError:
    ASI_ONE_TIMEOUT = 4.0


def _resolve_chat_endpoint(base_url: str) -> str:
    base = (base_url or "").strip()
    if not base:
        return ""
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _resolve_provider_api_key(provider: str) -> str:
    provider_key = (provider or "").strip().lower()
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "azure": "AZURE_OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "grok": "GROK_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = env_map.get(provider_key)
    return os.getenv(env_var, "").strip() if env_var else ""


def _summarize_message(
    message: str,
    style: Literal["notification_text", "notification_voice"],
) -> Optional[str]:
    if len(message) <= 5 or not ASI_ONE_API_KEY or not ASI_ONE_ENDPOINT:
        return None

    # Only skip summarization for very short messages (<=15 chars)
    # This ensures messages like "Step 1/15: ..." get summarized

    style_normalized = style.lower()
    if style_normalized == "notification_text":
        system_prompt = (
            "You are an assistant that produces a single concise status line (<=30 characters) "
            "summarizing what the Agent-S desktop agent is doing. Avoid emojis, filler, weird syntax. "
            "Strip ALL redundant info like 'Step X/15', emojis, code snippets, repetitive phrases. "
            "Examples: 'Step 1/15: Getting next action...' -> 'I'm getting action'. "
            "If you believe the user is trying to get you to stop. Print only: stopping. "
            "Avoid repeating yourself if you have already summarized the same action. "
            "If you believe you have already summarized the same action, print only: same action. "
        )
        char_limit = 60
    else:
        system_prompt = (
            "You are Agent-S, an assistant that produces a short, natural-sounding spoken update "
            "(<=160 characters) summarizing what the Agent-S desktop agent is doing in first person mode. Avoid emojis, filler, weird syntax. "
            "If you believe the user is trying to get you to stop. Print only: stopping. "
            "If you believe that the current message is unnatural or unneeded to say aloud (it's too explicit), don't say anything. "
            "Your top priority is to speak in first person and sound natural. "
            "Avoid repeating yourself if you have already summarized the same action. "
            "If you believe you have already summarized the same action, print only: same action. "
        )
        char_limit = 160 if style_normalized == "notification_voice" else None

    history = list(NOTIFICATION_HISTORY)
    history_block = (
        "\n".join(f"- {entry}" for entry in history[-NOTIFICATION_HISTORY_LIMIT:])
        if history
        else "None"
    )

    summary = list(SUMMARY_HISTORY)
    summary_block = (
        "\n".join(f"- {entry}" for entry in summary[-SUMMARY_HISTORY_LIMIT:])
        if summary
        else "None"
    )

    user_content = (
        f"{ASI_ONE_AGENT_HANDLE}\n"
        f"Summary style: {style_normalized}\n"
        f"Recent notification history:\n{history_block}\n\n"
        f"Recent summary history:\n{summary_block}\n\n"
        f"Current observation:\n{message}"
    )

    payload = {
        "model": ASI_ONE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    headers = {
        "Authorization": f"Bearer {ASI_ONE_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            ASI_ONE_ENDPOINT, headers=headers, json=payload, timeout=ASI_ONE_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:  # pragma: no cover - defensive logging
        logging.getLogger("desktopenv.agent").warning(
            "ASI:One summary request failed (%s): %s", style_normalized, exc
        )
        return None
    except ValueError as exc:  # json decode errors
        logging.getLogger("desktopenv.agent").warning(
            "ASI:One summary response decode failed (%s): %s", style_normalized, exc
        )
        return None

    choices = data.get("choices") or []
    message_data = (choices[0].get("message") if choices else {}) or {}
    summary_text = (message_data.get("content") or "").strip()

    if "same action" in summary_text:
        print(summary_text)
        return None

    if char_limit and len(summary_text) > char_limit:
        summary_text = summary_text[:char_limit].rstrip()

    if summary_text:
        SUMMARY_HISTORY.append(summary_text)

    return summary_text or None


def _limit_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _sanitize_text(text: str) -> str:
    # Keep BMP printable characters (basic ASCII punctuation/letters/numbers).
    sanitized_chars = []
    for ch in text:
        # allow standard printable ASCII
        if 32 <= ord(ch) <= 126:
            sanitized_chars.append(ch)
        # allow newline and space explicitly
        elif ch in {"\n", "\r", "\t"}:
            sanitized_chars.append(ch)
        # drop everything else (emojis, control chars)
    return "".join(sanitized_chars)


last_voice_summary = 0  # global timestamp of last voice summary
VOICE_COOLDOWN = 5.0  # seconds


def _build_notification_payload(message: str) -> dict[str, object]:
    global last_voice_summary

    sanitized_message = _sanitize_text(message)
    payload: dict[str, object] = {"original": sanitized_message}

    # Always build text summary
    text_summary = _summarize_message(sanitized_message, "notification_text")
    payload["text_summary"] = text_summary

    # Only build voice summary if cooldown period has passed
    current_time = time.time()
    if current_time - last_voice_summary >= VOICE_COOLDOWN:
        voice_summary = _summarize_message(sanitized_message, "notification_voice")
        last_voice_summary = current_time
    else:
        voice_summary = ""  # or None, depending on what you prefer

    payload["voice_summary"] = voice_summary
    return payload


def notify_current_action(message: Optional[str] = None) -> None:
    if not CURRENT_ACTION_URL:
        return

    payload: dict[str, object]
    if isinstance(message, str) and message:
        payload = _build_notification_payload(message)
    else:
        sanitized = _sanitize_text(message) if isinstance(message, str) else ""
        payload = {
            "original": sanitized,
            "text_summary": sanitized,
            "voice_summary": sanitized,
        }
        if sanitized:
            NOTIFICATION_HISTORY.append(sanitized)

    try:
        requests.post(CURRENT_ACTION_URL, json=payload, timeout=2)
    except requests.RequestException:
        pass


ROOT_LOGGER = logging.getLogger()
if not ROOT_LOGGER.handlers:
    ROOT_LOGGER.setLevel(logging.DEBUG)

    datetime_str: str = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    file_handler = logging.FileHandler(
        os.path.join("logs", f"normal-{datetime_str}.log"), encoding="utf-8"
    )
    debug_handler = logging.FileHandler(
        os.path.join("logs", f"debug-{datetime_str}.log"), encoding="utf-8"
    )
    stdout_handler = logging.StreamHandler()
    sdebug_handler = logging.FileHandler(
        os.path.join("logs", f"sdebug-{datetime_str}.log"), encoding="utf-8"
    )

    file_handler.setLevel(logging.INFO)
    debug_handler.setLevel(logging.DEBUG)
    stdout_handler.setLevel(logging.INFO)
    sdebug_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="\x1b[1;33m[%(asctime)s \x1b[31m%(levelname)s \x1b[32m%(module)s/%(lineno)d-%(processName)s"
        "\x1b[1;33m] \x1b[0m%(message)s"
    )
    for handler in (file_handler, debug_handler, stdout_handler, sdebug_handler):
        handler.setFormatter(formatter)

    stdout_handler.addFilter(logging.Filter("desktopenv"))
    sdebug_handler.addFilter(logging.Filter("desktopenv"))

    ROOT_LOGGER.addHandler(file_handler)
    ROOT_LOGGER.addHandler(debug_handler)
    ROOT_LOGGER.addHandler(stdout_handler)
    ROOT_LOGGER.addHandler(sdebug_handler)


class CurrentActionHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        notify_current_action(record.getMessage())


LOGGER = logging.getLogger("desktopenv.agent")
LOGGER.setLevel(logging.INFO)
if not any(isinstance(handler, CurrentActionHandler) for handler in LOGGER.handlers):
    handler = CurrentActionHandler()
    handler.setLevel(logging.INFO)
    LOGGER.addHandler(handler)


def log_debug(message: str) -> None:
    """Emit a debug log that also triggers the current-action notifier."""
    LOGGER.debug(message)


def show_permission_dialog(code: str, action_description: str) -> bool:
    """Show a platform-specific permission dialog and return True if approved."""
    if platform.system() == "Darwin":
        result = os.system(
            f'osascript -e \'display dialog "Do you want to execute this action?\n\n{code} which will try to {action_description}" '
            'with title "Action Permission" buttons {"Cancel", "OK"} default button "OK" cancel button "Cancel"\''
        )
        return result == 0
    if platform.system() == "Linux":
        result = os.system(
            f'zenity --question --title="Action Permission" --text="Do you want to execute this action?\n\n{code}" '
            "--width=400 --height=200"
        )
        return result == 0
    return False


def scale_screen_dimensions(
    width: int, height: int, max_dim_size: int
) -> Tuple[int, int]:
    scale_factor = min(max_dim_size / width, max_dim_size / height, 1)
    safe_width = int(width * scale_factor)
    safe_height = int(height * scale_factor)
    return safe_width, safe_height


def _wait_if_paused() -> bool:
    """Block while paused; return False if stop requested before resuming."""
    while not STATE.stop_event.is_set():
        if STATE.pause_event.wait(timeout=0.1):
            return True
    return False


def run_agent(
    agent: AgentS3, instruction: str, scaled_width: int, scaled_height: int
) -> None:
    obs = {}
    for step in range(15):
        if STATE.stop_event.is_set():
            LOGGER.debug("Stop requested before step %d", step + 1)
            break
        if not _wait_if_paused():
            LOGGER.debug("Stop requested while paused before step %d", step + 1)
            break

        screenshot = pyautogui.screenshot()
        screenshot = screenshot.resize((scaled_width, scaled_height), Image.LANCZOS)

        buffered = io.BytesIO()
        screenshot.save(buffered, format="PNG")
        obs["screenshot"] = buffered.getvalue()

        if STATE.stop_event.is_set():
            LOGGER.debug("Stop requested before prediction step %d", step + 1)
            break
        if not _wait_if_paused():
            LOGGER.debug(
                "Stop requested while paused before prediction step %d", step + 1
            )
            break

        # LOGGER.info("🔄 Step %d/15: Getting next action from agent...", step + 1)
        info, code = agent.predict(instruction=instruction, observation=obs)

        if STATE.stop_event.is_set():
            LOGGER.debug("Stop requested after prediction step %d", step + 1)
            break

        action_text = code[0]
        action_lower = action_text.lower()

        if "done" in action_lower or "fail" in action_lower:
            status = "fail" if "fail" in action_lower else "done"
            try:
                # LOGGER.info(
                #     "I'm done!"
                #     if status == "done"
                #     else "I messed up something. Let me know what to do next."
                # )
                requests.post(
                    f"http://{SERVER_HOST}:{SERVER_PORT}/api/completetask",
                    json={"status": status, "action": action_text},
                    timeout=2,
                )
            except requests.RequestException:
                pass
            break

        if "next" in action_lower:
            continue

        if "wait" in action_lower:
            LOGGER.info("⏳ Agent requested wait...")
            for _ in range(50):
                if STATE.stop_event.is_set():
                    break
                if not _wait_if_paused():
                    break
                time.sleep(0.1)
            continue

        time.sleep(1.0)
        LOGGER.info("EXECUTING CODE: %s", code[0])

        if STATE.stop_event.is_set():
            LOGGER.debug("Stop requested before executing code at step %d", step + 1)
            break
        if not _wait_if_paused():
            LOGGER.debug(
                "Stop requested while paused before executing code at step %d", step + 1
            )
            break

        exec(code[0])
        time.sleep(1.0)

        if "reflection" in info and "executor_plan" in info:
            traj += (
                "\n\nReflection:\n"
                + str(info["reflection"])
                + "\n\n----------------------\n\nPlan:\n"
                + info["executor_plan"]
            )

        if STATE.stop_event.is_set():
            LOGGER.debug("Stop requested after executing code at step %d", step + 1)
            break


def _extract_prompt(req: Request) -> str:
    """Allow raw string or JSON payloads when starting a chat session."""
    payload = req.get_json(silent=True)
    if isinstance(payload, dict) and "prompt" in payload:
        return str(payload["prompt"])
    raw_body = req.get_data(cache=False, as_text=True) or ""
    return raw_body.strip()


def _agent_worker(prompt: str) -> None:
    LOGGER.debug("Agent worker started with prompt: %s", prompt)
    was_stopped = False
    try:
        if AGENT is None:
            LOGGER.error("Agent not configured; unable to run.")
            return

        AGENT.reset()
        scaled_width, scaled_height = SCALED_DIMENSIONS
        run_agent(AGENT, prompt, scaled_width, scaled_height)
    except Exception:
        LOGGER.exception("Agent run failed.")
    finally:
        with STATE_LOCK:
            was_stopped = STATE.stop_event.is_set()
            STATE.running = False
            STATE.paused = False
            STATE.prompt = None
            STATE.thread = None
            STATE.stop_event.clear()
            STATE.pause_event.set()

        # Notify UI that agent has finished
        if was_stopped:
            notify_current_action("Ok, I'm going to stop now.")
        else:
            notify_current_action("I'm done!")

        LOGGER.debug("Agent worker finished.")


def stop_agent(wait: bool = True) -> None:
    thread: Optional[threading.Thread] = None
    with STATE_LOCK:
        thread = STATE.thread
        if thread and thread.is_alive():
            LOGGER.debug("Stop requested for active agent thread.")
            STATE.stop_event.set()
            STATE.pause_event.set()

    if wait and thread and thread.is_alive():
        thread.join()

    with STATE_LOCK:
        if not (STATE.thread and STATE.thread.is_alive()):
            STATE.thread = None
        STATE.running = False
        STATE.paused = False
        STATE.prompt = None
        STATE.stop_event.clear()
        STATE.pause_event.set()


def start_agent(prompt: str) -> None:
    stop_agent(wait=True)

    if not prompt:
        with STATE_LOCK:
            STATE.running = False
            STATE.paused = False
            STATE.prompt = None
        return

    worker = threading.Thread(target=_agent_worker, args=(prompt,), daemon=True)
    with STATE_LOCK:
        STATE.prompt = prompt
        STATE.running = True
        STATE.paused = False
        STATE.stop_event.clear()
        STATE.pause_event.set()
        STATE.thread = worker

    worker.start()
    LOGGER.info("Ok I'm starting...")


def pause_agent() -> None:
    with STATE_LOCK:
        if STATE.running and not STATE.paused:
            STATE.paused = True
            STATE.pause_event.clear()
            LOGGER.info("Ok I'm pausing...")


def resume_agent() -> None:
    with STATE_LOCK:
        if STATE.running and STATE.paused:
            STATE.paused = False
            STATE.pause_event.set()
            LOGGER.info("Ok I'm resuming...")


@app.route("/api/chat", methods=["POST"])
def start_chat():
    """
    Start a new Agent-S run for the supplied prompt.

    The current run (if any) is stopped first so the new prompt can take over.
    """
    if AGENT is None:
        return jsonify({"error": "Agent is not configured."}), 500

    prompt = _extract_prompt(request)
    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    start_agent(prompt)
    return jsonify({"status": "started", "state": STATE.to_dict()}), 200


@app.route("/api/stop", methods=["GET"])
def stop():
    """Stop the current Agent-S run and clear the active prompt."""
    stop_agent(wait=True)
    return jsonify({"status": "stopped", "state": STATE.to_dict()}), 200


@app.route("/api/pause", methods=["GET"])
def pause():
    """Pause an active Agent-S run while keeping the current prompt."""
    pause_agent()
    return jsonify({"status": "paused", "state": STATE.to_dict()}), 200


@app.route("/api/resume", methods=["GET"])
def resume():
    """Resume a paused Agent-S run with the same prompt."""
    resume_agent()
    return jsonify({"status": "resumed", "state": STATE.to_dict()}), 200


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AgentS3 server with specified model."
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        help="Specify the provider to use (e.g., openai, anthropic, etc.).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5",
        help="Specify the model to use (e.g., gpt-5).",
    )
    parser.add_argument(
        "--model_url",
        type=str,
        default="https://api.openai.com/v1/",
        help="The URL of the main generation model API.",
    )
    parser.add_argument(
        "--model_api_key",
        type=str,
        default="",
        help="The API key of the main generation model.",
    )
    parser.add_argument(
        "--model_temperature",
        type=float,
        default=1.0,
        help="Temperature to fix the generation model at (e.g. o3 can only be run with 1.0).",
    )
    parser.add_argument(
        "--ground_provider",
        type=str,
        default="openai",
        help="The provider for the grounding model.",
    )
    parser.add_argument(
        "--ground_url",
        type=str,
        default="https://api.openai.com/v1/",
        help="The URL of the grounding model.",
    )
    parser.add_argument(
        "--ground_api_key",
        type=str,
        default=os.environ.get("OPENAI_API_KEY", ""),
        help="The API key of the grounding model (defaults to $OPENAI_API_KEY if set).",
    )
    parser.add_argument(
        "--ground_model",
        type=str,
        default="gpt-5",
        help="The model name for the grounding model.",
    )
    parser.add_argument(
        "--grounding_width",
        type=int,
        default=1920,
        help="Width of screenshot image after processor rescaling.",
    )
    parser.add_argument(
        "--grounding_height",
        type=int,
        default=1080,
        help="Height of screenshot image after processor rescaling.",
    )
    parser.add_argument(
        "--max_trajectory_length",
        type=int,
        default=8,
        help="Maximum number of image turns to keep in trajectory.",
    )
    parser.add_argument(
        "--enable_reflection",
        action="store_true",
        default=False,
        help="Enable reflection agent to assist the worker agent.",
    )
    parser.add_argument(
        "--enable_local_env",
        action="store_true",
        default=False,
        help="Enable local coding environment for code execution (WARNING: Executes arbitrary code locally).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=AGENT_HOST,
        help="Host interface for the Flask server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=AGENT_PORT,
        help="Port for the Flask server.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Run Flask in debug mode.",
    )
    parser.add_argument(
        "--asi_one_api_key",
        type=str,
        default=os.getenv("ASI_ONE_API_KEY", ""),
        help="API key for ASI:One summaries (defaults to $ASI_ONE_API_KEY).",
    )
    parser.add_argument(
        "--use_fetch_ai",
        action="store_true",
        default=False,
        help=(
            "Use the Fetch.ai (ASI:One) service for notification summaries "
            "instead of the main model provider."
        ),
    )
    return parser


def configure_agent(args: argparse.Namespace) -> None:
    global AGENT, GROUNDING_AGENT, LOCAL_ENV, SCALED_DIMENSIONS
    global ASI_ONE_API_KEY, ASI_ONE_ENDPOINT, ASI_ONE_MODEL, USE_FETCH_AI

    screen_width, screen_height = pyautogui.size()
    SCALED_DIMENSIONS = scale_screen_dimensions(
        screen_width, screen_height, max_dim_size=2400
    )

    engine_params = {
        "engine_type": args.provider,
        "model": args.model,
        "base_url": args.model_url,
        "api_key": args.model_api_key,
        "temperature": getattr(args, "model_temperature", None),
    }

    engine_params_for_grounding = {
        "engine_type": args.ground_provider,
        "model": args.ground_model,
        "base_url": args.ground_url,
        "api_key": args.ground_api_key,
        "grounding_width": args.grounding_width,
        "grounding_height": args.grounding_height,
    }

    if args.enable_local_env:
        LOGGER.warning(
            "⚠️  Local coding environment enabled. This executes arbitrary code locally!"
        )
        LOCAL_ENV = LocalEnv()
    else:
        LOCAL_ENV = None

    GROUNDING_AGENT = OSWorldACI(
        env=LOCAL_ENV,
        platform=current_platform,
        engine_params_for_generation=engine_params,
        engine_params_for_grounding=engine_params_for_grounding,
        width=screen_width,
        height=screen_height,
    )

    AGENT = AgentS3(
        engine_params,
        GROUNDING_AGENT,
        platform=current_platform,
        max_trajectory_length=args.max_trajectory_length,
        enable_reflection=args.enable_reflection,
    )

    LOGGER.debug("Agent configured successfully with provider '%s'.", args.provider)

    if getattr(args, "asi_one_api_key", None):
        ASI_ONE_API_KEY = args.asi_one_api_key.strip()

    USE_FETCH_AI = bool(getattr(args, "use_fetch_ai", False))

    if not USE_FETCH_AI:
        resolved_endpoint = _resolve_chat_endpoint(args.model_url)
        ASI_ONE_ENDPOINT = resolved_endpoint
        if not resolved_endpoint:
            LOGGER.warning(
                "Notification summaries configured to use the main model but "
                "the model_url is empty; summaries will be disabled."
            )

        ASI_ONE_MODEL = args.model or ASI_ONE_MODEL

        summary_api_key = (args.model_api_key or "").strip()
        if not summary_api_key:
            summary_api_key = _resolve_provider_api_key(args.provider)

        if summary_api_key:
            ASI_ONE_API_KEY = summary_api_key
        else:
            LOGGER.warning(
                "Notification summaries configured to use the main model but "
                "no model_api_key was provided; summaries will be disabled."
            )
            ASI_ONE_API_KEY = ""


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    configure_agent(args)

    LOGGER.debug("Starting Agent-S Flask server on %s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
