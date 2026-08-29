"""The desktop UI: one page, no build step, no dependencies.

Served from localhost by repograph_ui.server. Everything a person needs to run a
scan without touching a terminal: pick a folder, choose what to produce, watch it
work, then open the report.
"""

CSS = r"""
:root {
  color-scheme: light dark;
  --bg:#ffffff; --panel:#f8fafc; --panel-2:#f1f5f9; --ink:#0f172a; --muted:#64748b;
  --faint:#94a3b8; --grid:#e2e8f0; --accent:#2563eb; --accent-ink:#ffffff;
  --ok:#16a34a; --warn:#a16207; --bad:#991b1b;
  --font: Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
  --mono: 'JetBrains Mono','SF Mono',Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#0b1120; --panel:#111827; --panel-2:#1e293b; --ink:#e2e8f0; --muted:#94a3b8;
          --faint:#64748b; --grid:#1e293b; --accent:#60a5fa; --accent-ink:#0b1120; }
}
* { box-sizing:border-box; }
body { margin:0; font-family:var(--font); background:var(--bg); color:var(--ink); font-size:14px; }
header { padding:18px 26px; border-bottom:1px solid var(--grid); display:flex; gap:14px;
         align-items:baseline; position:sticky; top:0; background:var(--bg); z-index:5; }
header h1 { font-size:17px; margin:0; letter-spacing:-0.01em; }
header .meta { color:var(--muted); font-size:12px; }
main { max-width:960px; margin:0 auto; padding:24px 26px 60px; }
h2 { font-size:15px; margin:26px 0 10px; }
.panel { background:var(--panel); border:1px solid var(--grid); border-radius:12px;
         padding:18px; margin-bottom:16px; }
label { display:block; font-size:12px; color:var(--muted); margin-bottom:6px; }
input[type=text], select { width:100%; font:inherit; font-family:var(--mono); font-size:13px;
  padding:10px 12px; border-radius:9px; border:1px solid var(--grid); background:var(--bg);
  color:var(--ink); }
.row { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
.row > .grow { flex:1 1 320px; }
button { font:inherit; font-size:13.5px; font-weight:600; padding:10px 16px; border-radius:9px;
  border:1px solid var(--accent); background:var(--accent); color:var(--accent-ink);
  cursor:pointer; }
button.ghost { background:var(--bg); color:var(--ink); border-color:var(--grid); font-weight:500; }
button:disabled { opacity:.5; cursor:default; }
button:hover:not(:disabled) { filter:brightness(1.07); }
.checks { display:flex; gap:18px; flex-wrap:wrap; margin-top:12px; }
.checks label { display:flex; gap:7px; align-items:center; font-size:13px; color:var(--ink);
                margin:0; cursor:pointer; }
.browser { max-height:260px; overflow:auto; border:1px solid var(--grid); border-radius:9px;
           margin-top:10px; background:var(--bg); }
.browser div { padding:7px 12px; cursor:pointer; font-family:var(--mono); font-size:12.5px;
               border-bottom:1px solid var(--grid); display:flex; justify-content:space-between; }
.browser div:last-child { border-bottom:0; }
.browser div:hover { background:var(--panel-2); }
.browser div .tag { color:var(--faint); font-family:var(--font); font-size:11px; }
.progress { height:8px; background:var(--panel-2); border-radius:99px; overflow:hidden;
            margin:14px 0 8px; }
.progress > div { height:100%; width:0; background:var(--accent); transition:width .25s; }
.log { font-family:var(--mono); font-size:12px; color:var(--muted); max-height:170px;
       overflow:auto; white-space:pre-wrap; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px;
         margin:12px 0; }
.card { background:var(--bg); border:1px solid var(--grid); border-radius:10px; padding:12px 14px; }
.card .v { font-size:20px; font-weight:700; }
.card .l { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.links { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
.links a { text-decoration:none; font-size:13px; padding:8px 13px; border-radius:8px;
           border:1px solid var(--grid); color:var(--ink); background:var(--bg); }
.links a:hover { background:var(--panel-2); }
.links a.primary { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
.recent { display:flex; flex-direction:column; gap:6px; }
.recent button { text-align:left; font-family:var(--mono); font-size:12.5px; font-weight:400;
                 background:var(--bg); color:var(--ink); border-color:var(--grid); }
.muted { color:var(--muted); }
.small { font-size:12.5px; }
.error { color:var(--bad); font-size:13px; margin-top:10px; white-space:pre-wrap; }
ul.qs { padding-left:18px; margin:8px 0 0; }
ul.qs li { margin-bottom:5px; font-size:13px; }
code { font-family:var(--mono); font-size:12.5px; background:var(--panel-2); padding:1px 5px;
       border-radius:5px; }
footer { color:var(--faint); font-size:11.5px; text-align:center; padding:24px; }
"""

