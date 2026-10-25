"""Tests for the Ollama Signal Bot.

Pure logic is tested directly; network calls are mocked via httpx.MockTransport.
"""

import asyncio
import json

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer

import main
import webui


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

def _make_bot(allowed_senders="*", allowed_admins="*", temperature=main.DEFAULT_TEMPERATURE, config_file="/tmp/osb-test-config.json"):
    return main.OllamaSignalBot(
        phone_number="+15551234567",
        signal_api_url="http://signal-api:8080",
        ollama_url="http://ollama:11434",
        allowed_senders=allowed_senders,
        allowed_admins=allowed_admins,
        temperature=temperature,
        config_file=config_file,
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


# ── security controls ─────────────────────────────────────────────

def test_admin_open_default():
    bot = _make_bot()
    assert bot.is_admin("+123") is True


def test_admin_specific():
    bot = _make_bot(allowed_admins="+111")
    assert bot.is_admin("+111") is True
    assert bot.is_admin("+222") is False


def test_model_change_requires_admin():
    bot = _make_bot(allowed_admins="+111")
    resp = asyncio.run(bot.handle_command("+222", "/model gemma4:latest"))
    assert "admin" in resp


def test_model_show_allowed_for_non_admin():
    bot = _make_bot(allowed_admins="+111")
    resp = asyncio.run(bot.handle_command("+222", "/model"))
    assert "gemma4:latest" in resp


def test_maxhistory_change_requires_admin():
    bot = _make_bot(allowed_admins="+111")
    resp = asyncio.run(bot.handle_command("+222", "/maxhistory 25"))
    assert "admin" in resp


def test_config_requires_admin():
    bot = _make_bot(allowed_admins="+111")
    resp = asyncio.run(bot.handle_command("+222", "/config"))
    assert "admin" in resp


def test_rate_limiting():
    bot = _make_bot()
    for _ in range(main.RATE_LIMIT_MESSAGES):
        assert bot.is_rate_limited("+123") is False
    assert bot.is_rate_limited("+123") is True


def test_query_ollama_caps_output():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "x" * 5000}})

    bot = _mock_bot(handler)
    resp = asyncio.run(bot.query_ollama("+123", "hi"))
    assert len(resp) == main.MAX_OUTPUT_LENGTH + 1  # +1 for the ellipsis
    assert resp.endswith("…")


def test_handle_message_caps_input():
    chat_payloads = []

    def handler(request):
        if request.url.path == "/api/chat":
            chat_payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": "ok"}})
        return httpx.Response(200, json={})

    bot = _mock_bot(handler)
    envelope = {"source": "+123", "dataMessage": {"message": "y" * 6000}}
    asyncio.run(bot.handle_message(envelope))
    assert len(chat_payloads[0]["messages"][-1]["content"]) == main.MAX_INPUT_LENGTH


# ── group handling and generation options ────────────────────────

def test_handle_message_ignores_group():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    bot = _mock_bot(handler)
    envelope = {
        "source": "+123",
        "dataMessage": {"message": "hello", "groupInfo": {"groupId": "abc"}},
    }
    asyncio.run(bot.handle_message(envelope))
    assert requests == []  # no typing, no send, no Ollama query


def test_query_ollama_sends_generation_options():
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    bot = _mock_bot(handler)
    asyncio.run(bot.query_ollama("+123", "hi"))
    options = payloads[0].get("options", {})
    assert options["num_predict"] == main.MAX_OUTPUT_TOKENS
    assert options["temperature"] == main.DEFAULT_TEMPERATURE


def test_temperature_configurable():
    bot = _make_bot(temperature=0.3)
    assert bot.temperature == 0.3


# ── runtime config (web UI) ───────────────────────────────────────

def test_get_runtime_config():
    bot = _make_bot()
    cfg = bot.get_runtime_config()
    assert cfg["ollama_model"] == "gemma4:latest"
    assert cfg["ollama_url"] == "http://ollama:11434"
    assert cfg["temperature"] == 0.7
    assert cfg["allowed_senders"] == "*"
    assert cfg["max_history"] == 50


def test_senders_roundtrip():
    bot = _make_bot()
    bot.allowed_senders = {"+111", "+222"}
    assert bot._senders_to_str(bot.allowed_senders) == "+111,+222"
    assert bot._str_to_senders("+111,+222") == {"+111", "+222"}
    assert bot._str_to_senders("*") is None


def test_apply_runtime_config():
    bot = _make_bot()
    bot.apply_runtime_config({
        "ollama_model": "llama3.2:latest",
        "temperature": 0.3,
        "max_history": 100,
        "allowed_senders": "+111",
    })
    assert bot.ollama_model == "llama3.2:latest"
    assert bot.temperature == 0.3
    assert bot.max_history == 100
    assert bot.allowed_senders == {"+111"}


