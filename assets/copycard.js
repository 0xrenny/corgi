/* Link card to the paper copy-trade dashboard: a few live numbers from data/copy.json (respects CORGI_DATA_BASE). */
(function () {
  var box = document.getElementById('copyMini'); if (!box) return;
  var DATA = window.CORGI_DATA_BASE || 'data/';
  function li(k, v, cls) { var e = document.createElement('li'); var b = document.createElement('b'); b.textContent = v; if (cls) b.className = cls; var s = document.createElement('span'); s.textContent = k; e.appendChild(b); e.appendChild(s); box.appendChild(e); }
  fetch(DATA + 'copy.json?t=' + Math.floor(Date.now() / 6e4), { cache: 'no-store' }).then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(function (d) {
    var s = d.summary || {}, eq = s.equity_usd, p = s.pnl_pct;
    li('paper bankroll', eq == null ? '—' : '$' + eq.toFixed(2), p > 0 ? 'up' : p < 0 ? 'dn' : '');
    li('since start', p == null ? '—' : (p > 0 ? '+' : '') + p.toFixed(2) + '%', p > 0 ? 'up' : p < 0 ? 'dn' : '');
    li('paper trades', String(s.trades || 0));
    li('win rate', s.win_rate == null ? '—' : Math.round(s.win_rate * 100) + '%');
  }).catch(function () { var c = document.getElementById('copyCard'); if (c) c.hidden = true; });
})();
