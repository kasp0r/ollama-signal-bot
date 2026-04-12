"""
Signal Bot for Ollama Integration
Uses signal-cli-rest-api to send/receive Signal messages.
Forwards messages to an Ollama server for AI-powered responses.
Supports conversation memory and slash commands.
"""

import asyncio
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Maximum conversation history per user (number of message pairs)
MAX_HISTORY = 50
START_TIME = datetime.now(timezone.utc)

def format_for_signal(text: str) -> str:
    """
    Convert Markdown-formatted text to clean plain text for Signal.
    Signal only supports plain text — no bold, italic, or HTML.
    """
    # Remove code block fences (```language ... ```)
    text = re.sub(r"```\w*\n?", "", text)

    # Inline code: `code` → code
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Bold + italic: ***text*** or ___text___
    text = re.sub(r"\*{3}(.+?)\*{3}", r"\1", text)
    text = re.sub(r"_{3}(.+?)_{3}", r"\1", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*{2}(.+?)\*{2}", r"\1", text)
    text = re.sub(r"_{2}(.+?)_{2}", r"\1", text)

    # Italic: *text* or _text_ (but not mid-word underscores like snake_case)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"\1", text)

    # Headers: ## Header → HEADER
    text = re.sub(r"^#{1,6}\s+(.+)$", lambda m: m.group(1).upper(), text, flags=re.MULTILINE)

    # Horizontal rules: --- or *** or ___
    text = re.sub(r"^[\s]*([-*_]){3,}\s*$", "─" * 30, text, flags=re.MULTILINE)

    # Unordered lists: - item or * item → • item
    text = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", text, flags=re.MULTILINE)

    # Ordered lists: clean up but keep numbers
    text = re.sub(r"^(\s*)\d+\.\s+", r"\1", text, flags=re.MULTILINE)

    # Links: [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Images: ![alt](url) → [Image: alt]
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"[Image: \1]", text)

    # Blockquotes: > text → │ text
    text = re.sub(r"^>\s?", "│ ", text, flags=re.MULTILINE)

    # Clean up excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()



