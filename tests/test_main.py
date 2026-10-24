"""Tests for the Ollama Signal Bot's pure logic (no Docker/network needed)."""

import asyncio

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
