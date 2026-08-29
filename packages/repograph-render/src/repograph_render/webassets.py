"""CSS and JavaScript for the interactive report.

Everything is inlined into the generated HTML: the report has to work from a
file:// URL on a laptop with no network, so there are no CDN dependencies and
the 2D/3D graph engines are written from scratch against plain canvas.
"""

CSS = r"""
:root {
  color-scheme: light dark;
  --bg: #ffffff; --panel: #f8fafc; --panel-2: #f1f5f9; --ink: #0f172a; --muted: #64748b;
  --faint: #94a3b8; --grid: #e2e8f0; --accent: #2563eb; --accent-soft: #eff6ff;
  --critical: #991b1b; --high: #c2410c; --medium: #a16207; --low: #1d4ed8; --info: #64748b;
  --radius: 12px; --mono: 'JetBrains Mono','SF Mono',Menlo,Consolas,monospace;
  --font: Inter,'Helvetica Neue',Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1120; --panel: #111827; --panel-2: #1e293b; --ink: #e2e8f0; --muted: #94a3b8;
    --faint: #64748b; --grid: #1e293b; --accent: #60a5fa; --accent-soft: #172554;
    --critical: #f87171; --high: #fb923c; --medium: #fbbf24; --low: #60a5fa; --info: #94a3b8;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: var(--font); background: var(--bg); color: var(--ink);
       font-size: 14px; line-height: 1.55; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, .mono { font-family: var(--mono); font-size: 12.5px; }
header.top { position: sticky; top: 0; z-index: 30; background: var(--bg);
  border-bottom: 1px solid var(--grid); padding: 14px 22px; display: flex; gap: 16px;
  align-items: baseline; flex-wrap: wrap; }
header.top h1 { font-size: 17px; margin: 0; font-weight: 700; letter-spacing: -0.01em; }
header.top .meta { color: var(--muted); font-size: 12px; }
nav.tabs { display: flex; gap: 4px; overflow-x: auto; padding: 8px 18px; background: var(--panel);
  border-bottom: 1px solid var(--grid); position: sticky; top: 52px; z-index: 29; }
nav.tabs button { border: 0; background: transparent; color: var(--muted); padding: 7px 13px;
  border-radius: 8px; cursor: pointer; font-size: 13px; font-family: inherit; white-space: nowrap; }
nav.tabs button:hover { background: var(--panel-2); color: var(--ink); }
nav.tabs button[aria-selected="true"] { background: var(--accent); color: #fff; font-weight: 600; }
main { padding: 22px; max-width: 1500px; margin: 0 auto; }
section[hidden] { display: none !important; }
h2 { font-size: 16px; margin: 26px 0 12px; letter-spacing: -0.01em; }
h2:first-child { margin-top: 4px; }
h3 { font-size: 13.5px; margin: 18px 0 8px; color: var(--muted); text-transform: uppercase;
     letter-spacing: 0.06em; }
p.lede { color: var(--muted); max-width: 78ch; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(178px, 1fr)); gap: 12px; }
.card { background: var(--panel); border: 1px solid var(--grid); border-radius: var(--radius);
  padding: 14px 16px; }
.card .value { font-size: 23px; font-weight: 700; letter-spacing: -0.02em; }
.card .label { color: var(--muted); font-size: 11.5px; text-transform: uppercase;
  letter-spacing: 0.05em; }
.panel { background: var(--panel); border: 1px solid var(--grid); border-radius: var(--radius);
  padding: 16px 18px; margin-bottom: 16px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 12.8px; }
th { text-align: left; font-weight: 600; color: var(--muted); border-bottom: 1px solid var(--grid);
  padding: 7px 9px; position: sticky; top: 0; background: var(--bg); cursor: pointer;
  white-space: nowrap; }
th:hover { color: var(--ink); }
td { padding: 6px 9px; border-bottom: 1px solid var(--grid); vertical-align: top; }
tr:hover td { background: var(--panel); }
.table-wrap { max-height: 560px; overflow: auto; border: 1px solid var(--grid);
  border-radius: var(--radius); }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px;
  font-weight: 600; color: #fff; }
.badge.critical { background: var(--critical); } .badge.high { background: var(--high); }
.badge.medium { background: var(--medium); } .badge.low { background: var(--low); }
.badge.info { background: var(--info); }
.tag { display: inline-block; padding: 1px 7px; border-radius: 6px; background: var(--panel-2);
  color: var(--muted); font-size: 11px; margin-right: 4px; }
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
input[type=search], select { font: inherit; font-size: 13px; padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--grid); background: var(--bg); color: var(--ink); }
input[type=search] { min-width: 240px; }
button.ghost { font: inherit; font-size: 12.5px; padding: 6px 11px; border-radius: 8px;
  border: 1px solid var(--grid); background: var(--bg); color: var(--ink); cursor: pointer; }
button.ghost:hover { background: var(--panel-2); }
.canvas-wrap { position: relative; border: 1px solid var(--grid); border-radius: var(--radius);
  overflow: hidden; background: var(--panel); }
canvas { display: block; width: 100%; touch-action: none; cursor: grab; }
canvas:active { cursor: grabbing; }
.tooltip { position: absolute; pointer-events: none; background: var(--ink); color: var(--bg);
  padding: 7px 10px; border-radius: 8px; font-size: 12px; max-width: 300px; opacity: 0;
  transition: opacity .12s; z-index: 10; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 12px;
  margin-top: 10px; }
.legend span.dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block;
  margin-right: 5px; vertical-align: middle; }
.diagram { overflow: auto; border: 1px solid var(--grid); border-radius: var(--radius);
  background: #fff; padding: 8px; margin-bottom: 14px; }
.diagram svg { max-width: none; }
@media (prefers-color-scheme: dark) { .diagram { background: #f8fafc; } }
details { border: 1px solid var(--grid); border-radius: 10px; padding: 8px 12px; margin: 8px 0;
  background: var(--panel); }
summary { cursor: pointer; font-size: 12.5px; color: var(--muted); }
pre { background: var(--panel-2); border-radius: 8px; padding: 12px; overflow: auto;
  font-family: var(--mono); font-size: 12px; line-height: 1.5; }
.finding { border-left: 3px solid var(--grid); padding: 8px 12px; margin-bottom: 8px;
  background: var(--panel); border-radius: 0 8px 8px 0; }
.finding.critical { border-left-color: var(--critical); }
.finding.high { border-left-color: var(--high); }
.finding.medium { border-left-color: var(--medium); }
.finding.low { border-left-color: var(--low); }
.finding .where { color: var(--muted); font-size: 11.5px; font-family: var(--mono); }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.right { text-align: right; }
footer { color: var(--faint); font-size: 11.5px; padding: 30px 22px; text-align: center; }
.pill-row { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 2px; }
.kv { display: grid; grid-template-columns: 190px 1fr; gap: 4px 14px; font-size: 13px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
"""