JS = r"""
const TOKEN = new URLSearchParams(location.search).get('t') || window.__TOKEN__ || '';
const $ = (s) => document.querySelector(s);
let pollTimer = null;

async function api(path, options = {}) {
  const url = path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(TOKEN);
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function setError(message) {
  $('#error').textContent = message || '';
}

async function browse(path) {
  try {
    const data = await api('/api/browse?path=' + encodeURIComponent(path || ''));
    $('#path').value = data.path;
    const list = $('#browser');
    list.innerHTML = '';
    if (data.parent !== null) {
      const up = document.createElement('div');
      up.innerHTML = '<span>../</span><span class="tag">parent</span>';
      up.onclick = () => browse(data.parent);
      list.appendChild(up);
    }
    data.entries.forEach((entry) => {
      const row = document.createElement('div');
      row.innerHTML = '<span>' + entry.name + '/</span><span class="tag">' +
        (entry.repo ? 'git repository' : '') + '</span>';
      row.onclick = () => browse(entry.path);
      list.appendChild(row);
    });
    setError('');
  } catch (err) { setError(String(err.message || err)); }
}

async function loadRecent() {
  try {
    const data = await api('/api/recent');
    const box = $('#recent');
    box.innerHTML = '';
    if (!data.entries.length) { $('#recent-panel').hidden = true; return; }
    $('#recent-panel').hidden = false;
    data.entries.forEach((entry) => {
      const button = document.createElement('button');
      button.className = 'ghost';
      button.textContent = entry.path + '   ' + (entry.when || '');
      button.onclick = () => { $('#path').value = entry.path; browse(entry.path); };
      box.appendChild(button);
    });
  } catch (err) { /* history is optional */ }
}

async function startScan() {
  setError('');
  $('#scan').disabled = true;
  $('#result').hidden = true;
  $('#progress-panel').hidden = false;
  $('#log').textContent = '';
  try {
    const body = {
      path: $('#path').value,
      online: $('#online').checked,
      everything: $('#everything').checked,
      no_git: !$('#git').checked,
      output: $('#output').value.trim(),
    };
    await api('/api/scan', { method: 'POST', body: JSON.stringify(body) });
    poll();
  } catch (err) {
    setError(String(err.message || err));
    $('#scan').disabled = false;
  }
}

async function poll() {
  clearTimeout(pollTimer);
  try {
    const status = await api('/api/status');
    const percent = status.total ? Math.round((status.done / status.total) * 100)
                                 : (status.state === 'running' ? 40 : 100);
    $('#bar').style.width = percent + '%';
    $('#stage').textContent = status.stage || '';
    if (status.log) $('#log').textContent = status.log.join('\n');
    if (status.state === 'running') { pollTimer = setTimeout(poll, 400); return; }
    $('#scan').disabled = false;
    if (status.state === 'error') { setError(status.error || 'the scan failed'); return; }
    if (status.state === 'done') showResult(status);
  } catch (err) {
    $('#scan').disabled = false;
    setError(String(err.message || err));
  }
}

function showResult(status) {
  const summary = status.summary || {};
  $('#result').hidden = false;
  $('#result-title').textContent = summary.name + ' — ' + (summary.label || '');
  $('#result-what').textContent = summary.what_it_is || '';
  const cards = [
    [summary.apps, 'Applications'], [summary.endpoints, 'Ways in'],
    [summary.systems, 'Systems it needs'], [summary.findings, 'Issues found'],
    [summary.files, 'Files'], [(summary.loc || 0).toLocaleString(), 'Lines of code'],
  ];
  $('#cards').innerHTML = cards.map(([value, label]) =>
    '<div class="card"><div class="v">' + (value ?? 0) + '</div><div class="l">' + label +
    '</div></div>').join('');
  const base = '/report/';
  const links = [['index.html', 'Open the report', 'primary']];
  (status.documents || []).forEach((name) => links.push([name, name, '']));
  $('#links').innerHTML = links.map(([href, label, cls]) =>
    '<a class="' + cls + '" target="_blank" href="' + base + href + '?t=' +
    encodeURIComponent(TOKEN) + '">' + label + '</a>').join('');
  $('#questions').innerHTML = (status.questions || []).map((q) => '<li>' + q + '</li>').join('');
  $('#ask-hint').innerHTML = 'Ask one with <code>repograph ask "…" -o ' +
    (status.output_dir || '') + '</code>';
  loadRecent();
}

document.addEventListener('DOMContentLoaded', () => {
  $('#scan').addEventListener('click', startScan);
  $('#browse').addEventListener('click', () => browse($('#path').value));
  $('#path').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') startScan();
  });
  browse('');
  loadRecent();
  poll();
});
"""


