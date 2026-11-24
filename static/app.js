(() => {
  'use strict';
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = id => document.getElementById(id);
  // SECURITY: lead and chat text comes from anonymous visitors. Use textContent only, never innerHTML.

  // ---- Sliding tab pill and view switching
  const pill = document.querySelector('.pill');
  const tabs = document.querySelectorAll('.tab');
  const movePill = t => { pill.style.left = t.offsetLeft + 'px'; pill.style.width = t.offsetWidth + 'px'; };
  const selectedTab = () => document.querySelector('.tab[aria-selected="true"]');
  tabs.forEach(t => t.addEventListener('click', () => {
    tabs.forEach(x => x.setAttribute('aria-selected', x === t));
    movePill(t);
    document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === t.dataset.view));
    if (t.dataset.view === 'owner') loadLeads(true);
  }));
  addEventListener('load', () => movePill(selectedTab()));
  addEventListener('resize', () => movePill(selectedTab()));

  // ---- Chat
  const newId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
  let sessionId;
  try {
    sessionId = sessionStorage.getItem('leadpilot_sid');
    if (!sessionId) { sessionId = newId(); sessionStorage.setItem('leadpilot_sid', sessionId); }
  } catch (e) {
    sessionId = sessionId || newId();
  }

  const msgs = $('msgs'), input = $('m'), send = $('send');
  const scrollDown = () => { msgs.scrollTop = msgs.scrollHeight; };
  function addMsg(text, cls) {
    const el = document.createElement('div');
    el.className = 'msg ' + cls;
    el.textContent = text;
    msgs.appendChild(el);
    scrollDown();
  }
  function addTyping() {
    const t = document.createElement('div');
    t.className = 'typing';
    for (let i = 0; i < 3; i++) t.appendChild(document.createElement('i'));
    msgs.appendChild(t);
    scrollDown();
    return t;
  }

  $('composer').addEventListener('submit', async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
    input.value = '';
    addMsg(text, 'me');
    send.disabled = true;
    const typing = addTyping();
    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      if (res.status === 503) {
        // server not configured: show the server's own hint (plain text via addMsg/textContent)
        const body = await res.json().catch(() => ({}));
        if (typeof body.detail === 'string' && body.detail) {
          typing.remove();
          addMsg(body.detail, 'bot err');
          return;
        }
      }
      if (!res.ok) throw new Error('http ' + res.status);
      const data = await res.json();
      typing.remove();
      addMsg(data.reply, 'bot');
      loadLeads(false);
    } catch (err) {
      typing.remove();
      addMsg("Sorry, I couldn't reach the assistant just now. Please try again in a moment.", 'bot err');
    } finally {
      send.disabled = false;
      input.focus();
    }
  });

  // ---- Owner dashboard
  let leads = [], tier = 'all', selectedId = null;

  // keep in sync with app/scoring.py
  function breakdown(l) {
    const rows = [];
    if (l.budget_usd != null) {
      const hi = l.budget_usd >= 5000, mid = l.budget_usd >= 1000;
      rows.push([`Budget $${l.budget_usd.toLocaleString('en-US')} (${hi ? '≥ $5k' : mid ? '≥ $1k' : '< $1k'})`, hi ? 40 : mid ? 25 : 5]);
    }
    if (l.timeline_days != null) {
      const fast = l.timeline_days <= 30, ok = l.timeline_days <= 90;
      rows.push([`Timeline ${l.timeline_days} days (${fast ? '≤ 30' : ok ? '≤ 90' : '> 90'})`, fast ? 30 : ok ? 15 : 5]);
    }
    if (l.is_decision_maker != null) {
      rows.push([l.is_decision_maker ? 'Decision maker' : 'Not the decision maker', l.is_decision_maker ? 20 : 5]);
    }
    if (l.need && l.need.trim()) rows.push(['Clear need stated', 10]);
    return rows;
  }

  function countUp(el, end) {
    if (still) { el.textContent = end; return; }
    const t0 = performance.now(), dur = 1100;
    const step = now => {
      const k = Math.min(1, (now - t0) / dur);
      el.textContent = Math.round(end * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  const fmtSlot = iso => {
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC';
  };
  const fmtDate = iso => {
    const d = new Date(iso);
    return isNaN(d) ? String(iso || '') : d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  };
  const cell = (cls, text) => {
    const td = document.createElement('td');
    if (cls) td.className = cls;
    td.textContent = text;
    return td;
  };

  function renderStats() {
    const avg = leads.length ? Math.round(leads.reduce((a, l) => a + (l.score || 0), 0) / leads.length) : 0;
    countUp($('s-total'), leads.length);
    countUp($('s-hot'), leads.filter(l => l.tier === 'hot').length);
    countUp($('s-booked'), leads.filter(l => l.booked_slot).length);
    countUp($('s-avg'), avg);
  }

  function renderRows() {
    const tbody = $('rows');
    tbody.replaceChildren();
    const shown = leads.filter(l => tier === 'all' || l.tier === tier);
    shown.forEach(l => {
      const tr = document.createElement('tr');
      if (l.id === selectedId) tr.className = 'sel';
      const who = document.createElement('td');
      who.className = 'who';
      const b = document.createElement('b');
      b.textContent = l.name || 'Anonymous';
      const s = document.createElement('span');
      s.textContent = l.email || 'no email yet';
      who.append(b, s);
      const badgeTd = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'badge ' + (l.tier || 'cold');
      badge.textContent = l.tier || 'cold';
      badgeTd.appendChild(badge);
      tr.append(who, cell('hide-sm', l.need || '—'), cell('num', l.score), badgeTd,
        cell('hide-sm ' + (l.booked_slot ? 'booked' : 'pending'), l.booked_slot ? fmtSlot(l.booked_slot) : 'Not booked'));
      tr.addEventListener('click', () => { selectedId = l.id; renderRows(); renderDetail(true); });
      tbody.appendChild(tr);
    });
    const empty = $('empty');
    empty.hidden = shown.length > 0;
    empty.replaceChildren();
    if (!shown.length) {
      if (leads.length) {
        empty.textContent = 'No leads in this tier.';
      } else {
        const b = document.createElement('b');
        b.textContent = 'No leads yet';
        empty.append(b, 'Chat with Ava in the Visitor view and your first lead will show up here.');
      }
    }
  }

  function renderDetail(animate) {
    const l = leads.find(x => x.id === selectedId);
    $('detail-card').hidden = !l;
    if (!l) return;
    $('d-title').textContent = `Why ${l.name || 'this lead'} scored ${l.score}`;
    $('d-score').textContent = l.score;
    const t = $('d-tier');
    t.className = 'badge ' + l.tier;
    t.textContent = l.tier;
    const ul = $('d-breakdown');
    ul.replaceChildren();
    const bars = [];
    breakdown(l).forEach(([label, pts]) => {
      const li = document.createElement('li');
      const a = document.createElement('span');
      a.textContent = label;
      const p = document.createElement('span');
      p.textContent = '+' + pts;
      const bar = document.createElement('i');
      bar.className = 'bar-fill';
      li.append(a, p, bar);
      ul.appendChild(li);
      bars.push([bar, pts]);
    });
    $('d-need').textContent = l.need || 'Not stated yet';
    const m = $('d-meeting');
    m.textContent = l.booked_slot ? fmtSlot(l.booked_slot) : 'Not booked';
    m.className = l.booked_slot ? 'booked' : '';
    $('d-created').textContent = fmtDate(l.created_at);
    const ring = $('ring');
    if (still || !animate) {
      ring.style.setProperty('--p', l.score);
      bars.forEach(([b, p]) => { b.style.width = p + '%'; });
      return;
    }
    ring.style.setProperty('--p', 0);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      ring.style.setProperty('--p', l.score);
      bars.forEach(([b, p], i) => setTimeout(() => { b.style.width = p + '%'; }, 300 + i * 150));
    }));
  }

  document.querySelectorAll('.filter').forEach(f => f.addEventListener('click', () => {
    document.querySelectorAll('.filter').forEach(x => x.setAttribute('aria-pressed', x === f));
    tier = f.dataset.tier;
    renderRows();
  }));

  // force=true replays the count-up animation (opening the tab); otherwise only render on change
  async function loadLeads(force) {
    try {
      const res = await fetch('/leads');
      if (!res.ok) return;
      const next = await res.json();
      const changed = JSON.stringify(next) !== JSON.stringify(leads);
      leads = next;
      if (!leads.some(l => l.id === selectedId)) selectedId = leads.length ? leads[0].id : null;
      if (changed || force) { renderStats(); renderRows(); renderDetail(true); }
    } catch (e) { /* keep showing the last data */ }
  }

  loadLeads(true);
})();