JS = r"""
(function () {
  'use strict';
  const DATA = window.__REPOGRAPH__;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // ---------------------------------------------------------------- tabs
  const tabs = $$('nav.tabs button');
  const sections = $$('main section');
  function activate(name) {
    tabs.forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    sections.forEach(s => { s.hidden = s.dataset.tab !== name; });
    if (name === 'graph2d') graph2d.start();
    if (name === 'graph3d') graph3d.start();
    if (location.hash.slice(1) !== name) history.replaceState(null, '', '#' + name);
  }
  tabs.forEach(b => b.addEventListener('click', () => activate(b.dataset.tab)));

  // ------------------------------------------------------------- tables
  $$('table[data-sortable]').forEach(table => {
    const tbody = table.tBodies[0];
    $$('th', table).forEach((th, index) => {
      th.addEventListener('click', () => {
        const numeric = th.dataset.numeric === '1';
        const dir = th.dataset.dir === 'asc' ? -1 : 1;
        $$('th', table).forEach(o => delete o.dataset.dir);
        th.dataset.dir = dir === 1 ? 'asc' : 'desc';
        const rows = Array.from(tbody.rows);
        rows.sort((a, b) => {
          const av = a.cells[index]?.dataset.sort ?? a.cells[index]?.innerText ?? '';
          const bv = b.cells[index]?.dataset.sort ?? b.cells[index]?.innerText ?? '';
          if (numeric) return (parseFloat(av || 0) - parseFloat(bv || 0)) * dir;
          return av.localeCompare(bv) * dir;
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
  });

  $$('input[data-filter]').forEach(input => {
    input.addEventListener('input', () => {
      const target = $('#' + input.dataset.filter);
      const needle = input.value.toLowerCase().trim();
      $$('tbody tr', target).forEach(row => {
        row.style.display = !needle || row.innerText.toLowerCase().includes(needle) ? '' : 'none';
      });
      const counter = $('#' + input.dataset.filter + '-count');
      if (counter) {
        counter.textContent = $$('tbody tr', target).filter(r => r.style.display !== 'none').length
          + ' of ' + $$('tbody tr', target).length;
      }
    });
  });

  $$('select[data-select-filter]').forEach(select => {
    select.addEventListener('change', () => {
      const target = $('#' + select.dataset.selectFilter);
      const key = select.dataset.key;
      const value = select.value;
      $$('tbody tr', target).forEach(row => {
        row.style.display = !value || row.dataset[key] === value ? '' : 'none';
      });
    });
  });

  // -------------------------------------------------------- graph shared
  const COLORS = DATA.colors || {};
  function nodeColor(n) { return COLORS[n.kind] || '#2563eb'; }
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function buildAdjacency(nodes, links) {
    const index = new Map(nodes.map((n, i) => [n.id, i]));
    const edges = [];
    links.forEach(l => {
      const s = index.get(l.source), t = index.get(l.target);
      if (s === undefined || t === undefined || s === t) return;
      edges.push({ s, t, w: l.weight || 1 });
    });
    return { index, edges };
  }

  // ------------------------------------------------------------ 2D graph
  const graph2d = (function () {
    const canvas = $('#graph2d');
    if (!canvas) return { start() {} };
    const ctx = canvas.getContext('2d');
    const tooltip = $('#tip2d');
    let nodes = [], edges = [], started = false, raf = null;
    let view = { x: 0, y: 0, k: 1 }, drag = null, hover = null, pinned = null;
    let filterApp = '', search = '';

    function reset() {
      const source = DATA.graph.nodes;
      const keep = source.filter(n => (!filterApp || n.app === filterApp));
      nodes = keep.map((n, i) => ({
        ...n,
        x: Math.cos(i * 2.399) * (60 + i * 6), y: Math.sin(i * 2.399) * (60 + i * 6),
        vx: 0, vy: 0, r: Math.max(5, Math.min(24, 4 + Math.sqrt(n.size || 1) * 1.7))
      }));
      const built = buildAdjacency(nodes, DATA.graph.links);
      edges = built.edges;
      view = { x: canvas.width / 2, y: canvas.height / 2, k: 1 };
      simulate(260);
    }

    function simulate(steps) {
      const k = Math.sqrt((canvas.width * canvas.height) / Math.max(1, nodes.length)) * 0.55;
      for (let step = 0; step < steps; step++) {
        const t = 1 - step / steps;
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 0.01; }
            const force = (k * k) / d2;
            const fx = dx * force * 0.02, fy = dy * force * 0.02;
            a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
          }
        }
        edges.forEach(e => {
          const a = nodes[e.s], b = nodes[e.t];
          const dx = b.x - a.x, dy = b.y - a.y;
          const d = Math.hypot(dx, dy) || 0.01;
          const force = (d - k) * 0.012 * Math.min(3, 1 + Math.log1p(e.w));
          const fx = dx / d * force, fy = dy / d * force;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        });
        nodes.forEach(n => {
          n.vx -= n.x * 0.0016; n.vy -= n.y * 0.0016;
          n.x += n.vx * t; n.y += n.vy * t;
          n.vx *= 0.82; n.vy *= 0.82;
        });
      }
    }

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = Math.max(460, Math.round(rect.width * 0.56)) * dpr;
      canvas.style.height = (canvas.height / dpr) + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function toScreen(n) {
      return { x: n.x * view.k + view.x / (window.devicePixelRatio || 1),
               y: n.y * view.k + view.y / (window.devicePixelRatio || 1) };
    }

    function draw() {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr, h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = css('--panel'); ctx.fillRect(0, 0, w, h);
      const highlight = pinned || hover;
      const near = new Set();
      if (highlight) {
        near.add(highlight.id);
        edges.forEach(e => {
          if (nodes[e.s].id === highlight.id) near.add(nodes[e.t].id);
          if (nodes[e.t].id === highlight.id) near.add(nodes[e.s].id);
        });
      }
      ctx.lineCap = 'round';
      edges.forEach(e => {
        const a = toScreen(nodes[e.s]), b = toScreen(nodes[e.t]);
        const active = highlight && (near.has(nodes[e.s].id) && near.has(nodes[e.t].id));
        ctx.globalAlpha = highlight ? (active ? 0.9 : 0.08) : 0.32;
        ctx.strokeStyle = active ? css('--accent') : css('--faint');
        ctx.lineWidth = Math.min(3.4, 0.7 + Math.log1p(e.w)) * view.k;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      });
      ctx.globalAlpha = 1;
      nodes.forEach(n => {
        const p = toScreen(n);
        const dim = highlight && !near.has(n.id);
        const matched = search && n.label.toLowerCase().includes(search);
        ctx.globalAlpha = dim ? 0.18 : 1;
        ctx.beginPath(); ctx.arc(p.x, p.y, n.r * view.k, 0, Math.PI * 2);
        ctx.fillStyle = nodeColor(n); ctx.fill();
        if (matched) { ctx.lineWidth = 3; ctx.strokeStyle = css('--ink'); ctx.stroke(); }
        if (view.k > 0.55 || n.r > 12 || matched) {
          ctx.globalAlpha = dim ? 0.25 : 0.95;
          ctx.fillStyle = css('--ink');
          ctx.font = '600 ' + Math.max(9, 11 * Math.min(1.4, view.k)) + 'px ' + css('--font');
          ctx.textAlign = 'center';
          ctx.fillText(n.label, p.x, p.y - n.r * view.k - 5);
        }
      });
      ctx.globalAlpha = 1;
    }

    function pick(mx, my) {
      let best = null, bestDist = 22;
      nodes.forEach(n => {
        const p = toScreen(n);
        const d = Math.hypot(p.x - mx, p.y - my);
        if (d < Math.max(bestDist, n.r * view.k + 4)) { best = n; bestDist = d; }
      });
      return best;
    }

    function bind() {
      canvas.addEventListener('pointerdown', ev => {
        const rect = canvas.getBoundingClientRect();
        const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
        const hit = pick(mx, my);
        if (hit) { pinned = pinned && pinned.id === hit.id ? null : hit; draw(); return; }
        drag = { x: ev.clientX, y: ev.clientY, ox: view.x, oy: view.y };
        canvas.setPointerCapture(ev.pointerId);
      });
      canvas.addEventListener('pointermove', ev => {
        const rect = canvas.getBoundingClientRect();
        const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
        if (drag) {
          view.x = drag.ox + (ev.clientX - drag.x) * (window.devicePixelRatio || 1);
          view.y = drag.oy + (ev.clientY - drag.y) * (window.devicePixelRatio || 1);
          draw();
          return;
        }
        const hit = pick(mx, my);
        hover = hit;
        if (hit) {
          tooltip.style.opacity = 1;
          tooltip.style.left = Math.min(mx + 14, rect.width - 260) + 'px';
          tooltip.style.top = (my + 14) + 'px';
          tooltip.innerHTML = '<b>' + hit.label + '</b><br>' + (hit.detail || '');
        } else { tooltip.style.opacity = 0; }
        draw();
      });
      canvas.addEventListener('pointerup', ev => { drag = null; });
      canvas.addEventListener('pointerleave', () => { drag = null; hover = null; tooltip.style.opacity = 0; draw(); });
      canvas.addEventListener('wheel', ev => {
        ev.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
        const factor = ev.deltaY < 0 ? 1.12 : 0.89;
        const dpr = window.devicePixelRatio || 1;
        view.x = (view.x / dpr - mx) * factor * dpr + mx * dpr;
        view.y = (view.y / dpr - my) * factor * dpr + my * dpr;
        view.k = Math.max(0.12, Math.min(6, view.k * factor));
        draw();
      }, { passive: false });
      window.addEventListener('resize', () => { resize(); draw(); });
      const appSelect = $('#graph2d-app');
      if (appSelect) appSelect.addEventListener('change', () => {
        filterApp = appSelect.value; reset(); draw();
      });
      const searchBox = $('#graph2d-search');
      if (searchBox) searchBox.addEventListener('input', () => {
        search = searchBox.value.toLowerCase().trim(); draw();
      });
      const relayout = $('#graph2d-relayout');
      if (relayout) relayout.addEventListener('click', () => { reset(); draw(); });
    }

    return {
      start() {
        if (started) { resize(); draw(); return; }
        started = true; resize(); reset(); bind(); draw();
      }
    };
  })();

  // ------------------------------------------------------------ 3D graph
  const graph3d = (function () {
    const canvas = $('#graph3d');
    if (!canvas) return { start() {} };
    const ctx = canvas.getContext('2d');
    const tooltip = $('#tip3d');
    let nodes = [], edges = [], started = false;
    let rotX = -0.32, rotY = 0.55, zoom = 1, autoRotate = true, drag = null, hover = null;
    let raf = null;

    function layout() {
      const source = DATA.graph.nodes;
      nodes = source.map((n, i) => {
        const phi = Math.acos(1 - 2 * (i + 0.5) / source.length);
        const theta = Math.PI * (1 + Math.sqrt(5)) * (i + 0.5);
        const radius = 220 + (i % 5) * 14;
        return {
          ...n,
          x: radius * Math.sin(phi) * Math.cos(theta),
          y: radius * Math.sin(phi) * Math.sin(theta),
          z: radius * Math.cos(phi),
          vx: 0, vy: 0, vz: 0,
          r: Math.max(4, Math.min(18, 3.5 + Math.sqrt(n.size || 1) * 1.5))
        };
      });
      edges = buildAdjacency(nodes, DATA.graph.links).edges;
      const k = 150 / Math.max(1, Math.cbrt(nodes.length));
      for (let step = 0; step < 220; step++) {
        const t = 1 - step / 220;
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
            let d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < 1) { dx = Math.random(); dy = Math.random(); dz = Math.random(); d2 = 1; }
            const f = (k * k * 60) / d2;
            const fx = dx * f / Math.sqrt(d2), fy = dy * f / Math.sqrt(d2), fz = dz * f / Math.sqrt(d2);
            a.vx += fx; a.vy += fy; a.vz += fz;
            b.vx -= fx; b.vy -= fy; b.vz -= fz;
          }
        }
        edges.forEach(e => {
          const a = nodes[e.s], b = nodes[e.t];
          const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
          const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 0.01;
          const f = (d - k * 2.4) * 0.01;
          a.vx += dx / d * f; a.vy += dy / d * f; a.vz += dz / d * f;
          b.vx -= dx / d * f; b.vy -= dy / d * f; b.vz -= dz / d * f;
        });
        nodes.forEach(n => {
          n.vx -= n.x * 0.0012; n.vy -= n.y * 0.0012; n.vz -= n.z * 0.0012;
          n.x += n.vx * t; n.y += n.vy * t; n.z += n.vz * t;
          n.vx *= 0.8; n.vy *= 0.8; n.vz *= 0.8;
        });
      }
    }

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = Math.max(500, Math.round(rect.width * 0.6)) * dpr;
      canvas.style.height = (canvas.height / dpr) + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function project(n) {
      const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
      const cosX = Math.cos(rotX), sinX = Math.sin(rotX);
      let x = n.x * cosY - n.z * sinY;
      let z = n.x * sinY + n.z * cosY;
      let y = n.y * cosX - z * sinX;
      z = n.y * sinX + z * cosX;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr, h = canvas.height / dpr;
      const distance = 900;
      const scale = (distance / (distance + z + 420)) * zoom;
      return { x: w / 2 + x * scale, y: h / 2 + y * scale, z: z, s: scale };
    }

    function draw() {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr, h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);
      const bg = ctx.createLinearGradient(0, 0, 0, h);
      bg.addColorStop(0, css('--panel'));
      bg.addColorStop(1, css('--panel-2'));
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

      const points = nodes.map(project);
      edges.forEach(e => {
        const a = points[e.s], b = points[e.t];
        const depth = (a.z + b.z) / 2;
        ctx.globalAlpha = Math.max(0.05, Math.min(0.5, 0.42 - depth / 1800));
        ctx.strokeStyle = hover && (nodes[e.s].id === hover.id || nodes[e.t].id === hover.id)
          ? css('--accent') : css('--faint');
        if (hover && (nodes[e.s].id === hover.id || nodes[e.t].id === hover.id)) ctx.globalAlpha = 0.95;
        ctx.lineWidth = Math.max(0.4, Math.min(2.6, 0.6 + Math.log1p(e.w)) * ((a.s + b.s) / 2));
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      });

      const order = nodes.map((n, i) => i).sort((a, b) => points[b].z - points[a].z);
      order.forEach(i => {
        const n = nodes[i], p = points[i];
        const radius = Math.max(2, n.r * p.s);
        const shade = Math.max(0.35, Math.min(1, 1 - (p.z + 400) / 1400));
        ctx.globalAlpha = shade;
        const gradient = ctx.createRadialGradient(p.x - radius / 3, p.y - radius / 3, radius / 6,
                                                  p.x, p.y, radius);
        gradient.addColorStop(0, '#ffffff');
        gradient.addColorStop(0.35, nodeColor(n));
        gradient.addColorStop(1, nodeColor(n));
        ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = gradient; ctx.fill();
        if (hover && hover.id === n.id) {
          ctx.globalAlpha = 1; ctx.strokeStyle = css('--ink'); ctx.lineWidth = 2; ctx.stroke();
        }
        if (radius > 7 || (hover && hover.id === n.id)) {
          ctx.globalAlpha = Math.min(1, shade + 0.25);
          ctx.fillStyle = css('--ink');
          ctx.font = '600 ' + Math.max(9, 11 * p.s) + 'px ' + css('--font');
          ctx.textAlign = 'center';
          ctx.fillText(n.label, p.x, p.y - radius - 4);
        }
      });
      ctx.globalAlpha = 1;
    }

    function loop() {
      if (autoRotate && !drag) { rotY += 0.0022; draw(); }
      raf = requestAnimationFrame(loop);
    }

    function bind() {
      canvas.addEventListener('pointerdown', ev => {
        drag = { x: ev.clientX, y: ev.clientY, rx: rotX, ry: rotY };
        canvas.setPointerCapture(ev.pointerId);
      });
      canvas.addEventListener('pointermove', ev => {
        const rect = canvas.getBoundingClientRect();
        if (drag) {
          rotY = drag.ry + (ev.clientX - drag.x) * 0.006;
          rotX = Math.max(-1.4, Math.min(1.4, drag.rx + (ev.clientY - drag.y) * 0.006));
          draw();
          return;
        }
        const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
        const points = nodes.map(project);
        let best = null, bestD = 18;
        points.forEach((p, i) => {
          const d = Math.hypot(p.x - mx, p.y - my);
          if (d < Math.max(bestD, nodes[i].r * p.s + 4)) { best = nodes[i]; bestD = d; }
        });
        hover = best;
        if (best) {
          tooltip.style.opacity = 1;
          tooltip.style.left = Math.min(mx + 14, rect.width - 260) + 'px';
          tooltip.style.top = (my + 14) + 'px';
          tooltip.innerHTML = '<b>' + best.label + '</b><br>' + (best.detail || '');
        } else { tooltip.style.opacity = 0; }
        draw();
      });
      canvas.addEventListener('pointerup', () => { drag = null; });
      canvas.addEventListener('pointerleave', () => { drag = null; hover = null; tooltip.style.opacity = 0; });
      canvas.addEventListener('wheel', ev => {
        ev.preventDefault();
        zoom = Math.max(0.25, Math.min(4, zoom * (ev.deltaY < 0 ? 1.1 : 0.9)));
        draw();
      }, { passive: false });
      window.addEventListener('resize', () => { resize(); draw(); });
      const toggle = $('#graph3d-rotate');
      if (toggle) toggle.addEventListener('click', () => {
        autoRotate = !autoRotate;
        toggle.textContent = autoRotate ? 'Pause rotation' : 'Resume rotation';
      });
    }

    return {
      start() {
        if (started) { resize(); draw(); return; }
        started = true; resize(); layout(); bind(); draw(); loop();
      }
    };
  })();

  // ------------------------------------------------------------- startup
  const initial = location.hash.slice(1);
  activate(tabs.some(t => t.dataset.tab === initial) ? initial : tabs[0].dataset.tab);
  window.addEventListener('hashchange', () => {
    const name = location.hash.slice(1);
    if (tabs.some(t => t.dataset.tab === name)) activate(name);
  });
})();
"""
