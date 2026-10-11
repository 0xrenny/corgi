/* Corgi — motion & delight. Pure progressive enhancement: the page works without it.
   Everything here respects prefers-reduced-motion and pauses when off-screen / tab hidden. */
(function () {
  'use strict';
  var mq = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : { matches: false, addEventListener: function () {} };
  var reduced = function () { return mq.matches; };
  var $ = function (id) { return document.getElementById(id); };
  var root = document.documentElement;
  root.classList.add('fx');

  // ---------- scroll reveal ----------
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (list) {
    list.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); countIn(e.target); }
    });
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.01 }) : null;
  function watch() {
    document.querySelectorAll('.reveal:not(.in):not([data-watched])').forEach(function (n) {
      n.dataset.watched = '1';
      if (!io || reduced()) { n.classList.add('in'); countIn(n); } else io.observe(n);
    });
  }

  // ---------- count-up numbers (only ever counts to a value that came from the JSON) ----------
  function countIn(scope) {
    (scope.querySelectorAll ? scope.querySelectorAll('[data-count]:not([data-counted])') : []).forEach(countUp);
  }
  function countUp(n) {
    n.dataset.counted = '1';
    var to = Number(n.dataset.count), pre = n.dataset.prefix || '', suf = n.dataset.suffix || '';
    if (!isFinite(to) || reduced() || to === 0) { n.textContent = pre + to + suf; return; }
    var t0 = performance.now(), dur = Math.min(1200, 500 + to * 60);
    (function step(t) {
      var p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      n.textContent = pre + Math.round(to * e) + suf;
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  }
  function countVisible() {
    document.querySelectorAll('.hero [data-count]:not([data-counted]), .reveal.in [data-count]:not([data-counted])').forEach(countUp);
  }

  // ---------- mascot ----------
  var mascot = $('mascot'), bubble = $('bubble');
  var pupils = mascot && mascot.querySelector('.pupils');
  var head = mascot && mascot.querySelector('.head');
  var bubbleTimer;
  function say(text, ms) {
    if (!bubble) return;
    bubble.textContent = text;
    bubble.classList.add('show');
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(function () { bubble.classList.remove('show'); }, ms || 3200);
  }
  var LINES = [
    'Boop received. Tail engaged.',
    'Short legs, long nose. Mostly nose.',
    'I sniff numbers so you don\u2019t have to lick them.',
    'Volume is loud. Holders are the crowd. Count the crowd.',
    'No token, no wallet, no problem.',
    'If it smells like a bot, I say so.',
    'That\u2019s my nose. I need that.',
    'Snack-sized facts only. No fake ones.'
  ];
  var boops = 0;
  if (mascot) {
    mascot.addEventListener('click', function (ev) {
      boops++;
      mascot.classList.remove('booped'); void mascot.offsetWidth; mascot.classList.add('booped');
      say(boops === 1 ? 'Boop! Hi, I\u2019m Corgi.' : LINES[(boops - 2) % LINES.length]);
      if (!reduced()) hearts(ev);
    });
  }
  function hearts(ev) {
    var wrap = mascot.parentNode, r = wrap.getBoundingClientRect();
    var x = ev && ev.clientX ? ev.clientX - r.left : r.width / 2, y = ev && ev.clientY ? ev.clientY - r.top : r.height / 3;
    for (var i = 0; i < 5; i++) {
      var h = document.createElement('span');
      h.className = 'heart'; h.textContent = i % 2 ? '\u2665' : '\u2726';
      h.style.left = x + 'px'; h.style.top = y + 'px';
      h.style.setProperty('--dx', (Math.random() * 90 - 45).toFixed(0) + 'px');
      h.style.setProperty('--rot', (Math.random() * 60 - 30).toFixed(0) + 'deg');
      h.style.animationDelay = (i * 60) + 'ms';
      wrap.appendChild(h);
      setTimeout(function (n) { n.remove(); }.bind(null, h), 1400);
    }
  }
  // blink every few seconds (JS so it works the same in every browser)
  (function blinkLoop() {
    setTimeout(function () {
      if (mascot && !document.hidden && root.dataset.status !== 'napping') {
        mascot.classList.add('blink');
        setTimeout(function () { mascot.classList.remove('blink'); }, 130);
      }
      blinkLoop();
    }, 2800 + Math.random() * 3200);
  })();
  // eyes + head follow the cursor (pointer devices only)
  var px = 0, py = 0, raf = 0;
  function look() {
    raf = 0;
    if (!mascot || reduced() || root.dataset.status === 'napping') return;
    var r = mascot.getBoundingClientRect();
    var cx = r.left + r.width / 2, cy = r.top + r.height * 0.4;
    var dx = px - cx, dy = py - cy, d = Math.hypot(dx, dy) || 1;
    var k = Math.min(1, d / 400);
    pupils.style.transform = 'translate(' + (dx / d * 4 * k).toFixed(2) + 'px,' + (dy / d * 3 * k).toFixed(2) + 'px)';
    head.style.transform = 'rotate(' + Math.max(-6, Math.min(6, dx / 120)).toFixed(2) + 'deg)';
    mascot.classList.toggle('near', d < 220);
  }
  if (window.matchMedia && matchMedia('(pointer: fine)').matches) {
    window.addEventListener('pointermove', function (e) { px = e.clientX; py = e.clientY; if (!raf) raf = requestAnimationFrame(look); }, { passive: true });
  }
  // ears perk when you scroll
  var perkT, lastY = window.scrollY;
  window.addEventListener('scroll', function () {
    var y = window.scrollY;
    root.classList.toggle('scrolled', y > 8);
    if (mascot && Math.abs(y - lastY) > 30) {
      lastY = y;
      mascot.classList.add('perk');
      clearTimeout(perkT); perkT = setTimeout(function () { mascot.classList.remove('perk'); }, 650);
    }
  }, { passive: true });

  // ---------- card spotlight ----------
  document.addEventListener('pointermove', function (e) {
    if (reduced()) return;
    var c = e.target.closest && e.target.closest('.card, .entry, .steps li');
    if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty('--mx', (e.clientX - r.left) + 'px');
    c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  }, { passive: true });

  // ---------- paw-print particles in the hero ----------
  var cv = $('paws'), ctx = cv && cv.getContext && cv.getContext('2d');
  var paws = [], running = false, visible = true, last = 0, W = 0, H = 0, DPR = 1, frame = 0;
  function pawColor() {
    return getComputedStyle(root).getPropertyValue('--paw').trim() || 'rgba(232,137,58,.18)';
  }
  var color = pawColor();
  function size() {
    if (!cv) return;
    var r = cv.getBoundingClientRect();
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = r.width; H = r.height;
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  function spawn(initial) {
    var s = 7 + Math.random() * 9;
    return { x: Math.random() * W, y: initial ? Math.random() * H : H + 20, s: s, v: 6 + Math.random() * 10,
             a: Math.random() * Math.PI * 2, w: (Math.random() - .5) * .4, o: .35 + Math.random() * .65, ph: Math.random() * 6 };
  }
  function drawPaw(p) {
    ctx.save();
    ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.globalAlpha = p.o;
    ctx.fillStyle = color;
    var s = p.s;
    ctx.beginPath(); ctx.ellipse(0, s * .35, s * .55, s * .45, 0, 0, Math.PI * 2); ctx.fill();
    [[-.55, -.25], [-.2, -.6], [.2, -.6], [.55, -.25]].forEach(function (t) {
      ctx.beginPath(); ctx.ellipse(t[0] * s, t[1] * s, s * .2, s * .26, 0, 0, Math.PI * 2); ctx.fill();
    });
    ctx.restore();
  }
  function tick(t) {
    if (!running) return;
    var dt = Math.min(.05, (t - (last || t)) / 1000); last = t;
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < paws.length; i++) {
      var p = paws[i];
      p.y -= p.v * dt; p.ph += dt; p.x += Math.sin(p.ph) * 4 * dt; p.a += p.w * dt;
      if (p.y < -20) paws[i] = spawn(false);
      drawPaw(p);
    }
    frame = requestAnimationFrame(tick);
  }
  function start() {
    if (!ctx || running || reduced() || !visible || document.hidden) return;
    running = true; last = 0; frame = requestAnimationFrame(tick);
  }
  function stop() { running = false; cancelAnimationFrame(frame); }
  if (ctx) {
    size();
    var n = W < 640 ? 8 : 16;
    for (var i = 0; i < n; i++) paws.push(spawn(true));
    if (reduced()) { paws.forEach(drawPaw); }
    new IntersectionObserver(function (l) { visible = l[0].isIntersecting; visible ? start() : stop(); }).observe(cv);
    document.addEventListener('visibilitychange', function () { document.hidden ? stop() : start(); });
    window.addEventListener('resize', function () { size(); if (!running) paws.forEach(drawPaw); });
    start();
  }
  if (mq.addEventListener) mq.addEventListener('change', function () { reduced() ? stop() : start(); });
  new MutationObserver(function () { color = pawColor(); if (!running && ctx) { ctx.clearRect(0, 0, W, H); paws.forEach(drawPaw); } })
    .observe(root, { attributes: true, attributeFilter: ['data-theme'] });

  // ---------- hook into data renders ----------
  var greeted = false;
  document.addEventListener('corgi:rendered', function (ev) {
    watch();
    countVisible();
    if (!greeted) {
      greeted = true;
      var st = ev.detail.state || {}, plan = st.plan || {};
      var nxt = plan.next_check_at ? new Date(plan.next_check_at) : null;
      var when = nxt && nxt > Date.now() ? new Intl.DateTimeFormat('en-GB', { timeZone: st.timezone || 'Europe/Istanbul', hour: '2-digit', minute: '2-digit', hour12: false }).format(nxt) + (st.timezone === 'Europe/Istanbul' || !st.timezone ? ' TRT' : '') : null;
      var line = st.status === 'napping' ? 'Zzz\u2026' + (when ? ' back at ' + when + '.' : '')
        : st.status === 'walking' ? 'Out on a walk. Nose down.'
        : st.status === 'offline' ? 'Kennel\u2019s closed for now.'
        : 'Nose on.' + (when ? ' Next sniff at ' + when + '.' : '');
      setTimeout(function () { say(line, 4200); }, reduced() ? 0 : 900);
    }
  });
  // Feed re-renders (filters) create new nodes: watch them too.
  var feed = $('feed');
  if (feed) new MutationObserver(watch).observe(feed, { childList: true });
  root.classList.toggle('scrolled', window.scrollY > 8);
})();
