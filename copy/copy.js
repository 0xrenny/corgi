/* Corgi · paper copy-trade dashboard. Reads data/copy.json (or window.CORGI_DATA_BASE + 'copy.json'). No build step. */
(function () {
  'use strict';
  var DATA = (window.CORGI_DATA_BASE) || '../data/';
  var TZ = 'Europe/Istanbul';
  var Q = new URLSearchParams(location.search);
  var REPLAY = Q.get('replay') === '1';
  var REPLAY_S = Math.min(120, Math.max(10, +Q.get('seconds') || 34));
  var RM = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $ = function (id) { return document.getElementById(id); };
  var doc = null, first = true, lastShown = {};
  var COLORS = ['#FF9F4A', '#5BE3A4', '#7FB8FF', '#FF6F96', '#FFC27A', '#B49CFF', '#4FD1C5', '#F6E05E'];

  /* ---------- helpers ---------- */
  function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
  function svgEl(tag, attrs) { var e = document.createElementNS('http://www.w3.org/2000/svg', tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function ms(ts) { return new Date(ts).getTime(); }
  function usd(v, d) { if (v == null || isNaN(v)) return '—'; var s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d }); return (v < 0 ? '−$' : '$') + s; }
  function sgnUsd(v) { return (v > 0 ? '+' : '') + usd(v); }
  function pct(v, d) { return v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(d == null ? 2 : d) + '%'; }
  function price(v) { if (v == null) return '—'; if (v >= 1) return '$' + v.toFixed(4); var e = Math.max(2, -Math.floor(Math.log10(v)) + 3); return '$' + v.toFixed(Math.min(e, 12)); }
  function shortA(a) { return a ? a.slice(0, 6) + '…' + a.slice(-4) : ''; }
  function fmtTime(ts, withDate) { var o = { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false }; if (withDate) { o.month = 'short'; o.day = 'numeric'; } return new Date(ts).toLocaleString('en-GB', o); }
  function fmtClock(ts) { return new Date(ts).toLocaleTimeString('en-GB', { timeZone: TZ, hour12: false }); }
  function ago(t) { var s = Math.max(0, (Date.now() - t) / 1000); if (s < 90) return 'just now'; if (s < 3600) return Math.round(s / 60) + 'm ago'; if (s < 86400) return Math.round(s / 3600) + 'h ago'; return Math.round(s / 86400) + 'd ago'; }
  function dayN(t) { var s = doc.experiment.day1; var d0 = Date.parse(s + 'T00:00:00+03:00'); return Math.floor((t - d0) / 864e5) + 1; }

  var tweens = {};
  function count(id, to, fmt, dur) {
    var node = $(id); if (!node) return;
    var from = tweens[id] != null ? tweens[id] : to;
    tweens[id] = to;
    if (RM || REPLAY || from === to || first && !dur) { node.textContent = fmt(to); if (!(first && !RM && !REPLAY)) return; from = 0; }
    var t0 = performance.now(), D = dur || 1100;
    (function step(t) { var k = Math.min(1, (t - t0) / D), e = 1 - Math.pow(1 - k, 3); node.textContent = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); })(t0);
  }

  function lastTs() { var h = doc.balance_history; return h.length ? ms(h[h.length - 1].ts) : 0; }

  /* ---------- view of the experiment up to time tCut ---------- */
  function view(tCut) {
    var B = doc.experiment.bankroll_usd;
    var trades = doc.trades.filter(function (t) { return ms(t.ts) <= tCut; });
    var hist = doc.balance_history.filter(function (h) { return ms(h.ts) <= tCut; });
    var sells = trades.filter(function (t) { return t.side === 'sell'; });
    var wins = sells.filter(function (t) { return t.realized_pnl_usd > 0; }).length;
    var eq = hist.length ? hist[hist.length - 1].equity : B, peak = B, mdd = 0;
    hist.forEach(function (h) { peak = Math.max(peak, h.equity); mdd = Math.max(mdd, peak > 0 ? (peak - h.equity) / peak : 0); });
    var streak = 0; for (var i = sells.length - 1; i >= 0 && sells[i].realized_pnl_usd > 0; i--) streak++;
    var realized = sells.reduce(function (a, t) { return a + t.realized_pnl_usd; }, 0);
    var fees = trades.reduce(function (a, t) { return a + (t.fee_usd || 0); }, 0);
    return { trades: trades, hist: hist, equity: eq, pnl: eq - B, pnlPct: (eq - B) / B * 100, sells: sells.length, buys: trades.length - sells.length,
      wins: wins, winRate: sells.length ? wins / sells.length : null, mdd: mdd * 100, streak: streak, realized: realized, fees: fees };
  }

  /* ---------- top / hero ---------- */
  function renderLive() {
    var t = ms(doc.updated_at), age = (Date.now() - t) / 36e5, live = $('live');
    live.classList.toggle('stale', age >= 5 && age < 14); live.classList.toggle('dead', age >= 14);
    $('liveText').textContent = (age < 5 ? 'live · ' : age < 14 ? 'napping · ' : 'offline · ') + 'updated ' + ago(t);
    live.title = 'Last update ' + fmtTime(doc.updated_at, true) + ' TRT. Corgi wakes at 09:09, 13:09, 17:09 and 21:09 TRT.';
    $('updated').textContent = 'Data updated ' + fmtTime(doc.updated_at, true) + ' TRT · next wakes 09:09 · 13:09 · 17:09 · 21:09 TRT';
  }

  function renderHero(v, tNow) {
    count('equity', v.equity, function (x) { return usd(x); }, 1400);
    var chip = $('pnlChip'); chip.textContent = pct(v.pnlPct) + ' · ' + sgnUsd(v.pnl);
    chip.className = 'chip ' + (v.pnl > 0.004 ? 'up' : v.pnl < -0.004 ? 'dn' : '');
    var d = Math.max(1, dayN(tNow));
    $('dayLabel').textContent = 'Day ' + d; $('hudDay').textContent = 'Day ' + d;
    $('startedLabel').textContent = 'started ' + fmtTime(doc.experiment.started_at, true) + ' TRT';
    $('goalText').textContent = 'day ' + Math.min(d, 30) + ' of 30'; $('goalBar').style.width = Math.min(100, d / 30 * 100) + '%';
    $('subline').textContent = 'Started with ' + usd(doc.experiment.bankroll_usd, 0) + ' of pretend money, copying ' + doc.wallets.length + ' real wallets on Robinhood Chain. ' +
      (v.trades.length ? v.trades.length + ' paper trade' + (v.trades.length === 1 ? '' : 's') + ' so far.' : 'No copied trades yet: the pack has been quiet since the start.');
  }

  function renderStats(v) {
    var wr = v.winRate;
    $('winRate').textContent = wr == null ? '—' : Math.round(wr * 100) + '%';
    $('ringFg').style.strokeDashoffset = 314.16 * (1 - (wr || 0));
    $('winFoot').textContent = v.sells ? v.wins + ' wins / ' + (v.sells - v.wins) + ' losses (closed trades)' : 'no closed trades yet';
    var m = Math.min(v.mdd, 50); // gauge full scale = 50%
    $('gaugeFg').style.strokeDashoffset = 182.2 * (1 - m / 50);
    $('needle').style.transform = 'rotate(' + (-90 + 180 * m / 50) + 'deg)';
    count('mdd', v.mdd, function (x) { return x.toFixed(1) + '%'; });
    count('nTrades', v.trades.length, function (x) { return Math.round(x); });
    $('nBuys').textContent = v.buys; $('nSells').textContent = v.sells;
    $('nSkipped').textContent = REPLAY ? '–' : (doc.skipped || []).length;
    count('realized', v.realized, sgnUsd);
    var s = doc.summary || {};
    $('unrealized').textContent = REPLAY ? '—' : sgnUsd(s.unrealized_pnl_usd || 0);
    $('fees').textContent = usd(v.fees);
    var c = $('combo'); if (v.streak >= 2) { c.hidden = false; c.querySelector('b').textContent = v.streak; } else c.hidden = true;
  }

  /* ---------- chart ---------- */
  function smooth(pts) {
    if (pts.length < 3) return pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    var d = 'M' + pts[0][0] + ' ' + pts[0][1];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2, k = 0.18;
      var c1x = p1[0] + (p2[0] - p0[0]) * k, c1y = p1[1] + (p2[1] - p0[1]) * k, c2x = p2[0] - (p3[0] - p1[0]) * k, c2y = p2[1] - (p3[1] - p1[1]) * k;
      c1x = Math.min(Math.max(c1x, p1[0]), p2[0]); c2x = Math.min(Math.max(c2x, p1[0]), p2[0]);
      var lo = Math.min(p1[1], p2[1]), hi = Math.max(p1[1], p2[1]); c1y = Math.min(Math.max(c1y, lo), hi); c2y = Math.min(Math.max(c2y, lo), hi);
      d += ' C' + c1x.toFixed(1) + ' ' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ' ' + c2y.toFixed(1) + ' ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1);
    }
    return d;
  }

  var chartGeom = null;
  function renderChart(v, tCut, animate) {
    var svg = $('chartSvg'), box = $('chart').getBoundingClientRect();
    var W = Math.max(260, box.width), H = Math.max(120, box.height), L = 52, R = 18, T = 16, Bm = 28;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.innerHTML = '';
    var B = doc.experiment.bankroll_usd;
    var t0 = ms(doc.experiment.started_at), t1 = Math.max(ms(doc.updated_at), t0 + 36e5, lastTs());
    var all = doc.balance_history.map(function (h) { return h.equity; }).concat([B]);
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = Math.max((hi - lo) * 0.18, B * 0.01);
    lo -= pad; hi += pad;
    var X = function (t) { return L + (t - t0) / (t1 - t0) * (W - L - R); }, Y = function (e) { return T + (hi - e) / (hi - lo) * (H - T - Bm); };
    var defs = svgEl('defs', {});
    defs.innerHTML = '<linearGradient id="lineG" x1="0" x2="1"><stop offset="0" stop-color="var(--amber-2)"/><stop offset="1" stop-color="var(--amber)"/></linearGradient>' +
      '<linearGradient id="areaG" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--amber)" stop-opacity=".38"/><stop offset=".7" stop-color="var(--amber)" stop-opacity=".04"/><stop offset="1" stop-color="var(--amber)" stop-opacity="0"/></linearGradient>' +
      '<clipPath id="reveal"><rect id="revealRect" x="0" y="0" width="' + (animate ? 0 : W) + '" height="' + H + '"/></clipPath>';
    svg.appendChild(defs);
    var g = svgEl('g', { class: 'grid' }), ax = svgEl('g', { class: 'axis' });
    for (var i = 0; i <= 4; i++) {
      var e = lo + (hi - lo) * i / 4, y = Y(e);
      g.appendChild(svgEl('line', { x1: L, x2: W - R, y1: y, y2: y }));
      var tx = svgEl('text', { x: L - 8, y: y + 4, 'text-anchor': 'end' }); tx.textContent = '$' + e.toFixed(e >= 1000 ? 0 : 2); ax.appendChild(tx);
    }
    var nx = W < 500 ? 3 : 6;
    for (i = 0; i <= nx; i++) {
      var t = t0 + (t1 - t0) * i / nx, tt = svgEl('text', { x: X(t), y: H - 8, 'text-anchor': i === 0 ? 'start' : i === nx ? 'end' : 'middle' });
      tt.textContent = fmtTime(t, (t1 - t0) > 864e5 * 1.5); ax.appendChild(tt);
    }
    svg.appendChild(g); svg.appendChild(ax);
    svg.appendChild(svgEl('line', { class: 'base', x1: L, x2: W - R, y1: Y(B), y2: Y(B) }));
    var pts = [[X(t0), Y(B)]], meta = [{ ts: doc.experiment.started_at, equity: B, event: 'start' }];
    v.hist.forEach(function (h) { var p = [X(ms(h.ts)), Y(h.equity)]; pts.push(p); meta.push(h); });
    if (REPLAY && tCut < t1) { var lastE = v.equity; pts.push([X(tCut), Y(lastE)]); meta.push({ ts: new Date(tCut).toISOString(), equity: lastE, event: 'now' }); }
    var lineD = smooth(pts);
    var cg = svgEl('g', { 'clip-path': 'url(#reveal)' });
    cg.appendChild(svgEl('path', { class: 'area', d: lineD + ' L' + pts[pts.length - 1][0] + ' ' + (H - Bm) + ' L' + pts[0][0] + ' ' + (H - Bm) + ' Z' }));
    var line = svgEl('path', { class: 'line', d: lineD }); cg.appendChild(line);
    var byId = {}; v.trades.forEach(function (t) { byId[t.id] = t; });
    meta.forEach(function (m, k) { if (m.event === 'trade' && byId[m.trade_id]) cg.appendChild(svgEl('circle', { class: 'mk ' + byId[m.trade_id].side, cx: pts[k][0], cy: pts[k][1], r: 4.5 })); });
    svg.appendChild(cg);
    var hp = pts[pts.length - 1];
    var head = svgEl('g', {}); head.appendChild(svgEl('circle', { class: 'head-ring', cx: hp[0], cy: hp[1], r: 5 })); head.appendChild(svgEl('circle', { class: 'head', cx: hp[0], cy: hp[1], r: 5 }));
    svg.appendChild(head);
    var xh = svgEl('line', { class: 'xh', y1: T, y2: H - Bm, x1: -10, x2: -10 }); svg.appendChild(xh);
    if (!v.trades.length && !REPLAY) {
      var n = svgEl('text', { class: 'empty-note', x: (L + W - R) / 2, y: T + 22, 'text-anchor': 'middle' }); n.textContent = 'Flat line = no copied trades yet. Honest, if boring.'; svg.appendChild(n);
    }
    chartGeom = { pts: pts, meta: meta, byId: byId, xh: xh, W: W };
    if (animate && !RM) {
      head.style.opacity = 0;
      var rr = $('revealRect'), t00 = performance.now(), D = 1800;
      (function step(t) { var k = Math.min(1, (t - t00) / D), e = 1 - Math.pow(1 - k, 3); rr.setAttribute('width', W * e); if (k < 1) requestAnimationFrame(step); else head.style.opacity = 1; })(t00);
    } else if (animate) { $('revealRect').setAttribute('width', W); }
    $('chartSvg').setAttribute('aria-label', 'Paper bankroll from ' + usd(B) + ' to ' + usd(v.equity) + ', ' + v.trades.length + ' trades, max drawdown ' + v.mdd.toFixed(1) + '%');
  }

  function chartHover(ev) {
    if (!chartGeom) return;
    var box = $('chart').getBoundingClientRect(), x = (ev.clientX - box.left) / box.width * chartGeom.W, best = 0;
    chartGeom.pts.forEach(function (p, i) { if (Math.abs(p[0] - x) < Math.abs(chartGeom.pts[best][0] - x)) best = i; });
    var p = chartGeom.pts[best], m = chartGeom.meta[best], tip = $('tip');
    chartGeom.xh.setAttribute('x1', p[0]); chartGeom.xh.setAttribute('x2', p[0]);
    var t = m.trade_id && chartGeom.byId[m.trade_id], s = fmtTime(m.ts, true) + ' TRT\nequity ' + usd(m.equity);
    if (t) s += '\n' + t.side.toUpperCase() + ' ' + (t.token.symbol || '?') + ' ' + usd(t.size_usd) + ' · ' + t.label + (t.side === 'sell' ? ' · ' + sgnUsd(t.realized_pnl_usd) : '');
    else s += '\n' + ({ start: 'experiment start', mark: 'mark-to-market check', now: 'replay' }[m.event] || m.event);
    tip.textContent = ''; s.split('\n').forEach(function (l, i) { if (i) tip.appendChild(document.createElement('br')); tip.appendChild(document.createTextNode(l)); });
    tip.hidden = false; tip.style.left = (p[0] / chartGeom.W * box.width) + 'px'; tip.style.top = (p[1] / (box.height) * box.height) + 'px';
  }

  /* ---------- sniff log ---------- */
  function termLine(t, fresh) {
    var ln = el('div', 'ln' + (fresh ? ' fresh' : ''));
    ln.appendChild(el('span', 't', fmtClock(t.ts)));
    ln.appendChild(el('span', t.side, t.side === 'buy' ? 'BUY ' : 'SELL'));
    var w = el('span', 'what');
    w.appendChild(document.createTextNode((t.token.symbol || shortA(t.token.address)) + ' ' + usd(t.size_usd) + ' @ ' + price(t.fill_price_usd) + ' '));
    w.appendChild(el('em', null, '← ' + t.label));
    if (t.side === 'sell') { w.appendChild(document.createTextNode(' ')); w.appendChild(el('span', t.realized_pnl_usd > 0 ? 'pnl-up' : 'pnl-dn', sgnUsd(t.realized_pnl_usd))); }
    ln.appendChild(w);
    var a = el('a', 'tx', 'tx ' + t.tx_hash.slice(0, 8) + '↗'); a.href = t.tx_url; a.target = '_blank'; a.rel = 'noopener';
    a.setAttribute('aria-label', 'Open the real transaction ' + t.tx_hash + ' on the explorer'); ln.appendChild(a);
    return ln;
  }
  function sysLine(ts, text) { var ln = el('div', 'ln'); ln.appendChild(el('span', 't', fmtClock(ts))); ln.appendChild(el('span', 'sys', '▸')); var w = el('span', 'what', text); w.style.gridColumn = 'span 2'; ln.appendChild(w); return ln; }
  function renderTerm(v, freshIds) {
    var term = $('term'), stick = term.scrollTop + term.clientHeight >= term.scrollHeight - 30;
    term.innerHTML = '';
    var lines = [{ ts: doc.experiment.started_at, sys: 'experiment started · ' + usd(doc.experiment.bankroll_usd) + ' paper bankroll · ' + doc.wallets.length + ' wallets locked in' }];
    v.trades.forEach(function (t) { lines.push({ ts: t.ts, t: t }); });
    if (!REPLAY) (doc.runs_log || []).forEach(function (r) {
      if (r.kind === 'run') lines.push({ ts: r.at, sys: 'wake · ' + r.new_swaps + ' new swap' + (r.new_swaps === 1 ? '' : 's') + ' seen, ' + r.copied + ' copied, ' + r.skipped + ' skipped' + ((r.wallets_failed || []).length ? ' · ' + r.wallets_failed.length + ' wallet read(s) failed' : '') });
    });
    lines.sort(function (a, b) { return ms(a.ts) - ms(b.ts); });
    lines.slice(-250).forEach(function (l) { term.appendChild(l.t ? termLine(l.t, freshIds && freshIds[l.t.id]) : sysLine(l.ts, l.sys)); });
    var c = el('div', 'ln'); c.appendChild(el('span', 't', '')); c.appendChild(el('span', 'sys', '$')); var cw = el('span', 'what'); cw.appendChild(el('span', 'cursor')); c.appendChild(cw); term.appendChild(c);
    if (stick || first || REPLAY) term.scrollTop = term.scrollHeight;
  }

  /* ---------- positions ---------- */
  function renderPositions(v) {
    var box = $('positions'); box.innerHTML = '';
    var list;
    if (REPLAY) {
      var lots = {};
      v.trades.forEach(function (t) {
        var k = t.wallet + t.token.address, L = lots[k] || (lots[k] = { label: t.label, token: t.token, qty: 0, cost: 0, px: t.fill_price_usd });
        if (t.side === 'buy') { L.qty += t.qty; L.cost += t.size_usd; } else { var f = L.qty ? Math.min(1, t.qty / L.qty) : 1; L.qty -= t.qty; L.cost *= (1 - f); }
        L.px = t.market_price_usd;
      });
      list = Object.keys(lots).map(function (k) { var L = lots[k]; return { label: L.label, token: L.token, value_usd: L.qty * L.px, cost_usd: L.cost, unrealized_pnl_usd: L.qty * L.px - L.cost, qty: L.qty }; }).filter(function (p) { return p.qty > 1e-12; });
    } else list = doc.positions || [];
    $('posSub').textContent = list.length ? list.length + ' open · marked ' + (REPLAY ? 'at last fill' : 'at current price') : '';
    if (!list.length) { box.appendChild(el('p', 'none', 'Nothing open. All paws on the ground.')); return; }
    list.forEach(function (p) {
      var r = el('div', 'pos'), u = p.unrealized_pnl_usd;
      var nm = el('b'); var a = el('a', null, p.token.symbol || shortA(p.token.address)); a.href = p.token.chart_url || '#'; a.target = '_blank'; a.rel = 'noopener'; nm.appendChild(a); r.appendChild(nm);
      r.appendChild(el('span', 'r', usd(p.value_usd)));
      r.appendChild(el('span', 'meta', 'via ' + p.label + ' · cost ' + usd(p.cost_usd) + (p.price_stale ? ' · price stale' : '')));
      r.appendChild(el('span', 'r meta ' + (u > 0 ? 'up' : u < 0 ? 'dn' : ''), sgnUsd(u)));
      box.appendChild(r);
    });
  }

  /* ---------- the pack ---------- */
  function spark(vals, color) {
    var s = svgEl('svg', { class: 'spark', viewBox: '0 0 160 46', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
    if (!vals || vals.length < 2) vals = [0, 0];
    var lo = Math.min.apply(null, vals.concat([0])), hi = Math.max.apply(null, vals.concat([0])), r = hi - lo || 1;
    var pts = vals.map(function (v, i) { return [i / (vals.length - 1) * 158 + 1, 42 - (v - lo) / r * 38]; });
    var id = 'sg' + Math.random().toString(36).slice(2, 8);
    s.innerHTML = '<defs><linearGradient id="' + id + '" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="' + color + '" stop-opacity=".35"/><stop offset="1" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs>';
    var d = smooth(pts);
    s.appendChild(svgEl('path', { d: d + ' L159 46 L1 46 Z', fill: 'url(#' + id + ')' }));
    s.appendChild(svgEl('line', { x1: 0, x2: 160, y1: 42 - (0 - lo) / r * 38, y2: 42 - (0 - lo) / r * 38, stroke: 'currentColor', 'stroke-opacity': .15, 'stroke-dasharray': '3 4' }));
    s.appendChild(svgEl('path', { class: 'l', d: d, stroke: color }));
    return s;
  }
  function renderPack(v, glowSince) {
    var box = $('pack'); box.innerHTML = '';
    doc.wallets.forEach(function (w, i) {
      var mine = v.trades.filter(function (t) { return t.wallet === w.address; });
      var my = mine.filter(function (t) { return t.side === 'sell'; }).reduce(function (a, t) { return a + t.realized_pnl_usd; }, 0);
      var last = mine.length ? mine[mine.length - 1] : null;
      var c = el('article', 'dog' + (last && glowSince && ms(last.ts) >= glowSince ? ' glow' : '')); c.id = 'dog-' + w.address;
      var top = el('div', 'dog-top'), av = el('span', 'av', w.label[0]); av.style.background = COLORS[i % 8]; top.appendChild(av);
      var nm = el('div'); nm.appendChild(el('h3', null, w.label)); var a = el('a', 'addr', shortA(w.address) + ' ↗'); a.href = w.explorer_url; a.target = '_blank'; a.rel = 'noopener'; a.setAttribute('aria-label', w.label + ': open wallet ' + w.address + ' on the explorer'); nm.appendChild(a); top.appendChild(nm);
      top.appendChild(el('span', 'rank', '#' + w.rank)); c.appendChild(top);
      c.appendChild(el('span', 'live-tag', '● NEW TRADE'));
      var sel = w.selection || {};
      var sp = spark(sel.pnl_curve, COLORS[i % 8]); c.appendChild(sp);
      var st = el('div', 'dog-stats');
      function cell(k, val, cls) { var d = el('div'); d.appendChild(el('span', null, k)); d.appendChild(el('b', cls || '', val)); st.appendChild(d); }
      cell('their P&L · ' + Math.round(sel.history_hours || 0) + 'h', sgnUsd(sel.realized_pnl_usd), sel.realized_pnl_usd > 0 ? 'up' : 'dn');
      cell('their win rate', sel.win_rate == null ? '—' : Math.round(sel.win_rate * 100) + '% of ' + sel.matched_sells);
      cell('copied by me', mine.length + (mine.length === 1 ? ' trade' : ' trades'));
      cell('my P&L from them', mine.some(function (t) { return t.side === 'sell'; }) ? sgnUsd(my) : '—', my > 0 ? 'up' : my < 0 ? 'dn' : '');
      c.appendChild(st);
      c.title = 'Sparkline: this wallet\'s own realized P&L over the ' + Math.round(sel.history_hours || 0) + 'h before Corgi started following it.' + (last ? ' Last copied trade ' + fmtTime(last.ts, true) + ' TRT.' : '');
      box.appendChild(c);
    });
  }
  function flashDog(addr) { var c = document.getElementById('dog-' + addr); if (!c) return; c.classList.remove('flash'); void c.offsetWidth; c.classList.add('flash', 'glow'); }

  /* ---------- mascot ---------- */
  var sayT = null;
  function say(text, mood, ms_) {
    var pup = document.querySelector('.pup'); pup.classList.remove('happy', 'sad', 'sniff', 'sleep'); if (mood) { void pup.offsetWidth; pup.classList.add(mood); }
    var b = $('say'); b.textContent = text; b.classList.add('on');
    clearTimeout(sayT); sayT = setTimeout(function () { b.classList.remove('on'); }, ms_ || 3800);
  }
  function idleMood(v) {
    if (!v.trades.length) return say('Nose down, waiting for the pack to move.', 'sniff', 5000);
    if (v.pnl > 0.005) return say('Up ' + sgnUsd(v.pnl) + ' on paper. Tail: wagging.', 'happy', 5000);
    if (v.pnl < -0.005) return say('Down ' + usd(-v.pnl) + '. Copying is harder than it looks.', 'sad', 5000);
    say('Flat. Fees ate the treats.', 'sniff', 5000);
  }

  /* ---------- method ---------- */
  function renderMethod() {
    var ol = $('methodList'); ol.innerHTML = '';
    (doc.experiment.method || []).forEach(function (m) { ol.appendChild(el('li', null, m)); });
    var r = doc.experiment.rules || {}, as = $('assume'); as.innerHTML = '';
    [['bankroll', usd(doc.experiment.bankroll_usd, 0)], ['size', r.size_pct_of_equity + '% of equity'], ['max per token', r.max_token_pct_of_equity + '%'], ['delay', r.delay_seconds + 's'],
     ['slippage', r.slippage_pct + '%'], ['fee', r.fee_pct_per_side + '% / side'], ['gas', usd(r.gas_usd_per_swap)]].forEach(function (x) { as.appendChild(el('span', null, x[0] + ': ' + x[1])); });
    var h = $('health'); h.innerHTML = '';
    var runs = (doc.runs_log || []).slice(-1)[0], ul = el('ul');
    if (runs) {
      Object.keys(runs.sources || {}).forEach(function (k) { var s = runs.sources[k]; var li = el('li'); li.appendChild(el('b', s.ok ? 'good' : 'bad', s.ok ? '✓ ' : '✗ ')); li.appendChild(document.createTextNode(k + ': ' + s.calls + ' calls' + (s.failed_calls ? ', ' + s.failed_calls + ' failed' + (s.errors && s.errors[0] ? ' (' + s.errors[0] + ')' : '') : ''))); ul.appendChild(li); });
      (runs.wallets_failed || []).concat(runs.notes || []).slice(0, 8).forEach(function (n) { ul.appendChild(el('li', null, n)); });
    }
    var tried = ((doc.experiment.selection || {}).sources_tried) || {};
    Object.keys(tried).forEach(function (k) { ul.appendChild(el('li', null, k.replace(/_/g, ' ') + ': ' + tried[k])); });
    var sk = (doc.skipped || []).slice(-6).reverse();
    if (sk.length) { var li = el('li', null, 'Recently skipped: '); sk.forEach(function (s, i) { var a = el('a', null, (s.token.symbol || '?') + ' ' + s.side); a.href = s.tx_url; a.target = '_blank'; a.rel = 'noopener'; a.title = s.reason; li.appendChild(a); li.appendChild(document.createTextNode(' (' + s.reason + ')' + (i < sk.length - 1 ? '; ' : ''))); }); ul.appendChild(li); }
    var sel = doc.experiment.selection || {};
    ul.appendChild(el('li', null, 'Selection ' + fmtTime(sel.at, true) + ' TRT: ' + sel.signers_seen + ' signers seen in ' + sel.universe_pools + ' pools, ' + sel.candidates_checked + ' checked, ' + sel.passed + ' passed. Excluded: ' + Object.keys(sel.excluded || {}).map(function (k) { return k.replace(/_/g, ' ') + ' ' + sel.excluded[k]; }).join(', ') + '.'));
    h.appendChild(ul);
  }

  /* ---------- full render ---------- */
  function renderAll(fresh) {
    var tNow = ms(doc.updated_at), v = view(Infinity), prevRun = (doc.runs_log || []).filter(function (r) { return r.kind === 'run'; }).slice(-2)[0];
    var glowSince = prevRun ? ms(prevRun.at) : ms(doc.experiment.started_at);
    var runs = (doc.runs_log || []).filter(function (r) { return r.kind === 'run'; });
    if (runs.length >= 2) glowSince = ms(runs[runs.length - 2].at);
    renderLive(); renderHero(v, tNow); renderStats(v); renderChart(v, Infinity, first); renderTerm(v, fresh); renderPositions(v); renderPack(v, glowSince); renderMethod();
    if (first) idleMood(v);
    first = false;
  }

  /* ---------- replay ---------- */
  function replay() {
    $('hud').hidden = false;
    var t0 = ms(doc.experiment.started_at), t1 = Math.max(ms(doc.updated_at), t0 + 60e3, lastTs());
    var ev = doc.balance_history.map(function (h) { return ms(h.ts); }).filter(function (t) { return t > t0; });
    // timeline: 55% proportional to real time, 45% equal slots per event, so quiet hours don't eat the video
    var knots = [[0, t0]], n = ev.length;
    ev.forEach(function (t, i) { knots.push([0.55 * (t - t0) / (t1 - t0) + 0.45 * (i + 1) / Math.max(1, n), t]); });
    knots.push([1, t1]);
    function realAt(f) { for (var i = 1; i < knots.length; i++) if (f <= knots[i][0]) { var a = knots[i - 1], b = knots[i], k = (f - a[0]) / ((b[0] - a[0]) || 1); return a[1] + (b[1] - a[1]) * k; } return t1; }
    var shown = {}, start = null, D = REPLAY_S * 1000, intro = 1200;
    var v0 = view(t0); renderHero(v0, t0); renderStats(v0); renderChart(v0, t0, false); renderTerm(v0); renderPositions(v0); renderPack(v0, null); renderMethod(); renderLive();
    $('equity').textContent = usd(doc.experiment.bankroll_usd);
    say('Day 1. ' + usd(doc.experiment.bankroll_usd, 0) + ' of pretend money and ' + doc.wallets.length + ' wallets to follow. Let\'s go.', 'sniff', 3000);
    var skip = false; $('hudSkip').onclick = function () { skip = true; };
    var lastDraw = 0;
    function frame(ts) {
      if (start == null) start = ts;
      var f = Math.min(1, Math.max(0, (ts - start - intro) / D)); if (skip) f = 1;
      var tv = realAt(f), v = view(tv);
      $('hudBar').style.width = (f * 100) + '%';
      var newT = v.trades.filter(function (t) { return !shown[t.id]; });
      if (newT.length || ts - lastDraw > 80 || f === 1) {
        lastDraw = ts;
        renderHero(v, tv); $('equity').textContent = usd(v.equity); renderStats(v); renderChart(v, tv, false);
        if (newT.length) {
          var fr = {}; newT.forEach(function (t) { shown[t.id] = 1; fr[t.id] = 1; flashDog(t.wallet); });
          renderTerm(v, fr); renderPositions(v);
          var t = newT[newT.length - 1];
          if (t.side === 'buy') say('Sniff… ' + t.label + ' bought ' + (t.token.symbol || 'something') + '. Copying ' + usd(t.size_usd) + '.', 'sniff', 2200);
          else if (t.realized_pnl_usd > 0) say(sgnUsd(t.realized_pnl_usd) + ' on ' + (t.token.symbol || '?') + '! Good dog, ' + t.label + '.', 'happy', 2200);
          else say('Ouch, ' + sgnUsd(t.realized_pnl_usd) + ' on ' + (t.token.symbol || '?') + '.', 'sad', 2200);
          var pk = $('pack'); pk.querySelectorAll('.dog').forEach(function (d) { d.classList.remove('glow'); }); newT.forEach(function (t) { var d = document.getElementById('dog-' + t.wallet); if (d) d.classList.add('glow'); });
        }
      }
      if (f < 1) return requestAnimationFrame(frame);
      renderTerm(view(Infinity)); renderPositions(view(Infinity));
      setTimeout(function () {
        var vf = view(Infinity), B = doc.experiment.bankroll_usd;
        $('finaleNum').textContent = usd(B, 0) + ' → ' + usd(vf.equity);
        $('finaleNum').className = 'finale-num ' + (vf.pnl > 0.005 ? 'up' : vf.pnl < -0.005 ? 'dn' : '');
        var d = Math.max(1, dayN(t1));
        $('finaleText').textContent = 'Day 1 to Day ' + d + ' · ' + vf.trades.length + ' paper trade' + (vf.trades.length === 1 ? '' : 's') + ' · win rate ' + (vf.winRate == null ? '—' : Math.round(vf.winRate * 100) + '%') + ' · max drawdown ' + vf.mdd.toFixed(1) + '%';
        $('finale').hidden = false; $('hud').hidden = true; document.documentElement.classList.add('replay-done');
        idleMood(vf);
      }, 700);
    }
    requestAnimationFrame(frame);
  }

  /* ---------- boot ---------- */
  function load() {
    return fetch(DATA + 'copy.json?t=' + Math.floor(Date.now() / 6e4), { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('copy.json ' + r.status); return r.json(); });
  }
  function reveal() {
    var els = document.querySelectorAll('.card, .tile, .pack-sec');
    if (RM || REPLAY || !('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }); }, { rootMargin: '0px 0px -8% 0px' });
    els.forEach(function (e) { e.classList.add('rv'); io.observe(e); });
  }
  $('themeBtn').addEventListener('click', function () {
    var t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = t; try { localStorage.setItem('corgi-copy-theme', t); } catch (e) {}
    if (doc) renderChart(view(Infinity), Infinity, false);
  });
  $('chart').addEventListener('mousemove', chartHover);
  $('chart').addEventListener('mouseleave', function () { $('tip').hidden = true; if (chartGeom) { chartGeom.xh.setAttribute('x1', -10); chartGeom.xh.setAttribute('x2', -10); } });
  document.querySelector('.pup').addEventListener('click', function () {
    var lines = ['Every trade here links to a real transaction. Go on, check me.', 'Paper money, real prices. My human keeps the real treats.', 'I copy 60 seconds late, on purpose. That\'s how it works in real life too.', 'Win rate isn\'t profit. Ask me about fees.', 'Short legs, long memory: every number is in copy.json.'];
    say(lines[Math.floor(Math.random() * lines.length)], 'happy');
  });
  document.querySelector('.pup').setAttribute('tabindex', '0');
  document.querySelector('.pup').setAttribute('role', 'button');
  document.querySelector('.pup').setAttribute('aria-label', 'Corgi. Click for a remark.');
  var rz; window.addEventListener('resize', function () { clearTimeout(rz); rz = setTimeout(function () { if (doc && !REPLAY) renderChart(view(Infinity), Infinity, false); }, 150); });

  load().then(function (d) {
    doc = d;
    if (REPLAY) { document.title = 'Replay · ' + document.title; replay(); }
    else { renderAll(); reveal(); }
    setInterval(function () { if (doc) renderLive(); }, 30000);
    if (!REPLAY) setInterval(function () {
      load().then(function (d2) {
        if (d2.updated_at === doc.updated_at) return;
        var old = {}; doc.trades.forEach(function (t) { old[t.id] = 1; });
        doc = d2; var fresh = {}; d2.trades.forEach(function (t) { if (!old[t.id]) fresh[t.id] = 1; });
        renderAll(fresh); Object.keys(fresh).forEach(function (id) { var t = d2.trades.find(function (x) { return x.id === id; }); if (t) flashDog(t.wallet); });
      }).catch(function () {});
    }, 5 * 60 * 1000);
  }).catch(function (e) {
    $('liveText').textContent = 'data unavailable'; $('live').classList.add('dead');
    $('subline').textContent = 'Couldn\'t load copy.json (' + e.message + '). Nothing shown rather than something made up.';
  });
})();
