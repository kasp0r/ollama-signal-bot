"""Web UI for the Ollama Signal Bot.

Serves a single-page admin interface plus a JSON API:
  GET  /            - the page
  GET  /api/status  - bot + dependency status (signal-api, Ollama, account)
  GET  /api/link/qr - QR code image for linking the Signal account
  GET  /api/config  - current runtime config
  PUT  /api/config  - update runtime config

Runs in the bot's asyncio loop.
"""

import json
import urllib.parse

from aiohttp import web

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ollama Signal Bot</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 640px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.4; }
  h1 { font-size: 1.35rem; margin-bottom: .25rem; }
  .sub { color: #666; margin-top: 0; }
  h2 { font-size: 1rem; margin-top: 1.75rem; border-bottom: 1px solid #eee; padding-bottom: .35rem; }
  .status-row { display: flex; align-items: center; gap: .5rem; padding: .3rem 0; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
  .dot.ok { background: #188038; }
  .dot.bad { background: #b00020; }
  .dot.wait { background: #e37400; }
  .muted { color: #888; }
  #link-section { background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 6px; padding: 1rem; }
  #qr-img { width: 200px; height: 200px; }
  label { display: block; margin-top: 1rem; font-weight: 600; font-size: .9rem; }
  input, textarea { width: 100%; padding: .5rem; margin-top: .25rem; box-sizing: border-box;
                    font-size: .95rem; border: 1px solid #ccc; border-radius: 4px; }
  textarea { min-height: 4.5rem; resize: vertical; }
  .hint { color: #888; font-size: .8rem; margin-top: .2rem; }
  button { margin-top: 1rem; padding: .55rem 1.2rem; font-size: .95rem;
           background: #1a73e8; color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
  button.secondary { background: #444; }
  #token-row { display: none; }
  #message { margin-top: 1rem; font-weight: 600; }
  #message.ok { color: #188038; }
  #message.err { color: #188038; color: #b00020; }
  code { background: #f2f2f2; padding: .1rem .3rem; border-radius: 3px; }
</style>
</head>
<body>
<h1>Ollama Signal Bot</h1>
<p class="sub">Configure and monitor the bot. Changes apply immediately and persist across restarts.</p>

<div id="token-row">
  <label for="token">Access token</label>
  <input id="token" type="password" placeholder="Enter WEBUI_TOKEN">
  <button type="button" class="secondary" onclick="saveToken()">Unlock</button>
</div>

<h2>Status</h2>
<div id="status">
  <div class="status-row"><span class="dot" id="dot-signal"></span> Signal API <span class="muted" id="status-signal">checking…</span></div>
  <div class="status-row"><span class="dot" id="dot-ollama"></span> Ollama <span class="muted" id="status-ollama">checking…</span></div>
  <div class="status-row"><span class="dot" id="dot-account"></span> Signal account <span class="muted" id="status-account">checking…</span></div>
  <div class="status-row"><span class="dot ok" style="background:#555"></span> Model <span class="muted" id="status-model">—</span></div>
</div>

<div id="link-section" style="display:none">
  <h2>Link your Signal account</h2>
  <p>Scan this QR code with the Signal app registered on the bot's number
     (<strong>Settings → Linked Devices → +</strong>).</p>
  <img id="qr-img" alt="QR code">
  <p><button type="button" class="secondary" onclick="loadQR()">Generate new QR code</button></p>
</div>

<h2>Configuration</h2>
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

function setDot(id, state) {
  const el = document.getElementById(id);
  el.className = 'dot ' + state;
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

function renderStatus(s) {
  const d = s.dependencies || {};

  setDot('dot-signal', d.signal_api && d.signal_api.ok ? 'ok' : 'bad');
  document.getElementById('status-signal').textContent =
    d.signal_api && d.signal_api.ok ? ('v' + d.signal_api.version) : 'offline';

  setDot('dot-ollama', d.ollama && d.ollama.ok ? 'ok' : 'bad');
  document.getElementById('status-ollama').textContent =
    d.ollama && d.ollama.ok ? (d.ollama.models + ' models') : 'offline';

  const linked = d.account && d.account.linked;
  setDot('dot-account', linked ? 'ok' : 'wait');
  document.getElementById('status-account').textContent =
    linked ? d.account.phone_number : 'not linked';

  document.getElementById('status-model').textContent = s.model || 'none';

  // Show the linking section only when the account isn't linked.
  const linkSection = document.getElementById('link-section');
  if (linked) {
    linkSection.style.display = 'none';
  } else {
    linkSection.style.display = 'block';
  }
}

async function refreshStatus() {
  try {
    const r = await fetch('/api/status', {headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) return;
    const s = await r.json();
    renderStatus(s);
    fillForm(s);
    hideToken();
  } catch (e) { /* transient */ }
}

async function loadQR() {
  try {
    const r = await fetch('/api/link/qr', {headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { showMessage('Could not generate QR code', true); return; }
    const blob = await r.blob();
    document.getElementById('qr-img').src = URL.createObjectURL(blob);
  } catch (e) { showMessage('Could not generate QR code: ' + e, true); }
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
    const r = await fetch('/api/config', {method: 'PUT', headers: headers(), body: JSON.stringify(payload)});
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
  refreshStatus();
  loadQR();
}

refreshStatus();
loadQR();
setInterval(refreshStatus, 3000);
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


async def _status(request):
    bot = request.app[_BOT_KEY]
    status = bot.get_status()
    status["dependencies"] = await bot.check_dependencies()
    return web.json_response(status)


async def _link_qr(request):
    bot = request.app[_BOT_KEY]
    device_name = urllib.parse.quote("Ollama Signal Bot")
    url = f"{bot.signal_api_url}/v1/qrcodelink?device_name={device_name}"
    try:
        resp = await bot.client.get(url, timeout=15.0)
        if resp.status_code != 200:
            return web.json_response({"error": "could not generate QR code"}, status=502)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)
    return web.Response(body=resp.content, content_type="image/png")


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


def create_app(bot, token=None):
    app = web.Application(middlewares=[_auth_middleware])
    app[_BOT_KEY] = bot
    app[_TOKEN_KEY] = token or ""
    app.router.add_get("/", _index)
    app.router.add_get("/api/status", _status)
    app.router.add_get("/api/link/qr", _link_qr)
    app.router.add_get("/api/config", _get_config)
    app.router.add_put("/api/config", _put_config)
    return app


async def start_server(bot, host, port, token=None):
    """Start the web UI and return an async cleanup function."""
    runner = web.AppRunner(create_app(bot, token))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner.cleanup