class OllamaSignalBot:
    """Signal bot that interfaces with Ollama via signal-cli-rest-api."""

    def __init__(
        self,
        phone_number: str,
        signal_api_url: str,
        ollama_url: str,
        ollama_model: str = "gemma4:latest",
        system_prompt: str = "You are a helpful assistant.",
        allowed_senders: str = "*",
    ):
        self.phone_number = phone_number
        self.signal_api_url = signal_api_url.rstrip("/")
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self.system_prompt = system_prompt
        self.client = httpx.AsyncClient(timeout=180.0)
        self.max_history = MAX_HISTORY

        # Sender allowlist: "*" means allow everyone, otherwise a set of phone numbers
        if allowed_senders.strip() == "*" or not allowed_senders.strip():
            self.allowed_senders: set[str] | None = None  # None = allow all
            logger.info("Sender allowlist: OPEN (all senders allowed)")
        else:
            self.allowed_senders = {s.strip() for s in allowed_senders.split(",") if s.strip()}
            logger.info(f"Sender allowlist: {self.allowed_senders}")

        # Per-user conversation history: { sender: [{"role": ..., "content": ...}, ...] }
        self.conversations: dict[str, list[dict]] = defaultdict(list)
        # Per-user verbose mode (off by default)
        self.verbose_users: set[str] = set()

        logger.info(f"Bot phone number: {phone_number}")
        logger.info(f"Signal API: {signal_api_url}")
        logger.info(f"Ollama: {ollama_url} (model: {ollama_model})")

    # ── Access control ──────────────────────────────────────────────

    def is_sender_allowed(self, sender: str) -> bool:
        """Check if a sender is allowed to use the bot."""
        if self.allowed_senders is None:
            return True
        return sender in self.allowed_senders

    # ── Ollama API helpers ──────────────────────────────────────────

    async def query_ollama(self, sender: str, prompt: str) -> str:
        """Query Ollama using the chat endpoint with conversation history."""
        if not self.ollama_model:
            return (
                "⚠️ No model is currently loaded.\n\n"
                "Please pull a model on your Ollama server first:\n"
                "  e.g. ollama pull gemma4:latest\n\n"
                "Then set it with /model <name>, or restart the bot."
            )

        try:
            # Append user message to history
            self.conversations[sender].append({"role": "user", "content": prompt})

            # Trim history if it exceeds the limit
            if len(self.conversations[sender]) > self.max_history * 2:
                self.conversations[sender] = self.conversations[sender][-(self.max_history * 2):]

            url = f"{self.ollama_url}/api/chat"
            payload = {
                "model": self.ollama_model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    *self.conversations[sender],
                ],
                "stream": False,
            }

            logger.info(f"Querying Ollama ({self.ollama_model}): {prompt[:80]}...")
            response = await self.client.post(url, json=payload)
            response.raise_for_status()

            result = response.json()
            answer = result.get("message", {}).get("content", "No response from model.")

            # Append assistant response to history
            self.conversations[sender].append({"role": "assistant", "content": answer})

            logger.info(f"Ollama response: {answer[:80]}...")

            # Append verbose telemetry if enabled for this sender
            if sender in self.verbose_users:
                answer += self._format_telemetry(result)

            return answer

        except httpx.HTTPError as e:
            logger.error(f"HTTP error querying Ollama: {e}")
            return f"⚠️ Error communicating with Ollama: {e}"
        except Exception as e:
            logger.error(f"Unexpected error querying Ollama: {e}")
            return f"⚠️ Unexpected error: {e}"

    def _format_telemetry(self, result: dict) -> str:
        """Format Ollama response telemetry into a readable block."""
        total_ns = result.get("total_duration", 0)
        load_ns = result.get("load_duration", 0)
        prompt_eval_count = result.get("prompt_eval_count", 0)
        prompt_eval_ns = result.get("prompt_eval_duration", 0)
        eval_count = result.get("eval_count", 0)
        eval_ns = result.get("eval_duration", 0)

        total_s = total_ns / 1e9
        load_s = load_ns / 1e9
        prompt_eval_s = prompt_eval_ns / 1e9
        eval_s = eval_ns / 1e9

        # Tokens per second
        prompt_tps = (prompt_eval_count / prompt_eval_s) if prompt_eval_s > 0 else 0
        eval_tps = (eval_count / eval_s) if eval_s > 0 else 0

        return (
            f"\n\n─── Telemetry ───\n"
            f"  Model: {result.get('model', 'unknown')}\n"
            f"  Input tokens: {prompt_eval_count:,} ({prompt_eval_s:.2f}s | {prompt_tps:.1f} t/s)\n"
            f"  Output tokens: {eval_count:,} ({eval_s:.2f}s | {eval_tps:.1f} t/s)\n"
            f"  Model load: {load_s:.2f}s\n"
            f"  Total time: {total_s:.2f}s"
        )

    async def ollama_get(self, path: str) -> dict | list | None:
        """Helper for GET requests to the Ollama API."""
        try:
            r = await self.client.get(f"{self.ollama_url}{path}", timeout=15.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Ollama API error ({path}): {e}")
            return None

    async def ollama_post(self, path: str, payload: dict) -> dict | None:
        """Helper for POST requests to the Ollama API."""
        try:
            r = await self.client.post(f"{self.ollama_url}{path}", json=payload, timeout=30.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Ollama API error ({path}): {e}")
            return None

    # ── Slash commands ──────────────────────────────────────────────

    async def cmd_help(self, sender: str) -> str:
        """Return help text for all commands."""
        return (
            "📋 *Available Commands*\n\n"
            "/help — Show this help message\n"
            "/heartbeat — Show bot uptime and status\n"
            "/version — Show Ollama server version\n"
            "/list — List available models\n"
            "/model — Show current model\n"
            "/model <name> — Switch to a different model\n"
            "/ps — List currently running models\n"
            "/show <name> — Show details about a model\n"
            "/reset — Clear conversation memory\n"
            "/history — Show conversation stats\n"
            "/maxhistory — Show max history limit\n"
            "/maxhistory <n> — Set max history to n pairs\n"
            "/verbose — Toggle telemetry on responses"
        )

    async def cmd_list(self, sender: str) -> str:
        """List available Ollama models."""
        data = await self.ollama_get("/api/tags")
        if not data:
            return "⚠️ Could not retrieve models from Ollama."

        models = data.get("models", [])
        if not models:
            return "No models found on the Ollama server."

        lines = ["📦 *Available Models*\n"]
        for m in models:
            name = m.get("name", "unknown")
            size_gb = m.get("size", 0) / (1024 ** 3)
            param_size = m.get("details", {}).get("parameter_size", "")
            quant = m.get("details", {}).get("quantization_level", "")

            detail = f"({param_size}" if param_size else ""
            if quant:
                detail += f", {quant}" if detail else f"({quant}"
            if detail:
                detail += ")"

            marker = " ← current" if name == self.ollama_model else ""
            lines.append(f"  • {name} [{size_gb:.1f} GB] {detail}{marker}")

        return "\n".join(lines)

    async def cmd_model(self, sender: str, args: str) -> str:
        """Show or change the current model."""
        if not args:
            return f"🤖 Current model: *{self.ollama_model}*"

        new_model = args.strip()

        # Verify model exists
        data = await self.ollama_get("/api/tags")
        if data:
            available = [m.get("name", "") for m in data.get("models", [])]
            if new_model not in available:
                return (
                    f"⚠️ Model '{new_model}' not found.\n\n"
                    f"Available models:\n"
                    + "\n".join(f"  • {n}" for n in available)
                )

        old_model = self.ollama_model
        self.ollama_model = new_model
        logger.info(f"Model changed: {old_model} → {new_model}")
        return f"✅ Model switched: {old_model} → *{new_model}*"

    async def cmd_reset(self, sender: str) -> str:
        """Clear conversation history for the sender."""
        msg_count = len(self.conversations[sender])
        self.conversations[sender].clear()
        logger.info(f"Conversation reset for {sender} ({msg_count} messages cleared)")
        return f"🗑️ Conversation cleared ({msg_count} messages removed)."

    async def cmd_version(self, sender: str) -> str:
        """Get Ollama server version."""
        data = await self.ollama_get("/api/version")
        if not data:
            return "⚠️ Could not reach Ollama server."
        version = data.get("version", "unknown")
        return f"🏷️ Ollama version: *{version}*"

    async def cmd_heartbeat(self, sender: str) -> str:
        """Show bot uptime and service status."""
        now = datetime.now(timezone.utc)
        uptime = now - START_TIME
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Check Ollama
        ollama_ok = False
        try:
            r = await self.client.get(f"{self.ollama_url}/api/version", timeout=5.0)
            ollama_ok = r.status_code == 200
        except Exception:
            pass

        # Check Signal API
        signal_ok = False
        try:
            r = await self.client.get(f"{self.signal_api_url}/v1/about", timeout=5.0)
            signal_ok = r.status_code == 200
        except Exception:
            pass

        status_ollama = "✅ Online" if ollama_ok else "❌ Offline"
        status_signal = "✅ Online" if signal_ok else "❌ Offline"

        active_chats = sum(1 for v in self.conversations.values() if v)
        total_msgs = sum(len(v) for v in self.conversations.values())

        return (
            f"💓 *Bot Heartbeat*\n\n"
            f"⏱️ Uptime: {days}d {hours}h {minutes}m {seconds}s\n"
            f"🕐 Server time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"🤖 Model: {self.ollama_model}\n\n"
            f"*Service Status:*\n"
            f"  Ollama: {status_ollama}\n"
            f"  Signal API: {status_signal}\n\n"
            f"*Stats:*\n"
            f"  Active chats: {active_chats}\n"
            f"  Messages in memory: {total_msgs}"
        )

    async def cmd_ps(self, sender: str) -> str:
        """List currently running/loaded models."""
        data = await self.ollama_get("/api/ps")
        if not data:
            return "⚠️ Could not retrieve running models."

        models = data.get("models", [])
        if not models:
            return "No models currently loaded."

        lines = ["⚡ *Running Models*\n"]
        for m in models:
            name = m.get("name", "unknown")
            size_gb = m.get("size", 0) / (1024 ** 3)
            vram_gb = m.get("size_vram", 0) / (1024 ** 3)
            expires = m.get("expires_at", "")

            lines.append(f"  • {name}")
            lines.append(f"    Size: {size_gb:.1f} GB | VRAM: {vram_gb:.1f} GB")
            if expires:
                lines.append(f"    Expires: {expires}")

        return "\n".join(lines)

    async def cmd_show(self, sender: str, args: str) -> str:
        """Show information about a specific model."""
        model_name = args.strip() if args else self.ollama_model

        # Verify model exists
        data = await self.ollama_get("/api/tags")
        if data:
            available = [m.get("name", "") for m in data.get("models", [])]
            if model_name not in available:
                return (
                    f"⚠️ Model '{model_name}' not found.\n\n"
                    f"Available models:\n"
                    + "\n".join(f"  • {n}" for n in available)
                )

        result = await self.ollama_post("/api/show", {"name": model_name})
        if not result:
            return f"⚠️ Could not get info for model '{model_name}'."

        details = result.get("details", {})
        params = result.get("model_info", {})
        license_text = result.get("license", "")

        lines = [f"📄 *Model: {model_name}*\n"]

        if details:
            if details.get("family"):
                lines.append(f"  Family: {details['family']}")
            if details.get("parameter_size"):
                lines.append(f"  Parameters: {details['parameter_size']}")
            if details.get("quantization_level"):
                lines.append(f"  Quantization: {details['quantization_level']}")
            if details.get("format"):
                lines.append(f"  Format: {details['format']}")

        # Extract a few interesting model_info fields
        if params:
            arch = params.get("general.architecture", "")
            context = params.get(f"{arch}.context_length", params.get("llama.context_length", ""))
            if context:
                lines.append(f"  Context length: {context:,}" if isinstance(context, int) else f"  Context length: {context}")

        if license_text:
            # Show first 200 chars of license
            short_license = license_text[:200].strip()
            if len(license_text) > 200:
                short_license += "..."
            lines.append(f"\n  License: {short_license}")

        return "\n".join(lines)

    async def cmd_history(self, sender: str) -> str:
        """Show conversation statistics for the sender."""
        history = self.conversations[sender]
        if not history:
            return "📊 No conversation history. Start chatting!"

        user_msgs = sum(1 for m in history if m["role"] == "user")
        assistant_msgs = sum(1 for m in history if m["role"] == "assistant")
        total_chars = sum(len(m["content"]) for m in history)

        return (
            f"📊 *Conversation Stats*\n\n"
            f"  Your messages: {user_msgs}\n"
            f"  Bot responses: {assistant_msgs}\n"
            f"  Total characters: {total_chars:,}\n"
            f"  Memory limit: {self.max_history} pairs"
        )

    async def cmd_maxhistory(self, sender: str, args: str) -> str:
        """View or set the maximum conversation history (in message pairs)."""
        if not args:
            return f"📏 Max history is currently set to *{self.max_history}* pairs."

        try:
            value = int(args.strip())
        except ValueError:
            return "⚠️ Please provide a valid integer, e.g. `/maxhistory 100`"

        if value < 1:
            return "⚠️ Max history must be at least 1."
        if value > 10000:
            return "⚠️ Max history cannot exceed 10,000 pairs."

        old = self.max_history
        self.max_history = value
        logger.info(f"MAX_HISTORY changed by {sender}: {old} → {value}")
        return f"✅ Max history updated: {old} → *{value}* pairs."

    async def cmd_verbose(self, sender: str) -> str:
        """Toggle verbose mode (Ollama telemetry) for the sender."""
        if sender in self.verbose_users:
            self.verbose_users.discard(sender)
            logger.info(f"Verbose mode OFF for {sender}")
            return "🔇 Verbose mode *disabled*. Responses will no longer include telemetry."
        else:
            self.verbose_users.add(sender)
            logger.info(f"Verbose mode ON for {sender}")
            return (
                "🔊 Verbose mode *enabled*.\n\n"
                "Each response will now include:\n"
                "  • Input/output token counts\n"
                "  • Processing speed (tokens/sec)\n"
                "  • Model load time\n"
                "  • Total response time"
            )

    # ── Command router ──────────────────────────────────────────────

    async def handle_command(self, sender: str, text: str) -> str | None:
        """Route slash commands. Returns response text, or None if not a command."""
        if not text.startswith("/"):
            return None

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        commands = {
            "/help": lambda: self.cmd_help(sender),
            "/version": lambda: self.cmd_version(sender),
            "/list": lambda: self.cmd_list(sender),
            "/model": lambda: self.cmd_model(sender, args),
            "/ps": lambda: self.cmd_ps(sender),
            "/show": lambda: self.cmd_show(sender, args),
            "/reset": lambda: self.cmd_reset(sender),
            "/history": lambda: self.cmd_history(sender),
            "/maxhistory": lambda: self.cmd_maxhistory(sender, args),
            "/verbose": lambda: self.cmd_verbose(sender),
            "/heartbeat": lambda: self.cmd_heartbeat(sender),
        }

        handler = commands.get(command)
        if handler:
            logger.info(f"Command from {sender}: {command} {args}")
            return await handler()

        return f"❓ Unknown command: {command}\nType /help for available commands."

    # ── Signal messaging ────────────────────────────────────────────

    async def send_message(self, recipient: str, message: str):
        """Send a Signal message via the REST API."""
        # Convert markdown to plain text for Signal
        message = format_for_signal(message)

        # Signal has a message size limit; split if needed
        max_len = 4096
        chunks = [message[i:i + max_len] for i in range(0, len(message), max_len)]

        url = f"{self.signal_api_url}/v2/send"
        for chunk in chunks:
            payload = {
                "message": chunk,
                "number": self.phone_number,
                "recipients": [recipient],
            }
            try:
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
            except Exception as e:
                logger.error(f"Error sending message to {recipient}: {e}")

    async def send_typing(self, recipient: str, stop: bool = False):
        """Send a typing indicator."""
        url = f"{self.signal_api_url}/v1/typing-indicator/{self.phone_number}"
        try:
            if stop:
                await self.client.delete(url, json={"recipient": recipient})
            else:
                await self.client.put(url, json={"recipient": recipient})
        except Exception:
            pass

    async def receive_messages(self) -> list:
        """Poll for new messages via the REST API."""
        url = f"{self.signal_api_url}/v1/receive/{self.phone_number}"
        try:
            response = await self.client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            return []
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                logger.warning("Receive failed (account not registered?)")
            else:
                logger.error(f"Error receiving messages: {e}")
            return []
        except Exception as e:
            logger.error(f"Error receiving messages: {e}")
            return []

    # ── Message handling ────────────────────────────────────────────

    async def handle_message(self, envelope: dict):
        """Process a single incoming message."""
        data_message = envelope.get("dataMessage")
        if not data_message:
            return

        message_text = data_message.get("message")
        if not message_text:
            return

        sender = envelope.get("source", "unknown")
        logger.info(f"Message from {sender}: {message_text[:80]}...")

        # Sender allowlist check
        if not self.is_sender_allowed(sender):
            logger.warning(f"Blocked message from unauthorized sender: {sender}")
            await self.send_message(
                sender,
                "🚫 Access denied.\n\n"
                "You are not authorized to use this bot. "
                "Your phone number is not on the allowed senders list.\n\n"
                "Please contact the bot administrator to request access."
            )
            return

        await self.send_typing(sender)

        try:
            # Check for slash command first
            command_response = await self.handle_command(sender, message_text.strip())
            if command_response is not None:
                await self.send_message(sender, command_response)
                return

            # Regular message — query Ollama with conversation history
            response = await self.query_ollama(sender, message_text)
            await self.send_message(sender, response)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self.send_message(sender, f"⚠️ Sorry, I encountered an error: {e}")
        finally:
            await self.send_typing(sender, stop=True)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def wait_for_api(self):
        """Wait for signal-cli-rest-api to be ready."""
        logger.info("Waiting for Signal API to be ready...")
        for i in range(60):
            try:
                r = await self.client.get(f"{self.signal_api_url}/v1/about")
                if r.status_code == 200:
                    logger.info(f"Signal API is ready: {r.json()}")
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
        logger.error("Signal API did not become ready in time")
        sys.exit(1)

    async def auto_detect_model(self):
        """Auto-detect an Ollama model if none was configured, or validate the configured one."""
        # If a model is explicitly configured, verify it exists
        if self.ollama_model:
            data = await self.ollama_get("/api/tags")
            if data:
                available = [m.get("name", "") for m in data.get("models", [])]
                if self.ollama_model in available:
                    logger.info(f"Configured model '{self.ollama_model}' is available.")
                    return
                else:
                    logger.warning(
                        f"Configured model '{self.ollama_model}' not found on server. "
                        f"Available: {available}"
                    )
                    # Fall through to auto-detection
            else:
                logger.warning("Could not reach Ollama to validate model. Keeping configured model.")
                return

        # Auto-detect: pick the first available model
        logger.info("No valid model configured — attempting auto-detection...")
        data = await self.ollama_get("/api/tags")
        if not data:
            logger.error("Cannot reach Ollama server for model auto-detection.")
            self.ollama_model = ""
            return

        models = data.get("models", [])
        if not models:
            logger.error(
                "No models available on the Ollama server. "
                "Pull a model first with: ollama pull <model-name>"
            )
            self.ollama_model = ""
            return

        first_model = models[0].get("name", "")
        logger.info(f"Auto-detected model: '{first_model}'")
        self.ollama_model = first_model

    async def run(self):
        """Main polling loop."""
        await self.wait_for_api()
        await self.auto_detect_model()
        logger.info(f"Bot is running — polling for messages... (model: {self.ollama_model or 'NONE'})")

        while True:
            try:
                messages = await self.receive_messages()
                for msg in messages:
                    envelope = msg.get("envelope", {})
                    await self.handle_message(envelope)
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")

            await asyncio.sleep(1)

    async def stop(self):
        """Clean up."""
        await self.client.aclose()


async def main():
    phone_number = os.getenv("SIGNAL_PHONE_NUMBER")
    signal_api_url = os.getenv("SIGNAL_API_URL", "http://signal-api:8080")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "")
    system_prompt = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")
    allowed_senders = os.getenv("ALLOWED_SENDERS", "*")

    if not phone_number:
        logger.error("SIGNAL_PHONE_NUMBER is required. Set it in .env")
        sys.exit(1)

    bot = OllamaSignalBot(
        phone_number=phone_number,
        signal_api_url=signal_api_url,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        system_prompt=system_prompt,
        allowed_senders=allowed_senders,
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())