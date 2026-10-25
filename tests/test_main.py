"""Tests for the Ollama Signal Bot.

Pure logic is tested directly; network calls are mocked via httpx.MockTransport.
"""

import asyncio
import json

import httpx

import main


# ── format_for_signal (Markdown → plain text) ─────────────────────

def test_bold():
    assert main.format_for_signal("**hello**") == "hello"


def test_italic():
    assert main.format_for_signal("*hello*") == "hello"


def test_bold_italic():
    assert main.format_for_signal("***hello***") == "hello"


def test_inline_code():
    assert main.format_for_signal("use `ls -la` here") == "use ls -la here"


def test_code_block():
    result = main.format_for_signal("```python\nprint('hi')\n```")
    assert "print('hi')" in result
    assert "```" not in result


def test_header():
    assert main.format_for_signal("## Heading") == "HEADING"


def test_link():
    assert main.format_for_signal("[text](https://example.com)") == "text (https://example.com)"


def test_image():
    assert main.format_for_signal("![alt](https://x/y.png)") == "[Image: alt]"


def test_unordered_list():
    assert main.format_for_signal("- item") == "• item"


def test_ordered_list():
    assert main.format_for_signal("1. first") == "first"


def test_blockquote():
    assert main.format_for_signal("> quote") == "│ quote"


def test_strikethrough():
    assert main.format_for_signal("~~gone~~") == "gone"


def test_horizontal_rule():
    assert "─" in main.format_for_signal("---")


def test_snake_case_not_italicized():
    # Underscores between word characters must not be treated as italics.
    assert "snake_case" in main.format_for_signal("snake_case")


# ── sender allowlist ──────────────────────────────────────────────

def _make_bot(allowed_senders="*"):
    return main.OllamaSignalBot(
        phone_number="+15551234567",
        signal_api_url="http://signal-api:8080",
        ollama_url="http://ollama:11434",
        allowed_senders=allowed_senders,
    )


def test_allowlist_open():
    bot = _make_bot("*")
    assert bot.is_sender_allowed("+19998887777") is True


def test_allowlist_empty_defaults_to_open():
    bot = _make_bot("")
    assert bot.is_sender_allowed("+19998887777") is True


def test_allowlist_specific():
    bot = _make_bot("+11111111111,+22222222222")
    assert bot.is_sender_allowed("+11111111111") is True
    assert bot.is_sender_allowed("+22222222222") is True
    assert bot.is_sender_allowed("+99999999999") is False


# ── telemetry formatting ──────────────────────────────────────────

def test_telemetry_format():
    bot = _make_bot()
    result = {
        "model": "gemma4:latest",
        "total_duration": 1_610_000_000,
        "load_duration": 20_000_000,
        "prompt_eval_count": 142,
        "prompt_eval_duration": 350_000_000,
        "eval_count": 87,
        "eval_duration": 1_240_000_000,
    }
    telemetry = bot._format_telemetry(result)
    assert "gemma4:latest" in telemetry
    assert "Input tokens: 142" in telemetry
    assert "Output tokens: 87" in telemetry


# ── offline slash commands ────────────────────────────────────────

def test_cmd_help():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/help"))
    assert "/help" in resp
    assert "/reset" in resp
    assert "/verbose" in resp
    assert "/recent" in resp
    assert "/config" in resp


def test_cmd_reset():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/reset"))
    assert "cleared" in resp


def test_cmd_maxhistory_no_args():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/maxhistory"))
    assert "50" in resp  # default MAX_HISTORY


def test_unknown_command():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/nope"))
    assert "Unknown command" in resp


# ── Ollama query flow (mocked network) ────────────────────────────

def _mock_bot(handler):
    """Create a bot whose httpx client uses a mocked transport."""
    bot = _make_bot()
    bot.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return bot


def _ollama_ok(request):
    return httpx.Response(200, json={
        "model": "gemma4:latest",
        "message": {"content": "Hi there!"},
        "total_duration": 1_000_000_000,
        "load_duration": 10_000_000,
        "prompt_eval_count": 5,
        "prompt_eval_duration": 100_000_000,
        "eval_count": 3,
        "eval_duration": 200_000_000,
    })


def test_query_ollama_success():
    bot = _mock_bot(_ollama_ok)
    resp = asyncio.run(bot.query_ollama("+123", "hello"))
    assert resp == "Hi there!"
    assert [m["role"] for m in bot.conversations["+123"]] == ["user", "assistant"]


