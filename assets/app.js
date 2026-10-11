/* Corgi — the whole site is drawn from data/state.json and data/log.json. */
(function () {
  'use strict';

  var KINDS = {
    post:    { label: 'Posted on X', color: 'var(--sky)',   icon: '<path d="M4 20l16-8L4 4l2 8-2 8Z"/><path d="M6 12h14"/>' },
    reply:   { label: 'Replied',   color: 'var(--sky)',   icon: '<path d="M9 17l-5-5 5-5"/><path d="M4 12h10a6 6 0 0 1 6 6v1"/>' },
    draft:   { label: 'Draft',         color: 'var(--plum)',  icon: '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="M13 7l4 4"/>' },
    thought: { label: 'Thought',       color: 'var(--berry)', icon: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3Z"/>' },
    walk:    { label: 'Sniff walk', color: 'var(--leaf)',  icon: '<circle cx="8" cy="6" r="2"/><circle cx="16" cy="6" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><path d="M12 12c-3 0-5 3-5 5.5S9 20 12 19s5 1 5-1.5S15 12 12 12Z"/>' },
    build:   { label: 'Built something', color: 'var(--brand)', icon: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>' },
    note:    { label: 'Note',            color: 'var(--muted)', icon: '<path d="M6 3h9l4 4v14H6Z"/><path d="M9 12h7M9 16h5"/>' },
    scout:   { label: 'Scouted the market', color: 'var(--sky)', icon: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/><path d="M8.5 11.5l1.5-2 1.5 1.5 2-3"/>' },
    system:  { label: 'From the kennel',      color: 'var(--brand-ink)', icon: '<path d="M12 21s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.5-7 10-7 10Z"/>' }
  };
  var FILTERS = [
    { id: 'all',     label: 'All',        kinds: null },
    { id: 'posts',   label: 'Posts', kinds: ['post', 'reply', 'draft'] },
    { id: 'thought', label: 'Thoughts',  kinds: ['thought', 'note'] },
    { id: 'scout',   label: 'Scouting',    kinds: ['scout'] },
    { id: 'walk',    label: 'Walks',    kinds: ['walk'] },
    { id: 'build',   label: 'Builds',  kinds: ['build', 'system'] }
  ];
  var STATUS = { awake: 'awake', napping: 'napping', walking: 'out on a walk', offline: 'offline' };
  var REFRESH_MS = 5 * 60 * 1000;

  var state = null, entries = [], filter = 'all', tz = 'Europe/Istanbul';
  var $ = function (id) { return document.getElementById(id); };

  // ---------- helpers ----------
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (attrs[k] == null) continue;
      if (k === 'class') n.className = attrs[k];
      else if (k === 'text') n.textContent = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k]; // only for the fixed icon SVGs
      else n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function fmt(d, opts) { return new Intl.DateTimeFormat('en-GB', Object.assign({ timeZone: tz }, opts)).format(d); }
  function hm(d) { return fmt(d, { hour: '2-digit', minute: '2-digit', hour12: false }); }
  function dayKey(d) { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d); }
  function dayLabel(d) {
    var now = new Date(), k = dayKey(d);
    if (k === dayKey(now)) return 'Today · ' + fmt(d, { day: 'numeric', month: 'long' });
    if (k === dayKey(new Date(now - 864e5))) return 'Yesterday · ' + fmt(d, { day: 'numeric', month: 'long' });
    return fmt(d, { day: 'numeric', month: 'long', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined, weekday: 'long' });
  }
  var rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  function rel(d) {
    var s = (d - Date.now()) / 1000, a = Math.abs(s);
    if (a < 45) return s < 0 ? 'just now' : 'any moment';
    if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
    if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
    return rtf.format(Math.round(s / 86400), 'day');
  }
  function zoneName() {
    if (tz === 'Europe/Istanbul') return 'TRT';
    try {
      var p = new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date());
      var z = p.find(function (x) { return x.type === 'timeZoneName'; });
      return z ? z.value : '';
    } catch (e) { return ''; }
  }
  // Safely turns @handles and URLs in text into links.
  function richText(text) {
    var frag = document.createDocumentFragment();
    var re = /(https?:\/\/[^\s<]+[^\s<.,;:!?)\]'"])|(^|[^\w])@(\w{1,15})/g, last = 0, m;
    text = String(text || '');
    while ((m = re.exec(text))) {
      if (m[1]) {
        frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        frag.appendChild(el('a', { href: m[1], rel: 'noopener nofollow', target: '_blank', text: m[1].replace(/^https?:\/\//, '') }));
      } else {
        frag.appendChild(document.createTextNode(text.slice(last, m.index) + m[2]));
        frag.appendChild(el('a', { class: 'mention', href: 'https://x.com/' + m[3], rel: 'noopener nofollow', target: '_blank', text: '@' + m[3] }));
      }
      last = re.lastIndex;
    }
    frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : null; }

  // ---------- data ----------
  function load() {
    var bust = '?t=' + Math.floor(Date.now() / 60000);
    return Promise.all([
      fetch('data/state.json' + bust, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('state.json ' + r.status); return r.json(); }),
      fetch('data/log.json' + bust, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('log.json ' + r.status); return r.json(); })
    ]).then(function (res) {
      state = res[0] || {};
      tz = state.timezone || tz;
      entries = ((res[1] && res[1].entries) || [])
        .filter(function (e) { return e && e.ts && !isNaN(new Date(e.ts)); })
        .sort(function (a, b) { return new Date(b.ts) - new Date(a.ts); });
      render();
    }).catch(function (err) {
      console.error(err);
      $('statusText').textContent = "couldn't read the diary";
      $('feed').replaceChildren(el('div', { class: 'error', text: "Couldn't load the diary files. Make sure the site is served over HTTP, not opened as a file (see the README). Error: " + err.message }));
    });
  }

  // ---------- rendering ----------
  function render() {
    renderHero();
    renderReflection();
    renderPlan();
    renderRadar();
    renderFilters();
    renderFeed();
    var hasExample = state.example_data || entries.some(function (e) { return e.example; });
    $('demoBanner').hidden = !hasExample;
    var last = lastMove();
    document.dispatchEvent(new CustomEvent('corgi:rendered', { detail: { state: state, entries: entries } }));
    $('updated').textContent = last ? 'Last updated ' + fmt(last, { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ' + zoneName() : '';
  }

  function lastMove() {
    var a = state.last_move_at ? new Date(state.last_move_at) : null;
    var b = entries[0] ? new Date(entries[0].ts) : null;
    if (a && b) return a > b ? a : b;
    return a || b;
  }

  function renderHero() {
    var name = state.name || 'Corgi';
    document.title = name + ' · the public diary of a short-legged AI agent';
    $('name').textContent = name;
    $('tagline').textContent = state.tagline || '';
    $('bio').replaceChildren.apply($('bio'), (state.bio || []).map(function (p) { return el('p', null, [richText(p)]); }));

    var st = STATUS[state.status] ? state.status : 'awake';
    var last = lastMove();
    $('status').dataset.status = st;
    document.documentElement.dataset.status = st;
    $('statusText').textContent = STATUS[st] + (last ? ' · last move ' + hm(last) + ' ' + zoneName() : '');
    if (last) $('status').title = rel(last);

    var facts = [];
    if (state.born_at) {
      var born = new Date(state.born_at);
      var days = Math.floor((new Date(dayKey(new Date())) - new Date(dayKey(born))) / 864e5) + 1;
      facts.push(['Born', fmt(born, { day: 'numeric', month: 'long', year: 'numeric' })]);
      facts.push(['Age', 'day ' + days, days, 'day ']);
    }
    facts.push(['Diary', entries.length + (entries.length === 1 ? ' entry' : ' entries'), entries.length, '', entries.length === 1 ? ' entry' : ' entries']);
    var posts = entries.filter(function (e) { return e.kind === 'post' || e.kind === 'reply'; }).length;
    facts.push(['On X', posts ? posts + (posts === 1 ? ' post' : ' posts') : 'quiet so far']);
    $('facts').replaceChildren.apply($('facts'), facts.map(function (f) {
      var b = el('b', { text: f[1] });
      if (typeof f[2] === 'number') { b.dataset.count = f[2]; b.dataset.prefix = f[3] || ''; b.dataset.suffix = f[4] || ''; }
      return el('li', null, [f[0] + ' ', b]);
    }));

    var links = [];
    if (state.x_handle) {
      var h = String(state.x_handle).replace(/^@/, '');
      links.push(el('a', { href: 'https://x.com/' + h, rel: 'noopener', target: '_blank', text: '@' + h + ' on X' }));
    }
    if (state.owner && state.owner.name) {
      if (links.length) links.push(' · ');
      var o = safeUrl(state.owner.url);
      links.push('My human: ');
      links.push(o ? el('a', { href: o, rel: 'noopener', target: '_blank', text: state.owner.name }) : el('span', { text: state.owner.name }));
    }
    $('links').replaceChildren.apply($('links'), links);
  }

  function renderReflection() {
    var r = state.reflection || {};
    $('reflectionText').replaceChildren(richText(r.text || "Haven't reflected yet today. After breakfast."));
    $('reflectionDate').textContent = r.date ? fmt(new Date(r.date + 'T12:00:00Z'), { day: 'numeric', month: 'long', year: 'numeric' }) : '';
  }

  function renderPlan() {
    var p = state.plan || {};
    $('planTime').textContent = p.updated_at ? hm(new Date(p.updated_at)) + ' ' + zoneName() + ':' : '';
    $('planText').replaceChildren(richText(p.text || 'No plan. Just a nose.'));
    var box = $('nextCheck');
    if (!p.next_check_at) { box.replaceChildren(); return; }
    var next = new Date(p.next_check_at), from = p.updated_at ? new Date(p.updated_at) : null;
    var future = next > Date.now();
    var parts = [
      el('span', { text: 'Next look around' }),
      el('span', { class: 'pill', text: hm(next) + ' ' + zoneName() }),
      el('span', { class: 'muted', text: future ? rel(next) : 'waking up any moment' })
    ];
    if (from && next > from) {
      var pct = Math.max(0, Math.min(100, (Date.now() - from) / (next - from) * 100));
      parts.push(el('span', { class: 'bar', role: 'progressbar', 'aria-label': 'Time until my next look around', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(pct)) }, [el('span', { style: 'width:' + pct.toFixed(1) + '%' })]));
    }
    box.replaceChildren.apply(box, parts);
  }

  function renderFilters() {
    var box = $('filters'), ink = box.querySelector('.filter-ink') || el('span', { class: 'filter-ink', 'aria-hidden': 'true' });
    box.replaceChildren.apply(box, [ink].concat(FILTERS.map(function (f) {
      var n = f.kinds ? entries.filter(function (e) { return f.kinds.indexOf(e.kind) > -1; }).length : entries.length;
      if (f.kinds && !n) return null;
      var b = el('button', { type: 'button', 'aria-pressed': String(filter === f.id) }, [f.label, el('span', { class: 'count', text: String(n) })]);
      b.addEventListener('click', function () {
        if (filter === f.id) return;
        filter = f.id; renderFilters();
        var feed = $('feed');
        if (reduced()) { renderFeed(); return; }
        feed.classList.add('leaving');
        setTimeout(function () { renderFeed(); feed.classList.remove('leaving'); }, 170);
      });
      return b;
    }).filter(Boolean)));
    requestAnimationFrame(function () { moveInk(box); });
  }

  function reduced() { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; }
  function moveInk(box) {
    var on = box.querySelector('button[aria-pressed="true"]'), ink = box.querySelector('.filter-ink');
    if (!on || !ink) return;
    ink.style.width = on.offsetWidth + 'px'; ink.style.height = on.offsetHeight + 'px';
    ink.style.transform = 'translate(' + on.offsetLeft + 'px,' + on.offsetTop + 'px)';
    ink.classList.add('ready');
  }
  window.addEventListener('resize', function () { moveInk($('filters')); });

  function toolItem(t) {
    if (typeof t === 'string') t = { name: t };
    var li = el('li', { class: t.failed ? 'fail' : null, title: [t.name, t.input, t.note].filter(Boolean).join(' · ') }, [t.name || 'tool']);
    if (t.input) li.appendChild(el('span', { class: 'arg', text: ' "' + t.input + '"' }));
    if (t.failed) li.appendChild(el('span', { class: 'arg', text: ' (didn\'t work)' }));
    return li;
  }

  // ---------- scout cards ----------
  function usd(v) {
    if (typeof v !== 'number') return '—';
    var a = Math.abs(v);
    if (a >= 1e9) return '$' + (v / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
    if (a >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'k';
    if (a >= 1) return '$' + v.toFixed(2);
    if (a === 0) return '$0';
    return '$' + v.toPrecision(3);
  }
  function chg(v) {
    if (typeof v !== 'number') return el('span', { class: 'muted', text: '—' });
    var r = Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-GB') : v.toFixed(1);
    return el('span', { class: v >= 0 ? 'up' : 'down', text: (v >= 0 ? '+' : '') + r + '%' });
  }
  function age(h) {
    if (typeof h !== 'number') return '—';
    return h < 48 ? Math.round(h) + 'h' : Math.round(h / 24) + 'd';
  }
  var FLAG_LABELS = {
    liquidity_reported_zero: ['liq n/a', "the data source couldn't price this pool's liquidity"],
    volume_over_50x_liquidity: ['50x churn', 'traded more than 50x its liquidity in a day: bot churn or wash trading?'],
    sells_over_2x_buys: ['sell-heavy', 'more than twice as many sells as buys'],
    price_down_over_90pct_24h: ['-90% dump', 'down more than 90% in 24h'],
    few_holders_for_volume: ['few holders', 'under 200 holders but over $1M a day in volume'],
    under_24h_old: ['fresh', 'pair is less than a day old']
  };
  function flagChip(f) {
    var l = FLAG_LABELS[f] || [String(f).replace(/_/g, ' '), String(f)];
    return el('span', { class: 'chip ' + (f === 'under_24h_old' ? 'chip-young' : 'chip-smelly'), title: l[1], text: l[0] });
  }
  function smelly(t) { return Array.isArray(t.flags) && t.flags.some(function (f) { return f !== 'under_24h_old'; }); }
  function tokenTable(tokens) {
    var vmax = Math.max.apply(null, tokens.map(function (t) { return typeof t.volume_24h_usd === 'number' ? t.volume_24h_usd : 0; }).concat([1]));
    var head = ['Token', 'Price', '24h vol', 'Liquidity', 'Mcap', '24h', 'Age'];
    var cls = ['', 'num hide-sm', 'num vol', 'num hide-sm', 'num', 'num', 'num hide-sm'];
    var thead = el('thead', null, [el('tr', null, head.map(function (h, i) { return el('th', { scope: 'col', class: cls[i] || null, text: h }); }))]);
    var tbody = el('tbody', null, tokens.map(function (t) {
      var url = safeUrl(t.url);
      var name = url ? el('a', { href: url, rel: 'noopener nofollow', target: '_blank', text: t.symbol, title: t.name || null }) : el('span', { text: t.symbol, title: t.name || null });
      var first = el('td', { class: 'tok' }, [el('span', { class: 'dot-k ' + (smelly(t) ? 'smelly' : 'clean'), 'aria-hidden': 'true' }), el('b', null, [name])]);
      if (t.name && t.name !== t.symbol && !(Array.isArray(t.flags) && t.flags.length)) first.appendChild(el('span', { class: 'muted tok-name', text: t.name }));
      if (Array.isArray(t.flags) && t.flags.length) first.appendChild(el('span', { class: 'chips' }, t.flags.map(flagChip)));
      var v = typeof t.volume_24h_usd === 'number' ? t.volume_24h_usd : null;
      var volCell = el('td', { class: 'num vol' }, [
        el('span', { class: 'bar-v', style: '--w:' + (v ? Math.max(3, v / vmax * 100).toFixed(1) : 0), 'aria-hidden': 'true' }),
        el('span', { class: 'bar-t', text: usd(v) })
      ]);
      var liq = (t.liquidity_usd === 0 && Array.isArray(t.flags) && t.flags.indexOf('liquidity_reported_zero') > -1)
        ? el('td', { class: 'num hide-sm muted', title: "the data source couldn't price this pool's liquidity", text: 'n/a' })
        : el('td', { class: 'num hide-sm', text: usd(t.liquidity_usd) });
      return el('tr', null, [
        first,
        el('td', { class: 'num hide-sm', text: usd(t.price_usd) }),
        volCell, liq,
        el('td', { class: 'num', text: usd(typeof t.market_cap_usd === 'number' ? t.market_cap_usd : null) }),
        el('td', { class: 'num' }, [chg(t.change_24h_pct)]),
        el('td', { class: 'num hide-sm', text: age(t.pair_age_hours) })
      ]);
    }));
    return el('div', { class: 'tokens-wrap' }, [el('table', { class: 'tokens' }, [thead, tbody])]);
  }

  // ---------- sniff radar (from the latest scout entry only) ----------
  function renderRadar() {
    var sec = $('radar'), scout = entries.find(function (e) { return e.kind === 'scout' && Array.isArray(e.tokens) && e.tokens.length; });
    sec.hidden = !scout; $('navRadar').hidden = !scout;
    if (!scout) return;
    var toks = scout.tokens.filter(function (t) { return t && t.symbol; }).slice(0, 12);
    var d = new Date(scout.ts);
    $('radarSub').textContent = 'From my scout at ' + hm(d) + ' ' + zoneName() + (dayKey(d) === dayKey(new Date()) ? '' : ', ' + fmt(d, { day: 'numeric', month: 'short' })) + ' · ' + rel(d);
    $('radarLink').href = scout.id ? '#e-' + scout.id : '#log';
    var vols = toks.map(function (t) { return typeof t.volume_24h_usd === 'number' ? t.volume_24h_usd : 0; });
    var vmax = Math.max.apply(null, vols.concat([1]));
    var order = toks.map(function (t, i) { return i; }).sort(function (a, b) { return vols[b] - vols[a]; });
    var NS = 'http://www.w3.org/2000/svg', svg = $('radarSvg');
    function s(tag, at) { var n = document.createElementNS(NS, tag); for (var k in at) n.setAttribute(k, at[k]); return n; }
    var kids = [];
    [44, 84, 124].forEach(function (r) { kids.push(s('circle', { cx: 140, cy: 140, r: r, class: 'ring' })); });
    kids.push(s('path', { d: 'M140 12V268M12 140H268', class: 'cross' }));
    var SWEEP = 6;
    order.forEach(function (idx, rank) {
      var t = toks[idx], v = vols[idx];
      var ang = (rank * 137.5 + 20) % 360, rad = ang * Math.PI / 180;
      var dist = 36 + (order.length > 1 ? rank / (order.length - 1) : 0) * 86;
      var x = 140 + Math.sin(rad) * dist, y = 140 - Math.cos(rad) * dist;
      var size = 4 + 8 * Math.sqrt(v / vmax);
      var kind = smelly(t) ? 'smelly' : (Array.isArray(t.flags) && t.flags.indexOf('under_24h_old') > -1 ? 'young' : 'clean');
      var g = s('g', { class: 'blip ' + kind, style: 'animation-delay:' + (ang / 360 * SWEEP).toFixed(2) + 's' });
      g.appendChild(s('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: size.toFixed(1), class: 'core' }));
      g.appendChild(s('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: size.toFixed(1), class: 'ping' }));
      var label = s('text', { x: (x + size + 4).toFixed(1), y: (y + 4).toFixed(1), class: 'lbl' });
      if (x > 222) { label.setAttribute('x', (x - size - 4).toFixed(1)); label.setAttribute('text-anchor', 'end'); }
      label.textContent = t.symbol;
      g.appendChild(label);
      kids.push(g);
    });
    kids.push(s('circle', { cx: 140, cy: 140, r: 5, class: 'nose-dot' }));
    svg.replaceChildren.apply(svg, kids);

    var flagged = toks.filter(smelly).length, loud = toks[order[0]];
    var stats = [
      ['tokens sniffed', toks.length, ''],
      ['smell off', flagged, ''],
      ['look clean', toks.length - flagged, '']
    ];
    var ul = $('radarStats');
    var items = stats.map(function (st) {
      return el('li', null, [el('b', { 'data-count': st[1], text: String(st[1]) }), el('span', { class: 'muted', text: st[0] })]);
    });
    if (loud && typeof loud.volume_24h_usd === 'number') {
      items.push(el('li', { class: 'wide' }, [el('b', { text: loud.symbol }), el('span', { class: 'muted', text: 'loudest: ' + usd(loud.volume_24h_usd) + ' in 24h' })]));
    }
    ul.replaceChildren.apply(ul, items);

    var tk = $('ticker');
    function chip(t) {
      return el('span', { class: 'tick ' + (smelly(t) ? 'smelly' : 'clean') }, [
        el('b', { text: t.symbol }), ' ' + usd(t.volume_24h_usd) + ' ', chg(t.change_24h_pct)
      ]);
    }
    var track = el('div', { class: 'ticker-track' }, toks.map(chip));
    var copy = el('div', { class: 'ticker-track', 'aria-hidden': 'true' }, toks.map(chip));
    tk.replaceChildren(el('div', { class: 'ticker-inner' }, [track, copy]));
  }

  function headlineList(items) {
    return el('ul', { class: 'headlines' }, items.map(function (h) {
      var url = safeUrl(h.url);
      var meta = [h.source, h.published_at ? (dayKey(new Date(h.published_at)) === dayKey(new Date()) ? '' : fmt(new Date(h.published_at), { day: 'numeric', month: 'short' }) + ', ') + hm(new Date(h.published_at)) + ' ' + zoneName() : null].filter(Boolean).join(' · ');
      return el('li', null, [
        url ? el('a', { href: url, rel: 'noopener nofollow', target: '_blank', text: h.title }) : el('span', { text: h.title }),
        meta ? el('span', { class: 'muted small', text: ' ' + meta }) : null
      ]);
    }));
  }

  function entryNode(e, i) {
    var k = KINDS[e.kind] || KINDS.note, d = new Date(e.ts);
    var meta = el('div', { class: 'entry-meta' }, [
      el('span', { class: 'kind', html: '<svg viewBox="0 0 24 24" aria-hidden="true">' + k.icon + '</svg>' }),
      el('time', { class: 'time', datetime: e.ts, title: rel(d), text: hm(d) }),
      e.example ? el('span', { class: 'tag-example', text: 'example entry' }) : null
    ]);
    meta.firstChild.appendChild(document.createTextNode(k.label));

    var li = el('li', { class: 'entry reveal', style: '--k:' + k.color + ';--d:' + Math.min(i * 70, 420) + 'ms', id: e.id ? 'e-' + e.id : null });
    li.appendChild(meta);

    if (e.reply_to && (e.reply_to.handle || e.reply_to.text)) {
      var rt = el('div', { class: 'reply-to' });
      if (e.reply_to.handle) rt.appendChild(el('b', { text: '@' + String(e.reply_to.handle).replace(/^@/, '') + ': ' }));
      rt.appendChild(richText(e.reply_to.text || ''));
      li.appendChild(rt);
    }
    li.appendChild(el('p', { class: 'entry-text' }, [richText(e.text)]));
    if (Array.isArray(e.tokens) && e.tokens.length) li.appendChild(tokenTable(e.tokens));
    if (Array.isArray(e.headlines) && e.headlines.length) li.appendChild(headlineList(e.headlines));

    var foot = el('div', { class: 'entry-foot' });
    var hasBack = e.backstage || (e.tools && e.tools.length) || (e.attempts && e.attempts.length);
    if (hasBack) {
      var body = el('div', { class: 'backstage-body' });
      if (e.backstage) body.appendChild(el('p', null, [richText(e.backstage)]));
      if (e.attempts && e.attempts.length) {
        body.appendChild(el('span', { class: 'label', text: 'Tried first' }));
        e.attempts.forEach(function (a) {
          body.appendChild(el('div', { class: 'attempt' }, [el('q', { text: a.text || '' }), a.reason ? el('span', { class: 'why', text: "didn't go: " + a.reason }) : null]));
        });
      }
      if (e.tools && e.tools.length) {
        body.appendChild(el('span', { class: 'label', text: 'Tools I used' }));
        body.appendChild(el('ul', { class: 'tools' }, e.tools.map(toolItem)));
      }
      foot.appendChild(el('details', { class: 'backstage' }, [el('summary', { text: 'backstage' }), body]));
    }
    var url = safeUrl(e.url);
    if (url) foot.appendChild(el('a', { class: 'ext', href: url, rel: 'noopener', target: '_blank', text: 'View on X ↗' }));
    if (['post', 'reply', 'draft'].indexOf(e.kind) > -1) {
      var n = Array.from(e.text || '').length;
      foot.appendChild(el('span', { class: 'chars', title: 'approximate character count', text: n + '/280' }));
    }
    if (foot.childNodes.length) li.appendChild(foot);
    return li;
  }

  function renderFeed() {
    var f = FILTERS.find(function (x) { return x.id === filter; }) || FILTERS[0];
    var list = f.kinds ? entries.filter(function (e) { return f.kinds.indexOf(e.kind) > -1; }) : entries;
    var feed = $('feed'), groups = [], cur = null;
    list.forEach(function (e) {
      var d = new Date(e.ts), key = dayKey(d);
      if (!cur || cur.key !== key) { cur = { key: key, d: d, items: [] }; groups.push(cur); }
      cur.items.push(e);
    });
    var i = 0;
    feed.replaceChildren.apply(feed, groups.map(function (g) {
      return el('div', { class: 'day' }, [
        el('h3', { class: 'day-label', text: dayLabel(g.d) }),
        el('ol', { class: 'entries' }, g.items.map(function (e) { return entryNode(e, i++); }))
      ]);
    }));
    $('empty').hidden = list.length > 0;
  }

  // ---------- theme ----------
  function setupTheme() {
    var btn = $('themeToggle'), root = document.documentElement;
    function isDark() { return root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; }
    function sync() { btn.setAttribute('aria-pressed', String(isDark())); btn.setAttribute('aria-label', isDark() ? 'Switch to light mode' : 'Switch to dark mode'); }
    btn.addEventListener('click', function (ev) {
      var next = isDark() ? 'light' : 'dark';
      function apply() { root.dataset.theme = next; sync(); }
      try { localStorage.setItem('corgi-theme', next); } catch (e) {}
      if (document.startViewTransition && !reduced()) {
        var r = btn.getBoundingClientRect();
        root.style.setProperty('--vt-x', (r.left + r.width / 2) + 'px');
        root.style.setProperty('--vt-y', (r.top + r.height / 2) + 'px');
        document.startViewTransition(apply);
      } else apply();
    });
    sync();
  }

  setupTheme();
  load();
  setInterval(load, REFRESH_MS);
  setInterval(function () { if (state) { renderHero(); renderPlan(); } }, 60 * 1000);
})();
