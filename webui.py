"""Web UI for runtime configuration of the Ollama Signal Bot.

Serves a small single-page admin interface plus a JSON API
(GET/PUT /api/config, GET /api/status). The bot runs this in the same
asyncio loop as its message polling.
"""

import json

from aiohttp import web

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ollama Signal Bot</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 620px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.4; }
  h1 { font-size: 1.35rem; }
  .sub { color: #666; margin-top: -.5rem; }
  label { display: block; margin-top: 1rem; font-weight: 600; font-size: .9rem; }
  input, textarea { width: 100%; padding: .5rem; margin-top: .25rem;
                    box-sizing: border-box; font-size: .95rem; border: 1px solid #ccc; border-radius: 4px; }
  textarea { min-height: 4.5rem; resize: vertical; }
  .hint { color: #888; font-size: .8rem; margin-top: .2rem; }
  button { margin-top: 1.25rem; padding: .6rem 1.4rem; font-size: 1rem;
           background: #1a73e8; color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
  #token-row { display: none; margin-top: 1rem; }
  #message { margin-top: 1rem; font-weight: 600; }
  #message.ok { color: #188038; }
  #message.err { color: #b00020; }
</style>
</head>
<body>
<h1>Ollama Signal Bot</h1>
<p class="sub">Configure the bot at runtime — changes apply immediately and persist across restarts.</p>

<div id="token-row">
  <label for="token">Access token</label>
  <input id="token" type="password" placeholder="Enter WEBUI_TOKEN">
  <button type="button" onclick="saveToken()">Unlock</button>
</div>

<form id="form" onsubmit="saveConfig(event)">
  <label for="ollama_model">Model</label>
  <input id="ollama_model" type="text">
  <div class="hint">Leave empty to auto-detect the first available model.</div>

  <label for="temperature">Temperature</label>
  <input id="temperature" type="number" step="0.1" min="0" max="2">

  <label for="system_prompt">System prompt</label>
  <textarea id="system_prompt"></textarea>

  <label for="max_history">Max history (message pairs)</label>
  <input id="max_history" type="number" min="1">

  <label for="allowed_senders">Allowed senders</label>
  <input id="allowed_senders" type="text">
  <div class="hint"><code>*</code> = everyone, or comma-separated numbers.</div>

  <label for="allowed_admins">Allowed admins</label>
  <input id="allowed_admins" type="text">
  <div class="hint"><code>*</code> = every allowed sender, or comma-separated numbers.</div>

  <button type="submit">Save changes</button>
</form>
<div id="message"></div>

<script>
const TOKEN_KEY = 'osb_token';
let token = localStorage.getItem(TOKEN_KEY) || '';

function headers() {
  const h = {'Content-Type': 'application/json'};
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

function showMessage(text, isError) {
  const m = document.getElementById('message');
  m.textContent = text;
  m.className = isError ? 'err' : 'ok';
}

function showToken() { document.getElementById('token-row').style.display = 'block'; }
function hideToken() { document.getElementById('token-row').style.display = 'none'; }

function fillForm(cfg) {
  document.getElementById('ollama_model').value = cfg.ollama_model || '';
  document.getElementById('temperature').value = cfg.temperature ?? 0.7;
  document.getElementById('system_prompt').value = cfg.system_prompt || '';
  document.getElementById('max_history').value = cfg.max_history ?? 50;
  document.getElementById('allowed_senders').value = cfg.allowed_senders || '*';
  document.getElementById('allowed_admins').value = cfg.allowed_admins || '*';
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config', {headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { showMessage('Failed to load config', true); return; }
    fillForm(await r.json());
    hideToken();
  } catch (e) { showMessage('Failed to load config: ' + e, true); }
}

async function saveConfig(e) {
  e.preventDefault();
  const payload = {
    ollama_model: document.getElementById('ollama_model').value.trim(),
    temperature: parseFloat(document.getElementById('temperature').value),
    system_prompt: document.getElementById('system_prompt').value,
    max_history: parseInt(document.getElementById('max_history').value, 10),
    allowed_senders: document.getElementById('allowed_senders').value.trim() || '*',
    allowed_admins: document.getElementById('allowed_admins').value.trim() || '*',
  };
  try {
    const r = await fetch('/api/config', {
      method: 'PUT', headers: headers(), body: JSON.stringify(payload),
    });
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      showMessage(d.error || 'Save failed', true);
      return;
    }
    showMessage('Saved', false);
  } catch (e) { showMessage('Save failed: ' + e, true); }
}

function saveToken() {
  token = document.getElementById('token').value.trim();
  localStorage.setItem(TOKEN_KEY, token);
  loadConfig();
}

loadConfig();
</script>
</body>
</html>
"""


_BOT_KEY = web.AppKey("bot", object)
_TOKEN_KEY = web.AppKey("token", str)


@web.middleware
async def _auth_middleware(request, handler):
    token = request.app[_TOKEN_KEY]
    if token:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {token}" and request.query.get("token") != token:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def _index(request):
    return web.Response(text=HTML, content_type="text/html")


async def _get_config(request):
    return web.json_response(request.app[_BOT_KEY].get_runtime_config())


async def _put_config(request):
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not isinstance(data, dict):
        return web.json_response({"error": "expected a JSON object"}, status=400)

    try:
        request.app[_BOT_KEY].apply_runtime_config(data)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(request.app[_BOT_KEY].get_runtime_config())


async def _status(request):
    return web.json_response(request.app[_BOT_KEY].get_status())


def create_app(bot, token=None):
    app = web.Application(middlewares=[_auth_middleware])
    app[_BOT_KEY] = bot
    app[_TOKEN_KEY] = token or ""
    app.router.add_get("/", _index)
    app.router.add_get("/api/config", _get_config)
    app.router.add_put("/api/config", _put_config)
    app.router.add_get("/api/status", _status)
    return app


async def start_server(bot, host, port, token=None):
    """Start the web UI and return an async cleanup function."""
    runner = web.AppRunner(create_app(bot, token))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner.cleanup