def test_query_ollama_no_model():
    bot = _make_bot()
    bot.ollama_model = ""
    resp = asyncio.run(bot.query_ollama("+123", "hi"))
    assert "No model is currently loaded" in resp


def test_query_ollama_http_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    bot = _mock_bot(handler)
    resp = asyncio.run(bot.query_ollama("+123", "hi"))
    assert "Error communicating with Ollama" in resp


def test_query_ollama_history_bounded():
    bot = _mock_bot(_ollama_ok)
    bot.max_history = 1
    for msg in ["first", "second", "third", "fourth"]:
        asyncio.run(bot.query_ollama("+123", msg))
    history = bot.conversations["+123"]
    assert len(history) <= 3  # bounded to roughly max_history pairs
    assert history[-2]["content"] == "fourth"  # latest user message retained


# ── Signal messaging (mocked network) ─────────────────────────────

def test_send_message_chunks_long_messages():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    bot = _mock_bot(handler)
    asyncio.run(bot.send_message("+123", "x" * 5000))

    assert len(sent) == 2
    assert all(len(m["message"]) <= 4096 for m in sent)
    assert all(m["recipients"] == ["+123"] for m in sent)
    assert all(m["number"] == "+15551234567" for m in sent)


def test_receive_messages_account_not_registered():
    def handler(request):
        return httpx.Response(400, json={})

    bot = _mock_bot(handler)
    assert asyncio.run(bot.receive_messages()) == []


def test_receive_messages_timeout():
    def handler(request):
        raise httpx.TimeoutException("timed out")

    bot = _mock_bot(handler)
    assert asyncio.run(bot.receive_messages()) == []


# ── slash-command argument validation ─────────────────────────────

def test_maxhistory_invalid_number():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/maxhistory abc"))
    assert "valid integer" in resp


def test_maxhistory_too_low():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/maxhistory 0"))
    assert "at least 1" in resp


def test_maxhistory_too_high():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/maxhistory 10001"))
    assert "cannot exceed" in resp


def test_maxhistory_set():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/maxhistory 25"))
    assert "25" in resp
    assert bot.max_history == 25


def test_verbose_toggle():
    bot = _make_bot()
    resp_on = asyncio.run(bot.handle_command("+123", "/verbose"))
    assert "enabled" in resp_on
    assert "+123" in bot.verbose_users
    resp_off = asyncio.run(bot.handle_command("+123", "/verbose"))
    assert "disabled" in resp_off
    assert "+123" not in bot.verbose_users


def test_history_empty():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/history"))
    assert "No conversation history" in resp


def test_model_no_args():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/model"))
    assert "gemma4:latest" in resp


# ── format_for_signal edge cases ──────────────────────────────────

def test_format_empty():
    assert main.format_for_signal("") == ""


def test_format_collapses_blank_lines():
    assert main.format_for_signal("a\n\n\n\nb") == "a\n\nb"


def test_image_no_alt():
    assert main.format_for_signal("![](https://x/y.png)") == "[Image: ]"


# ── /recent and /config commands ──────────────────────────────────

def test_recent_empty():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/recent"))
    assert "No conversation yet" in resp


def test_recent_shows_history():
    bot = _make_bot()
    bot.conversations["+123"] = [
        {"role": "user", "content": "hello there"},
        {"role": "assistant", "content": "hi, how can I help?"},
    ]
    resp = asyncio.run(bot.handle_command("+123", "/recent"))
    assert "hello there" in resp
    assert "how can I help" in resp
    assert "You" in resp
    assert "Bot" in resp


def test_recent_invalid_number():
    bot = _make_bot()
    bot.conversations["+123"] = [{"role": "user", "content": "x"}]
    resp = asyncio.run(bot.handle_command("+123", "/recent abc"))
    assert "valid number" in resp


def test_recent_too_low():
    bot = _make_bot()
    bot.conversations["+123"] = [{"role": "user", "content": "x"}]
    resp = asyncio.run(bot.handle_command("+123", "/recent 0"))
    assert "at least 1" in resp


def test_recent_caps_at_20():
    bot = _make_bot()
    bot.conversations["+123"] = [
        {"role": "user", "content": f"message number {i}"} for i in range(25)
    ]
    resp = asyncio.run(bot.handle_command("+123", "/recent 999"))
    assert "message number 24" in resp
    assert "message number 0" not in resp


def test_config():
    bot = _make_bot()
    resp = asyncio.run(bot.handle_command("+123", "/config"))
    assert "gemma4:latest" in resp
    assert "OPEN" in resp
    assert "50 pairs" in resp