def test_apply_runtime_config_validation():
    bot = _make_bot()
    with pytest.raises(ValueError):
        bot.apply_runtime_config({"temperature": 5.0})
    with pytest.raises(ValueError):
        bot.apply_runtime_config({"max_history": 0})


def test_apply_runtime_config_ollama_url():
    bot = _make_bot()
    bot.apply_runtime_config({"ollama_url": "http://192.168.1.50:11434"})
    assert bot.ollama_url == "http://192.168.1.50:11434"


def test_apply_runtime_config_invalid_ollama_url():
    bot = _make_bot()
    with pytest.raises(ValueError):
        bot.apply_runtime_config({"ollama_url": "not-a-url"})


def test_get_available_models():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "a"}, {"name": "b"}]})

    bot = _mock_bot(handler)
    assert asyncio.run(bot.get_available_models()) == ["a", "b"]


def test_config_persistence(tmp_path):
    cfg = tmp_path / "config.json"
    bot = _make_bot(config_file=str(cfg))
    bot.apply_runtime_config({"ollama_model": "custom", "temperature": 0.2, "max_history": 42})

    bot2 = _make_bot(config_file=str(cfg))
    bot2.load_runtime_config()
    assert bot2.ollama_model == "custom"
    assert bot2.temperature == 0.2
    assert bot2.max_history == 42


def test_load_runtime_config_skips_blank_values(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"ollama_model": "", "system_prompt": "", "temperature": 0.3}))
    bot = _make_bot(config_file=str(cfg))
    bot.load_runtime_config()
    # blank strings must not wipe the env/default values
    assert bot.ollama_model == "gemma4:latest"
    assert bot.system_prompt == "You are a helpful assistant."
    # non-blank values still apply
    assert bot.temperature == 0.3


def test_get_status():
    bot = _make_bot()
    status = bot.get_status()
    assert status["model"] == "gemma4:latest"
    assert "uptime_seconds" in status
    assert status["active_chats"] == 0
    assert status["last_message_at"] is None
    assert status["last_message_sender"] is None


def test_last_message_tracking():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "ok"}})

    bot = _mock_bot(handler)
    assert bot.last_message_at is None
    envelope = {"source": "+123", "dataMessage": {"message": "hi"}}
    asyncio.run(bot.handle_message(envelope))
    assert bot.last_message_at is not None
    assert bot.last_message_sender == "+123"


def test_webui_get_config():
    bot = _make_bot()

    async def run():
        server = TestServer(webui.create_app(bot))
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get("/api/config")
            assert resp.status == 200
            data = await resp.json()
            assert data["ollama_model"] == "gemma4:latest"
        finally:
            await client.close()

    asyncio.run(run())


def test_webui_put_config():
    bot = _make_bot()

    async def run():
        server = TestServer(webui.create_app(bot))
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.put("/api/config", json={"temperature": 0.5})
            assert resp.status == 200
            assert (await resp.json())["temperature"] == 0.5
            assert bot.temperature == 0.5
        finally:
            await client.close()

    asyncio.run(run())


def test_webui_auth():
    bot = _make_bot()

    async def run():
        server = TestServer(webui.create_app(bot, token="secret"))
        client = TestClient(server)
        await client.start_server()
        try:
            assert (await client.get("/api/config")).status == 401
            ok = await client.get("/api/config", headers={"Authorization": "Bearer secret"})
            assert ok.status == 200
        finally:
            await client.close()

    asyncio.run(run())


# ── dependency checks ────────────────────────────────────────────

def test_check_dependencies():
    def handler(request):
        if request.url.path == "/v1/about":
            return httpx.Response(200, json={"version": "0.101"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "a"}, {"name": "b"}]})
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json=["+15551234567"])
        return httpx.Response(404)

    bot = _mock_bot(handler)
    deps = asyncio.run(bot.check_dependencies())
    assert deps["signal_api"]["ok"] is True
    assert deps["signal_api"]["version"] == "0.101"
    assert deps["ollama"]["ok"] is True
    assert deps["ollama"]["models"] == 2
    assert deps["account"]["linked"] is True
    assert deps["account"]["phone_number"] == "+15551234567"


def test_check_dependencies_offline():
    def handler(request):
        return httpx.Response(500)

    bot = _mock_bot(handler)
    deps = asyncio.run(bot.check_dependencies())
    assert deps["signal_api"]["ok"] is False
    assert deps["ollama"]["ok"] is False
    assert deps["account"]["linked"] is False


def test_webui_status():
    def handler(request):
        if request.url.path == "/v1/about":
            return httpx.Response(200, json={"version": "0.101"})
        return httpx.Response(200, json=[])

    bot = _mock_bot(handler)

    async def run():
        server = TestServer(webui.create_app(bot))
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get("/api/status")
            assert resp.status == 200
            data = await resp.json()
            assert data["dependencies"]["signal_api"]["ok"] is True
            assert data["dependencies"]["account"]["linked"] is False
        finally:
            await client.close()

    asyncio.run(run())