def page(version: str, token: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>repograph</title>
<style>{CSS}</style>
</head><body>
<header>
  <h1>repograph</h1>
  <span class="meta">{version} · running locally · nothing leaves this machine</span>
</header>
<main>
  <div class="panel">
    <div class="row">
      <div class="grow">
        <label for="path">Repository folder</label>
        <input type="text" id="path" spellcheck="false" placeholder="/path/to/your/repository">
      </div>
      <button class="ghost" id="browse">Browse</button>
      <button id="scan">Scan</button>
    </div>
    <div id="browser" class="browser"></div>
    <div class="checks">
      <label><input type="checkbox" id="git" checked> Read git history</label>
      <label><input type="checkbox" id="online"> Check dependencies against OSV.dev (network)</label>
      <label><input type="checkbox" id="everything"> Produce every artifact, even inapplicable ones</label>
    </div>
    <div class="row" style="margin-top:12px">
      <div class="grow">
        <label for="output">Output folder (optional — defaults to &lt;repository&gt;/repograph-out)</label>
        <input type="text" id="output" spellcheck="false" placeholder="">
      </div>
    </div>
    <div id="error" class="error"></div>
  </div>

  <div class="panel" id="recent-panel" hidden>
    <label>Recently scanned</label>
    <div class="recent" id="recent"></div>
  </div>

  <div class="panel" id="progress-panel" hidden>
    <div id="stage" class="small muted">Starting…</div>
    <div class="progress"><div id="bar"></div></div>
    <div class="log" id="log"></div>
  </div>

  <div class="panel" id="result" hidden>
    <h2 id="result-title"></h2>
    <p class="small" id="result-what"></p>
    <div class="cards" id="cards"></div>
    <div class="links" id="links"></div>
    <h2>Questions worth asking next</h2>
    <ul class="qs" id="questions"></ul>
    <p class="small muted" id="ask-hint"></p>
  </div>
</main>
<footer>repograph runs entirely on this machine. Close this window to stop the server.</footer>
<script>window.__TOKEN__ = {token!r};</script>
<script>{JS}</script>
</body></html>"""
