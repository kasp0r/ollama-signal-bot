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
  input, textarea, select { width: 100%; padding: .5rem; margin-top: .25rem; box-sizing: border-box;
                    font-size: .95rem; border: 1px solid #ccc; border-radius: 4px; }
  textarea { min-height: 4.5rem; resize: vertical; }
  .hint { color: #888; font-size: .8rem; margin-top: .2rem; }
  button { margin-top: 1rem; padding: .55rem 1.2rem; font-size: .95rem;
           background: #1a73e8; color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
  button.secondary { background: #444; }
  button.danger { background: #b00020; }
  #token-row { display: none; }
  #message { margin-top: 1rem; font-weight: 600; }
  #message.ok { color: #188038; }
  #message.err { color: #188038; color: #b00020; }
  code { background: #f2f2f2; padding: .1rem .3rem; border-radius: 3px; }
  body.dark { background: #1a1a1a; color: #e6e6e6; }
  body.dark .sub, body.dark .hint, body.dark .muted { color: #999; }
  body.dark h2 { border-bottom-color: #333; }
  body.dark input, body.dark textarea, body.dark select { background: #2a2a2a; color: #e6e6e6; border-color: #444; }
  body.dark #link-section { background: #242424; border-color: #333; }
  body.dark code { background: #2a2a2a; }
  .theme-toggle { position: fixed; bottom: 1rem; right: 1rem; padding: .5rem .8rem; background: #444; color: #fff; border: 0; border-radius: 4px; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.3); z-index: 10; }
  .tabs { display: flex; gap: .25rem; margin-top: 1rem; border-bottom: 1px solid #ccc; }
  .tab { padding: .5rem 1rem; background: transparent; border: 0; cursor: pointer; color: inherit; font-size: .95rem; border-bottom: 2px solid transparent; }
  .tab.active { border-bottom-color: #1a73e8; font-weight: 600; }
  body.dark .tabs { border-bottom-color: #444; }
</style>
</head>
<body>
<h1>Ollama Signal Bot</h1>
<p class="sub">Configure and monitor the bot. Changes apply immediately and persist across restarts.</p>
<button type="button" class="theme-toggle" onclick="toggleTheme()">🌙 Toggle dark mode</button>

<div id="token-row">
  <label for="token">Access token</label>
  <input id="token" type="password" placeholder="Enter WEBUI_TOKEN">
  <button type="button" class="secondary" onclick="saveToken()">Unlock</button>
</div>

<div class="tabs">
  <button class="tab active" data-tab="overview" onclick="switchTab('overview')">Overview</button>
  <button class="tab" data-tab="conversations" onclick="switchTab('conversations')">Conversations</button>
  <button class="tab" data-tab="settings" onclick="switchTab('settings')">Settings</button>
</div>

<div id="tab-overview" class="tab-content">
<h2>Status</h2>
<div id="status">
  <div class="status-row"><span class="dot" id="dot-signal"></span> Signal API <span class="muted" id="status-signal">checking…</span></div>
  <div class="status-row"><span class="dot" id="dot-ollama"></span> Ollama <span class="muted" id="status-ollama">checking…</span></div>
  <div class="status-row"><span class="dot" id="dot-account"></span> Signal account <span class="muted" id="status-account">checking…</span></div>
  <div class="status-row"><span class="dot ok" style="background:#555"></span> Model <span class="muted" id="status-model">—</span></div>
  <div class="status-row"><span class="dot ok" style="background:#555"></span> Last message <span class="muted" id="status-last">—</span></div>
</div>

<div class="status-row">
  <button type="button" class="secondary" onclick="unlinkAccount()">Relink to another Signal account</button>
</div>

<h2>Stats</h2>
<div id="stats">
  <div class="status-row"><span class="muted">Total messages:</span> <span id="stat-messages">—</span></div>
  <div class="status-row"><span class="muted">Active users:</span> <span id="stat-users">—</span></div>
  <div class="status-row"><span class="muted">Tokens in / out:</span> <span id="stat-tokens">—</span></div>
</div>

<div id="link-section" style="display:none">
  <h2>Link your Signal account</h2>
  <p>Scan this QR code with the Signal app registered on the bot's number
     (<strong>Settings → Linked Devices → +</strong>).</p>
  <img id="qr-img" alt="QR code">
  <p><button type="button" class="secondary" onclick="loadQR()">Generate new QR code</button></p>
</div>
</div>

<div id="tab-conversations" class="tab-content" style="display:none">
<h2>Conversations</h2>
<div id="conversations" class="muted">loading…</div>
</div>

<div id="tab-settings" class="tab-content" style="display:none">
<h2>Configuration</h2>
<form id="form" onsubmit="saveConfig(event)">
  <label for="signal_api_url">Signal API URL</label>
  <input id="signal_api_url" type="text">
  <div class="hint">Defaults to the bundled signal-api (<code>http://signal-api:8080</code>), or point at a remote one.</div>

  <label for="ollama_url">Ollama URL</label>
  <input id="ollama_url" type="text">
  <div class="hint">Local or remote Ollama server, e.g. <code>http://host.docker.internal:11434</code>.</div>

  <label for="ollama_model">Model</label>
  <select id="ollama_model">
    <option value="">Auto-detect</option>
  </select>
  <div class="hint">Auto-detects the first available model, or pick one.</div>

  <label for="pull_model">Pull model</label>
  <div style="display:flex; gap:.5rem;">
    <input id="pull_model" type="text" placeholder="e.g. llama3.2:latest">
    <button type="button" class="secondary" onclick="pullModel()">Pull</button>
  </div>
  <div class="hint">Downloads a model into Ollama (may take a while for large models).</div>

  <label for="temperature">Temperature</label>
  <input id="temperature" type="number" step="0.1" min="0" max="2">

  <label for="num_predict">Max tokens (num_predict)</label>
  <input id="num_predict" type="number" min="1">
  <div class="hint">Maximum tokens to generate per reply (default 1024).</div>

  <label for="top_p">Top P</label>
  <input id="top_p" type="number" step="0.05" min="0" max="1">
  <div class="hint">Nucleus sampling (0.0-1.0, default 0.9).</div>

  <label for="top_k">Top K</label>
  <input id="top_k" type="number" min="1">
  <div class="hint">Top-k sampling (default 40).</div>

  <label for="system_prompt">System prompt</label>
  <textarea id="system_prompt"></textarea>

  <label for="max_history">Max history (message pairs)</label>
  <input id="max_history" type="number" min="1">

  <label for="allowed_senders">Allowed senders</label>
  <input id="allowed_senders" type="text">
  <div class="hint">Examples: <code>*</code> = everyone · <code>+15551234567</code> = one user · <code>+15551234567,+15559876543</code> = multiple users.</div>

  <label for="allowed_admins">Allowed admins</label>
  <input id="allowed_admins" type="text">
  <div class="hint"><code>*</code> = every allowed sender, or comma-separated numbers.</div>

  <button type="submit">Save changes</button>
  <button type="button" class="secondary" onclick="resetConfig()">Reset to default settings</button>
</form>

<h2>Danger zone</h2>
<button type="button" class="danger" onclick="resetAll()">Reset entire installation</button>
<div class="hint">Unlinks the Signal account, clears all conversation history, and resets settings to defaults.</div>
</div>

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

function setModelSelect(value) {
  const sel = document.getElementById('ollama_model');
  if (!value) { sel.value = ''; return; }
  let found = false;
  for (const opt of sel.options) { if (opt.value === value) { found = true; break; } }
  if (!found) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = value;
    sel.appendChild(opt);
  }
  sel.value = value;
}

function fillForm(cfg) {
  document.getElementById('signal_api_url').value = cfg.signal_api_url || '';
  document.getElementById('ollama_url').value = cfg.ollama_url || '';
  setModelSelect(cfg.ollama_model || '');
  document.getElementById('temperature').value = cfg.temperature ?? 0.7;
  document.getElementById('num_predict').value = cfg.num_predict ?? 1024;
  document.getElementById('top_p').value = cfg.top_p ?? 0.9;
  document.getElementById('top_k').value = cfg.top_k ?? 40;
  document.getElementById('system_prompt').value = cfg.system_prompt || '';
  document.getElementById('max_history').value = cfg.max_history ?? 50;
  document.getElementById('allowed_senders').value = cfg.allowed_senders || '*';
  document.getElementById('allowed_admins').value = cfg.allowed_admins || '*';
}

function formatDateTime(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? 'unknown' : d.toLocaleString();
}

function renderStatus(s) {
  const d = s.dependencies || {};

  setDot('dot-signal', d.signal_api && d.signal_api.ok ? 'ok' : 'bad');
  document.getElementById('status-signal').textContent =
    d.signal_api && d.signal_api.ok ? ('v' + d.signal_api.version) : 'offline';

  setDot('dot-ollama', d.ollama && d.ollama.ok ? 'ok' : 'bad');
  document.getElementById('status-ollama').textContent =
    d.ollama && d.ollama.ok
      ? (d.ollama.version ? 'v' + d.ollama.version + ' \u00b7 ' : '') + d.ollama.models + ' models'
      : 'offline';

  const linked = d.account && d.account.linked;
  setDot('dot-account', linked ? 'ok' : 'wait');
  document.getElementById('status-account').textContent =
    linked ? d.account.phone_number : 'not linked';

  document.getElementById('status-model').textContent = s.model || 'none';
  document.getElementById('status-last').textContent =
    s.last_message_at ? (formatDateTime(s.last_message_at) + ' from ' + (s.last_message_sender || '?')) : 'none yet';

  // Show the linking section only when the account isn't linked.
  const linkSection = document.getElementById('link-section');
  if (linked) {
    linkSection.style.display = 'none';
    // Clear a stale "account unlinked" message once re-linked.
    const msg = document.getElementById('message');
    if (msg.textContent.indexOf('Account unlinked') !== -1) {
      msg.textContent = '';
      msg.className = '';
    }
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
    hideToken();
  } catch (e) { /* transient */ }
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config', {headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) return;
    fillForm(await r.json());
    hideToken();
  } catch (e) { /* transient */ }
}

async function loadModels() {
  try {
    const r = await fetch('/api/models', {headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) return;
    const models = await r.json();
    const sel = document.getElementById('ollama_model');
    const current = sel.value;
    sel.innerHTML = '<option value="">Auto-detect</option>';
    for (const m of models) {
      const opt = document.createElement('option');
      opt.value = m.name;
      const extra = [m.parameter_size, m.quantization].filter(Boolean).join(' ');
      opt.textContent = m.name + (extra ? '  (' + extra + ')' : '') + '  [' + m.size_gb + ' GB]';
      sel.appendChild(opt);
    }
    setModelSelect(current);
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
    signal_api_url: document.getElementById('signal_api_url').value.trim(),
    ollama_url: document.getElementById('ollama_url').value.trim(),
    ollama_model: document.getElementById('ollama_model').value.trim(),
    temperature: parseFloat(document.getElementById('temperature').value),
    num_predict: parseInt(document.getElementById('num_predict').value, 10),
    top_p: parseFloat(document.getElementById('top_p').value),
    top_k: parseInt(document.getElementById('top_k').value, 10),
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

async function resetConfig() {
  if (!confirm('Reset all settings to their defaults?')) return;
  try {
    const r = await fetch('/api/config/reset', {method: 'POST', headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { showMessage('Reset failed', true); return; }
    fillForm(await r.json());
    showMessage('Reset to defaults', false);
  } catch (e) { showMessage('Reset failed: ' + e, true); }
}

async function resetAll() {
  if (!confirm('RESET the entire installation? This unlinks your Signal account, clears all conversation history, and resets settings to defaults.')) return;
  if (!confirm('Are you sure? This cannot be undone.')) return;
  try {
    const r = await fetch('/api/reset', {method: 'POST', headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { showMessage('Reset failed', true); return; }
    showMessage('Installation reset — link your Signal account to start fresh.', false);
    refreshStatus();
    loadStats();
    loadConfig();
    loadQR();
  } catch (e) { showMessage('Reset failed: ' + e, true); }
}

function toggleTheme() {
  const dark = document.body.classList.toggle('dark');
  localStorage.setItem('osb_theme', dark ? 'dark' : 'light');
}

function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(function(el) { el.style.display = 'none'; });
  document.getElementById('tab-' + name).style.display = 'block';
  document.querySelectorAll('.tab').forEach(function(el) { el.classList.remove('active'); });
  document.querySelector('.tab[data-tab="' + name + '"]').classList.add('active');
  if (name === 'conversations') loadStats();
}

async function loadStats() {
  try {
    const r = await fetch('/api/stats', {headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) return;
    const s = await r.json();
    document.getElementById('stat-messages').textContent = s.total_messages;
    document.getElementById('stat-users').textContent = s.active_users;
    document.getElementById('stat-tokens').textContent = s.total_tokens_in + ' / ' + s.total_tokens_out;
    renderConversations(s.per_user || {});
  } catch (e) { /* transient */ }
}

function renderConversations(perUser) {
  const el = document.getElementById('conversations');
  const senders = Object.keys(perUser);
  if (!senders.length) {
    el.innerHTML = '<span class="muted">No conversations yet.</span>';
    return;
  }
  el.innerHTML = '';
  for (const sender of senders) {
    const row = document.createElement('div');
    row.className = 'status-row';
    const label = document.createElement('span');
    label.textContent = sender + '  (' + perUser[sender].messages + ' messages)';
    row.appendChild(label);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'secondary';
    btn.textContent = 'Clear';
    btn.style.marginLeft = 'auto';
    btn.onclick = function() { clearConversation(sender); };
    row.appendChild(btn);
    el.appendChild(row);
  }
}

async function clearConversation(sender) {
  if (!confirm('Clear conversation with ' + sender + '?')) return;
  try {
    const r = await fetch('/api/conversations/reset', {method: 'POST', headers: headers(), body: JSON.stringify({sender: sender})});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { showMessage('Clear failed', true); return; }
    loadStats();
  } catch (e) { showMessage('Clear failed: ' + e, true); }
}

async function pullModel() {
  const name = document.getElementById('pull_model').value.trim();
  if (!name) return;
  showMessage('Pulling ' + name + '… (this may take a while)', false);
  try {
    const r = await fetch('/api/models/pull', {method: 'POST', headers: headers(), body: JSON.stringify({name: name})});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { const d = await r.json().catch(() => ({})); showMessage(d.error || 'Pull failed', true); return; }
    showMessage('Pulled ' + name, false);
    document.getElementById('pull_model').value = '';
    loadModels();
  } catch (e) { showMessage('Pull failed: ' + e, true); }
}

async function unlinkAccount() {
  if (!confirm('Unlink the current Signal account? You will need to scan a new QR code to link a different account.')) return;
  try {
    const r = await fetch('/api/account/unlink', {method: 'POST', headers: headers()});
    if (r.status === 401) { showToken(); return; }
    if (!r.ok) { showMessage('Unlink failed', true); return; }
    showMessage('Account unlinked — scan the QR code to link a new account.', false);
    refreshStatus();
    loadQR();
  } catch (e) { showMessage('Unlink failed: ' + e, true); }
}

function saveToken() {
  token = document.getElementById('token').value.trim();
  localStorage.setItem(TOKEN_KEY, token);
  loadModels();
  loadConfig();
  refreshStatus();
  loadStats();
  loadQR();
}

(async function init() {
  if (localStorage.getItem('osb_theme') === 'dark') document.body.classList.add('dark');
  await loadModels();
  await loadConfig();
  await refreshStatus();
  loadStats();
  loadQR();
  setInterval(refreshStatus, 3000);
})();
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


async def _models(request):
    bot = request.app[_BOT_KEY]
    return web.json_response(await bot.get_available_models())


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


async def _reset_config(request):
    bot = request.app[_BOT_KEY]
    bot.reset_runtime_config()
    return web.json_response(bot.get_runtime_config())


async def _stats(request):
    bot = request.app[_BOT_KEY]
    return web.json_response(bot.get_stats())


async def _reset_conversation(request):
    bot = request.app[_BOT_KEY]
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    sender = (data or {}).get("sender", "").strip()
    if not sender:
        return web.json_response({"error": "sender is required"}, status=400)
    count = bot.clear_sender_history(sender)
    return web.json_response({"sender": sender, "cleared": count})


async def _pull_model(request):
    bot = request.app[_BOT_KEY]
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    name = (data or {}).get("name", "").strip()
    if not name:
        return web.json_response({"error": "model name is required"}, status=400)
    ok = await bot.pull_model(name)
    if not ok:
        return web.json_response({"error": f"pull failed for '{name}'"}, status=500)
    return web.json_response({"pulled": name})


async def _unlink_account(request):
    bot = request.app[_BOT_KEY]
    ok = await bot.unlink_account()
    if not ok:
        return web.json_response({"error": "unlink failed"}, status=500)
    return web.json_response({"unlinked": True})


async def _reset_all(request):
    bot = request.app[_BOT_KEY]
    await bot.reset_all()
    return web.json_response({"reset": True})


def create_app(bot, token=None):
    app = web.Application(middlewares=[_auth_middleware])
    app[_BOT_KEY] = bot
    app[_TOKEN_KEY] = token or ""
    app.router.add_get("/", _index)
    app.router.add_get("/api/status", _status)
    app.router.add_get("/api/link/qr", _link_qr)
    app.router.add_get("/api/models", _models)
    app.router.add_get("/api/config", _get_config)
    app.router.add_put("/api/config", _put_config)
    app.router.add_post("/api/config/reset", _reset_config)
    app.router.add_get("/api/stats", _stats)
    app.router.add_post("/api/conversations/reset", _reset_conversation)
    app.router.add_post("/api/models/pull", _pull_model)
    app.router.add_post("/api/account/unlink", _unlink_account)
    app.router.add_post("/api/reset", _reset_all)
    return app


async def start_server(bot, host, port, token=None):
    """Start the web UI and return an async cleanup function."""
    runner = web.AppRunner(create_app(bot, token))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner.cleanup
