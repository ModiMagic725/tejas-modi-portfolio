/*
  Portfolio assistant widget - core (vanilla JS, no dependencies).

  One widget, one instance per page. This file owns: the chat, the speech bubble (greeting, scroll
  nudges, questions with buttons), the spoken greeting, and a small API (window.PCB) that music.js
  uses to add the music player and the music-permission conversation. Nothing here plays music.

  - Mounts after the page has loaded (and after the Homepage loader is gone).
  - No request to the chat server until the visitor sends something.
  - All visitor/assistant text is written with textContent, never innerHTML.
  - Session memory (this tab only, cleared when the tab closes): last chat messages ('pcb:v1') and
    small flags ('pcb:s': greeted, voiced, quiet, nudges, music choice). Nothing is sent to a server.
*/
(function () {
  'use strict';

  if (window.PCB) return;                       // never run two instances
  var host = document.getElementById('pcb-root');
  if (!host || !window.fetch) return;

  var PCB = window.PCB = {
    host: host, ui: {}, state: null, cfg: null,
    actions: {},          // name -> function(source): handlers for local buttons (chips / bubble buttons)
    filters: [],          // function(chipItem) -> false hides that chip
    welcomeExtra: [],     // extra {label, action} chips on the welcome message
    chatOpenCbs: [],      // called when the chat opens: function({bubbleKind})
    mountCbs: [], mounted: false, greetPending: false
  };
  PCB.onMount = function (fn) { if (PCB.mounted) fn(); else PCB.mountCbs.push(fn); };

  var CFG = PCB.cfg = {
    endpoint: host.getAttribute('data-pcb-endpoint'),
    csrf: host.getAttribute('data-pcb-csrf') || '',
    greeting: host.getAttribute('data-pcb-greeting') || '',
    music: host.getAttribute('data-pcb-music') || '',
    pages: {
      about: host.getAttribute('data-pcb-about'),
      websites: host.getAttribute('data-pcb-websites'),
      contact: host.getAttribute('data-pcb-contact'),
      start: host.getAttribute('data-pcb-start')
    }
  };
  var STORE_KEY = 'pcb:v1';
  var FLAGS_KEY = 'pcb:s';
  var REOPEN_KEY = 'pcb:reopen';
  var MAX_STORED = 30;
  var MAX_LEN = 500;
  var REQUEST_TIMEOUT_MS = 28000;       // covers a cold start plus the AI's own 10s limit
  var RETRY_DELAY_MS = 2500;
  var NUDGE_GAP_MS = 20000;             // minimum time between speech bubbles
  var NUDGE_MAX = 2;                    // scroll nudges per browser tab session

  // Labels are display text; the ids must exist in portfolio_app/chatbot/intents.py (a test checks this).
  var QUICK = [
    ['Show me your projects', 'projects'],
    ['What are your skills?', 'skills'],
    ['Work experience', 'experience'],
    ['Where is your resume?', 'resume'],
    ['How can I hire you?', 'hire'],
    ['Contact details', 'contact']
  ];
  var WELCOME = "Hi! I'm the portfolio assistant. I can walk you through Tejas's projects, skills and " +
                'experience, or point you to the right page. Pick a question or type your own.';
  var GREET_TEXT = 'Hello! How can I help you?';
  // Short, page-aware nudges shown while scrolling: [scroll depth, text]. At most NUDGE_MAX per tab.
  var NUDGES = {
    '/': [[0.35, 'Take your time looking around. Ask me for a quick tour any time.'],
          [0.75, 'Want to see the work up close? I can point you to the projects.']],
    '/about/': [[0.4, 'Curious about the skills or experience? Just ask me.'],
                [0.8, 'Want the resume? I can show you where it is.']],
    '/websites/': [[0.4, 'See something you like? Ask me about the projects.']],
    '/backend-projects/': [[0.4, 'Want the short version of a project? Just ask.']],
    '/contact/': [[0.5, 'Not sure which form to use? I can help you choose.']],
    '/start-a-project/': [[0.4, 'Need a hand with the form? Ask me anything.']]
  };

  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var small = function () { return window.matchMedia && matchMedia('(max-width: 640px)').matches; };

  var state = PCB.state = { msgs: [], busy: false, open: false };
  var ui = PCB.ui;

  // ------------------------------------------------------------------ helpers
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function getCookie(name) {
    var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  }
  function safeHref(u) {
    if (typeof u !== 'string') return null;
    if (u.charAt(0) === '/' && u.charAt(1) !== '/') return u;       // same-site path
    if (/^mailto:[^\s]+$/i.test(u)) return u;
    if (/^https:\/\/[^\s]+$/i.test(u)) return u;
    return null;
  }
  PCB.narrow = function () { return window.innerWidth < 800; };   // on narrow screens chat and player take turns
  PCB.el = el;
  PCB.reduced = reduced;
  PCB.small = small;

  var ICON = PCB.ICON = {
    bot: '<svg class="pcb-face" viewBox="0 0 64 64" aria-hidden="true" focusable="false"><ellipse class="f-shadow" cx="32" cy="60" rx="13" ry="2.2"/><g class="f-tilt"><g class="f-head"><path class="f-stem" d="M32 15V9.5"/><g class="f-orb"><circle cx="32" cy="7" r="3.4"/><circle class="f-glint" cx="31" cy="6" r="1.1"/></g><rect class="f-ear" x="4.5" y="29" width="6" height="14" rx="3"/><rect class="f-ear" x="53.5" y="29" width="6" height="14" rx="3"/><rect class="f-shell" x="9" y="14" width="46" height="42" rx="20"/><path class="f-shade" d="M12 44c2 8 9 12 20 12s18-4 20-12c-4 3-11 5-20 5s-16-2-20-5Z"/><path class="f-shine" d="M15 22c3-4.5 8-6.5 14-6.5"/><rect class="f-visor" x="14" y="22" width="36" height="25" rx="12.5"/><path class="f-glass" d="M19 26.5c2.2-2 5-3 8-3"/><g class="f-eyes"><g class="f-eye"><ellipse cx="25" cy="34" rx="4.3" ry="5.2"/><circle class="f-glint" cx="26.5" cy="31.8" r="1.5"/><circle class="f-glint f-dim" cx="23.6" cy="36.4" r=".7"/></g><g class="f-eye"><ellipse cx="39" cy="34" rx="4.3" ry="5.2"/><circle class="f-glint" cx="40.5" cy="31.8" r="1.5"/><circle class="f-glint f-dim" cx="37.6" cy="36.4" r=".7"/></g></g><ellipse class="f-cheek" cx="19.2" cy="41.6" rx="2.8" ry="1.6"/><ellipse class="f-cheek" cx="44.8" cy="41.6" rx="2.8" ry="1.6"/><path class="f-mouth" d="M28.6 42.2q3.4 3 6.8 0"/></g></g></svg>',
    speaker: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15.5 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/></svg>',
    x: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    down: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m6 9 6 6 6-6"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg>',
    out: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7 17 17 7M8 7h9v9"/></svg>',
    reset: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 12a8 8 0 1 0 2.6-5.9L4 8.5"/><path d="M4 4v4.5h4.5"/></svg>',
    disc: '<svg class="pcb-discsvg" viewBox="0 0 48 48" aria-hidden="true" focusable="false"><circle class="d-base" cx="24" cy="24" r="23.4"/><circle class="d-g1" cx="24" cy="24" r="21.2"/><circle class="d-g2" cx="24" cy="24" r="18.8"/><circle class="d-g1" cx="24" cy="24" r="16.4"/><circle class="d-g2" cx="24" cy="24" r="14"/><path class="d-shine" d="M24 24 40.4 9.6A22 22 0 0 1 46 22Z"/><path class="d-shine d-dim" d="M24 24 7.6 38.4A22 22 0 0 1 2 26Z"/><circle class="d-label" cx="24" cy="24" r="9.4"/><path class="d-glint" d="M18.2 22.4a6.2 6.2 0 0 1 5-4"/><circle class="d-hole" cx="24" cy="24" r="2"/></svg>',
    note: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/></svg>',
    play: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M8 5.2v13.6a.6.6 0 0 0 .9.5l11-6.8a.6.6 0 0 0 0-1L8.9 4.7a.6.6 0 0 0-.9.5Z" style="fill:currentColor;stroke:none"/></svg>',
    pause: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="6" y="5" width="4" height="14" rx="1.2" style="fill:currentColor;stroke:none"/><rect x="14" y="5" width="4" height="14" rx="1.2" style="fill:currentColor;stroke:none"/></svg>',
    prev: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 5v14"/><path d="M19 5.6v12.8a.5.5 0 0 1-.8.4l-8.6-6.4a.5.5 0 0 1 0-.8l8.6-6.4a.5.5 0 0 1 .8.4Z" style="fill:currentColor;stroke:none"/></svg>',
    next: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M18 5v14"/><path d="M5 5.6v12.8a.5.5 0 0 0 .8.4l8.6-6.4a.5.5 0 0 0 0-.8L5.8 5.2a.5.5 0 0 0-.8.4Z" style="fill:currentColor;stroke:none"/></svg>',
    vol: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15.5 9a4 4 0 0 1 0 6"/></svg>',
    mute: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/></svg>'
  };

  // ------------------------------------------------------------------ session flags (this tab only)
  var flags = {};
  try { var f0 = JSON.parse(sessionStorage.getItem(FLAGS_KEY) || 'null'); if (f0 && typeof f0 === 'object') flags = f0; } catch (e) { flags = {}; }
  PCB.session = {
    get: function (k) { return flags[k]; },
    set: function (k, v) { flags[k] = v; try { sessionStorage.setItem(FLAGS_KEY, JSON.stringify(flags)); } catch (e) { /* storage off: the chat just forgets */ } }
  };

  // ------------------------------------------------------------------ theme: borrow the page's accent
  function parseColor(v) {
    v = (v || '').trim();
    var m = v.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (m) {
      var h = m[1].length === 3 ? m[1].replace(/./g, '$&$&') : m[1];
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    m = v.match(/^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i);
    return m ? [+m[1], +m[2], +m[3]] : null;
  }
  function lum(c) {
    var a = c.map(function (x) { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
  }
  function contrast(a, b) {
    var l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  }
  function applyTheme() {
    var ink = [12, 16, 22];
    var ac = parseColor(getComputedStyle(document.documentElement).getPropertyValue('--ac')) || [45, 212, 191];
    var dark = [6, 16, 20], white = [255, 255, 255];
    var on = contrast(ac, dark) >= contrast(ac, white) ? dark : white;
    var text = ac.slice(), i = 0;
    while (contrast(text, ink) < 4.5 && i++ < 12) {
      text = text.map(function (x) { return Math.round(x + (255 - x) * 0.14); });
    }
    var s = host.style;
    s.setProperty('--pcb-ac', 'rgb(' + ac.join(',') + ')');
    s.setProperty('--pcb-ac-rgb', ac.join(', '));
    s.setProperty('--pcb-ac-text', 'rgb(' + text.join(',') + ')');
    s.setProperty('--pcb-on-ac', 'rgb(' + on.join(',') + ')');
  }

  // ------------------------------------------------------------------ chat history (this tab only)
  function save() {
    try {
      var keep = state.msgs.filter(function (m) { return !m.transient; }).slice(-MAX_STORED)
        .map(function (m) { return { role: m.role, text: m.text, links: m.links, sugg: m.sugg, source: m.source, welcome: m.welcome }; });
      sessionStorage.setItem(STORE_KEY, JSON.stringify({ msgs: keep, open: state.open }));
    } catch (e) { /* private mode / storage disabled */ }
  }
  function load() {
    try {
      var d = JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null');
      if (d && Array.isArray(d.msgs)) {
        state.msgs = d.msgs.filter(function (m) {
          return m && (m.role === 'user' || m.role === 'bot') && typeof m.text === 'string';
        }).slice(-MAX_STORED);
      }
    } catch (e) { state.msgs = []; }
  }

  // ------------------------------------------------------------------ rendering
  function scrollEnd() {
    var log = ui.log;
    if (!log) return;
    if (log.scrollTo && !reduced) log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' });
    else log.scrollTop = log.scrollHeight;
  }
  function link(l) {
    var href = safeHref(l && l.url);
    if (!href) return null;
    var a = el('a', 'pcb-link');
    a.href = href;
    a.appendChild(el('span', null, String(l.label || 'Open').slice(0, 60)));
    a.insertAdjacentHTML('beforeend', ICON.out);
    if (href.charAt(0) !== '/' && !/^mailto:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    return a;
  }
  function chipOk(it) {
    return PCB.filters.every(function (f) { return f(it) !== false; });
  }
  function chipRow(items) {
    var shown = items.filter(chipOk);
    if (!shown.length) return null;
    var row = el('div', 'pcb-chips');
    shown.forEach(function (it) {
      var b = el('button', 'pcb-chip', it.label);
      b.type = 'button';
      b.disabled = state.busy;
      if (it.action) b.setAttribute('data-action', it.action);
      else b.setAttribute('data-intent', it.intent);
      row.appendChild(b);
    });
    return row;
  }
  function bubbleNode(m, isLast, animate) {
    var wrap = el('div', 'pcb-msg ' + (m.role === 'user' ? 'pcb-user' : 'pcb-bot') + (m.error ? ' pcb-error' : '') + (animate ? ' pcb-new' : ''));
    wrap.appendChild(el('div', 'pcb-bubble', m.text));
    if (m.links && m.links.length) {
      var row = el('div', 'pcb-links');
      m.links.forEach(function (l) { var a = link(l); if (a) row.appendChild(a); });
      if (row.childNodes.length) wrap.appendChild(row);
    }
    if (m.retry) {
      var r = el('button', 'pcb-retry', 'Try again');
      r.type = 'button';
      r.setAttribute('data-retry', '1');
      wrap.appendChild(r);
    }
    if (m.source === 'ai') wrap.appendChild(el('div', 'pcb-meta', 'AI-generated. Check the linked pages for details.'));
    if (m.role === 'bot' && isLast && m.sugg && m.sugg.length) {
      var chips = chipRow(m.sugg);
      if (chips) wrap.appendChild(chips);
    }
    return wrap;
  }
  function renderAll() {
    ui.log.textContent = '';
    state.msgs.forEach(function (m, i) {
      ui.log.appendChild(bubbleNode(m, i === state.msgs.length - 1, false));
    });
  }
  function push(m) {
    var chips = ui.log.querySelectorAll('.pcb-chips');
    Array.prototype.forEach.call(chips, function (c) { c.parentNode.removeChild(c); });
    state.msgs.push(m);
    ui.log.appendChild(bubbleNode(m, true, !reduced && state.open));
    scrollEnd();
    save();
  }
  PCB.push = push;
  function setStatus(kind, text) {
    host.setAttribute('data-status', kind);
    ui.statusText.textContent = text;
  }
  function setBusy(b) {
    state.busy = b;
    ui.send.disabled = b || !ui.input.value.trim();
    Array.prototype.forEach.call(ui.log.querySelectorAll('.pcb-chip[data-intent], .pcb-retry'), function (c) { c.disabled = b; });
    setStatus(b ? 'busy' : 'ready', b ? 'Thinking\u2026' : "Ask about Tejas's work");
  }

  var typingNode = null, waitTimer = null;
  function showTyping() {
    typingNode = el('div', 'pcb-msg pcb-bot pcb-typing');
    typingNode.setAttribute('role', 'status');
    typingNode.setAttribute('aria-label', 'The assistant is typing');
    var b = el('div', 'pcb-bubble');
    b.appendChild(el('i')); b.appendChild(el('i')); b.appendChild(el('i'));
    typingNode.appendChild(b);
    ui.log.appendChild(typingNode);
    scrollEnd();
    waitTimer = setTimeout(function () {
      if (typingNode) typingNode.firstChild.appendChild(el('span', 'pcb-wait', 'Still working\u2026 the site may be waking up.'));
    }, 4000);
  }
  function hideTyping() {
    clearTimeout(waitTimer);
    if (typingNode && typingNode.parentNode) typingNode.parentNode.removeChild(typingNode);
    typingNode = null;
  }

  // ------------------------------------------------------------------ network
  async function request(payload) {
    var tries = 0;
    for (;;) {
      tries++;
      var ctrl = new AbortController();
      var timer = setTimeout(function () { ctrl.abort(); }, REQUEST_TIMEOUT_MS);
      try {
        var res = await fetch(CFG.endpoint, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') || CFG.csrf,
            'X-Requested-With': 'XMLHttpRequest'
          },
          body: JSON.stringify(payload),
          signal: ctrl.signal
        });
        clearTimeout(timer);
        var data = null;
        try { data = await res.json(); } catch (e) { data = null; }
        if (res.ok && data && data.ok) return data;
        var err = new Error(data && data.error ? data.error.message : '');
        err.status = res.status;
        err.retryable = res.status >= 500 || res.status === 429;
        // A sleeping Render service often answers 502/503/504 once: one automatic retry, then stop.
        if ((res.status === 502 || res.status === 503 || res.status === 504) && tries === 1) {
          await sleep(RETRY_DELAY_MS);
          continue;
        }
        throw err;
      } catch (e) {
        clearTimeout(timer);
        if (e && e.status !== undefined) throw e;
        if (tries === 1 && e && e.name !== 'AbortError') { await sleep(RETRY_DELAY_MS); continue; }
        var ne = new Error('network');
        ne.status = 0;
        ne.retryable = true;
        throw ne;
      }
    }
  }

  function history() {
    return state.msgs.filter(function (m) { return !m.error && !m.transient && !m.local; }).slice(-6).map(function (m) {
      return { role: m.role === 'user' ? 'user' : 'assistant', text: m.text.slice(0, 400) };
    });
  }

  function failure(err, payload) {
    var s = err && err.status;
    var text, retry = !!(err && err.retryable);
    if (s === 429) text = err.message || "You're sending messages quickly. Please wait a moment, then try again.";
    else if (s === 403) { text = 'Your session has expired. Please refresh the page and try again.'; retry = false; }
    else if (s === 400 || s === 413 || s === 415) { text = err.message || "I couldn't read that. Please try rephrasing."; retry = false; }
    else text = "I couldn't reach the server. It may be waking up, so please try again in a moment. Meanwhile, these pages might help:";
    var links = [];
    if (s !== 400 && s !== 429 && s !== 403) {
      links = [
        { label: 'About', url: CFG.pages.about }, { label: 'Websites', url: CFG.pages.websites },
        { label: 'Contact', url: CFG.pages.contact }
      ];
    }
    push({ role: 'bot', text: text, links: links, sugg: [], error: true, retry: retry, transient: true, _payload: payload });
  }

  async function run(payload) {
    setBusy(true);
    showTyping();
    try {
      var d = await request(payload);
      hideTyping();
      push({ role: 'bot', text: String(d.reply || ''), links: d.links || [], sugg: d.suggestions || [], source: d.source });
      setBusy(false);
    } catch (err) {
      hideTyping();
      failure(err, payload);
      setBusy(false);
      setStatus('error', 'Connection problem');
    }
  }

  function ask(label, payload) {
    if (state.busy) return;
    push({ role: 'user', text: label });
    run(payload);
  }
  function sendTyped() {
    var v = ui.input.value.replace(/\s+/g, ' ').trim();
    if (!v || state.busy) return;
    ui.input.value = '';
    ui.send.disabled = true;
    ask(v.slice(0, MAX_LEN), { message: v.slice(0, MAX_LEN), history: history() });
  }
  function retryLast(btn) {
    if (state.busy) return;
    var node = btn.closest('.pcb-msg');
    var idx = -1;
    for (var i = state.msgs.length - 1; i >= 0; i--) { if (state.msgs[i].retry) { idx = i; break; } }
    if (idx < 0) return;
    var payload = state.msgs[idx]._payload;
    state.msgs.splice(idx, 1);
    if (node && node.parentNode) node.parentNode.removeChild(node);
    save();
    run(payload);
  }

  // ------------------------------------------------------------------ spoken greeting
  // Plays by itself once per tab. Browsers often refuse sound before the visitor has touched the
  // page, so: try straight away; if refused, play on the first click, tap or key press anywhere.
  var audio = null;
  function setVoiceUi(playing) {
    (ui.voiceBtns || []).forEach(function (b) {
      b.setAttribute('aria-label', playing ? 'Stop spoken greeting' : 'Play spoken greeting');
      b.setAttribute('aria-pressed', playing ? 'true' : 'false');
      b.title = playing ? 'Stop' : 'Hear the greeting';
    });
  }
  function stopTalking() { host.classList.remove('pcb-talking'); setVoiceUi(false); }
  function stopVoice() {
    if (audio) { try { audio.pause(); } catch (e) { /* ignore */ } }
    stopTalking();
  }
  PCB.stopVoice = stopVoice;
  function playVoice() {
    if (!CFG.greeting) return Promise.resolve(false);
    try {
      if (!audio) {
        audio = new Audio();
        audio.preload = 'none';
        audio.src = CFG.greeting;
        audio.addEventListener('ended', stopTalking);
        audio.addEventListener('pause', stopTalking);
        audio.addEventListener('error', stopTalking);
      }
      audio.currentTime = 0;
      host.classList.add('pcb-talking');
      setVoiceUi(true);
      var p = audio.play();
      if (p && p.then) return p.then(function () { return true; }, function () { stopTalking(); return false; });
      return Promise.resolve(true);
    } catch (e) { stopTalking(); return Promise.resolve(false); }
  }
  function playAndRemember() {
    return playVoice().then(function (ok) { if (ok) PCB.session.set('voiced', 1); return ok; });
  }
  var GESTURES = ['pointerdown', 'touchend', 'keydown'];
  function autoVoice() {
    if (!CFG.greeting || PCB.session.get('voiced')) return;
    // Music the visitor already chose on an earlier page takes priority over the greeting voice.
    var m = PCB.session.get('music');
    if (m && m.perm === 'yes' && m.playing) return;
    playAndRemember().then(function (ok) {
      if (ok) return;
      var onGesture = function (e) {
        GESTURES.forEach(function (g) { document.removeEventListener(g, onGesture, true); });
        if (PCB.session.get('voiced') || host.contains(e.target) || PCB.musicActive) return;
        playAndRemember();
      };
      GESTURES.forEach(function (g) { document.addEventListener(g, onGesture, true); });
    });
  }
  function toggleVoice() {
    if (host.classList.contains('pcb-talking')) stopVoice(); else playAndRemember();
  }

  // ------------------------------------------------------------------ speech bubble (one slot)
  var bubble = { timer: null, visible: false, kind: null, lastAt: 0 };
  var queue = [];
  PCB.bubbleState = function () { return { visible: bubble.visible, kind: bubble.kind }; };
  function canShow() { return !state.open && !bubble.visible && !PCB.greetPending && !PCB.panelBusy; }
  function flush() {
    if (!canShow()) return;
    var fn = queue.shift();
    if (fn) fn();
  }
  // Run fn when the bubble slot is free (after the greeting, with the chat closed).
  PCB.whenBubbleFree = function (fn) { queue.push(fn); flush(); };
  PCB.flushBubbles = flush;

  function hideBubble() {
    clearTimeout(bubble.timer);
    var was = bubble.visible;
    if (ui.bubble) ui.bubble.hidden = true;
    bubble.visible = false;
    bubble.kind = null;
    if (was) bubble.lastAt = Date.now();
    setTimeout(flush, 400);
  }
  PCB.hideBubble = hideBubble;
  // opts: {text, kind, ttl, voice, actions: [{label, act}]}
  function showBubble(o) {
    if (!ui.bubble) return;
    clearTimeout(bubble.timer);
    ui.bubbleText.textContent = o.text;
    ui.bubbleVoice.hidden = !(o.voice && CFG.greeting);
    ui.bubbleActions.textContent = '';
    (o.actions || []).forEach(function (a, i) {
      var b = el('button', 'pcb-greet-btn' + (i === 0 ? ' pcb-primary' : ''), a.label);
      b.type = 'button';
      b.setAttribute('data-bact', a.act);
      ui.bubbleActions.appendChild(b);
    });
    ui.bubbleActions.hidden = !(o.actions && o.actions.length);
    ui.bubble.hidden = false;
    bubble.visible = true;
    bubble.kind = o.kind || 'info';
    bubble.timer = setTimeout(hideBubble, o.ttl || 8000);
  }
  PCB.showBubble = showBubble;

  function scheduleGreeting() {
    if (PCB.session.get('greeted')) return;
    PCB.greetPending = true;
    setTimeout(function () {
      PCB.greetPending = false;
      PCB.session.set('greeted', 1);
      if (!state.open) showBubble({ text: GREET_TEXT, kind: 'greet', voice: true, ttl: 7000 });
      else flush();
    }, reduced ? 600 : 1400);
  }

  // Scroll nudges: conversational, page-aware, rare. Never while the chat is open, a bubble is
  // showing, or after the visitor dismissed a bubble.
  var ticking = false;
  function pathKey() {
    var p = location.pathname || '/';
    return p.charAt(p.length - 1) === '/' ? p : p + '/';
  }
  function checkScroll() {
    ticking = false;
    if (state.open || bubble.visible || PCB.greetPending || PCB.panelBusy || queue.length) return;
    if (PCB.session.get('quiet')) return;
    var done = PCB.session.get('nudged') || [];
    if (done.length >= NUDGE_MAX) return;
    if (Date.now() - bubble.lastAt < NUDGE_GAP_MS && bubble.lastAt) return;
    var list = NUDGES[pathKey()];
    if (!list) return;
    var de = document.documentElement;
    var range = de.scrollHeight - window.innerHeight;
    if (range < window.innerHeight * 0.6) return;               // page too short to bother
    var progress = (window.pageYOffset || de.scrollTop || 0) / range;
    for (var i = 0; i < list.length; i++) {
      var key = pathKey() + ':' + list[i][0];
      if (progress >= list[i][0] && done.indexOf(key) < 0) {
        done = done.concat([key]);
        PCB.session.set('nudged', done);
        showBubble({ text: list[i][1], kind: 'nudge', ttl: 7000, actions: [{ label: 'Chat with me', act: 'open-chat' }] });
        return;
      }
    }
  }
  function onScroll() {
    if (ticking) return;
    ticking = true;
    (window.requestAnimationFrame || setTimeout)(checkScroll);
  }

  // ------------------------------------------------------------------ open / close
  function openPanel(opts) {
    opts = opts || {};
    if (state.open) return;
    var bubbleKind = bubble.visible ? bubble.kind : null;
    if (PCB.narrow() && PCB.closePlayer) PCB.closePlayer({ noFocus: true });
    state.open = true;
    hideBubble();
    host.setAttribute('data-state', 'open');
    ui.launcher.setAttribute('aria-expanded', 'true');
    ui.launcher.setAttribute('aria-label', 'Close portfolio assistant');
    ui.panel.hidden = false;
    void ui.panel.offsetWidth;
    ui.panel.classList.add('pcb-open');
    PCB.chatOpenCbs.forEach(function (fn) { try { fn({ bubbleKind: bubbleKind }); } catch (e) { /* ignore */ } });
    scrollEnd();
    if (!opts.silent) {
      if (window.matchMedia && matchMedia('(pointer: fine)').matches) ui.input.focus();
      else ui.panel.focus();
    }
    save();
  }
  function closePanel(opts) {
    if (!state.open) return;
    state.open = false;
    stopVoice();
    host.setAttribute('data-state', 'closed');
    ui.launcher.setAttribute('aria-expanded', 'false');
    ui.launcher.setAttribute('aria-label', 'Open portfolio assistant');
    ui.panel.classList.remove('pcb-open');
    var done = function () { if (!state.open) ui.panel.hidden = true; };
    if (reduced) done(); else setTimeout(done, 230);
    if (!opts || (!opts.silent && !opts.noFocus)) ui.launcher.focus();
    save();
    setTimeout(flush, 600);
  }
  PCB.openChat = openPanel;
  PCB.closeChat = closePanel;
  function userOpen() { openPanel(); if (!PCB.session.get('voiced') && !PCB.musicActive) playAndRemember(); }

  function startOver() {
    if (state.busy) return;
    state.msgs = [];
    try { sessionStorage.removeItem(STORE_KEY); } catch (e) { /* ignore */ }
    seedWelcome();
    renderAll();
    setStatus('ready', "Ask about Tejas's work");
    ui.input.focus();
  }
  function welcomeChips() {
    return QUICK.map(function (q) { return { label: q[0], intent: q[1] }; }).concat(PCB.welcomeExtra);
  }
  function seedWelcome() {
    state.msgs = [{ role: 'bot', text: WELCOME, links: [], source: 'static', welcome: true, local: true, sugg: welcomeChips() }];
  }
  // music.js adds its chip after mount; refresh the welcome message if it is still the only one.
  PCB.refreshWelcome = function () {
    if (state.msgs.length === 1 && state.msgs[0].welcome) {
      state.msgs[0].sugg = welcomeChips();
      renderAll();
    }
  };

  // ------------------------------------------------------------------ build
  function build() {
    host.textContent = '';
    host.setAttribute('data-state', 'closed');
    host.setAttribute('data-status', 'ready');

    // energy glow behind the launcher (pure CSS animation, decorative)
    var aura = el('div', 'pcb-aura');
    aura.setAttribute('aria-hidden', 'true');
    aura.appendChild(el('span', 'pcb-ripple'));
    ui.aura = aura;

    var panel = el('div', 'pcb-panel');
    panel.id = 'pcb-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'false');
    panel.setAttribute('aria-labelledby', 'pcb-title');
    panel.tabIndex = -1;
    panel.hidden = true;

    var head = el('div', 'pcb-head');
    var mark = el('span', 'pcb-mark');
    mark.innerHTML = ICON.bot;
    mark.setAttribute('aria-hidden', 'true');
    head.appendChild(mark);
    var id = el('div', 'pcb-id');
    var name = el('span', 'pcb-name', 'Portfolio assistant');
    name.id = 'pcb-title';
    var st = el('div', 'pcb-status');
    st.appendChild(el('span', 'pcb-dot'));
    ui.statusText = el('span', null, "Ask about Tejas's work");
    st.appendChild(ui.statusText);
    id.appendChild(name); id.appendChild(st);
    head.appendChild(id);

    var vh = el('button', 'pcb-icon-btn');
    vh.type = 'button';
    vh.innerHTML = ICON.speaker;
    vh.setAttribute('data-act', 'voice');
    if (!CFG.greeting) vh.hidden = true;
    var reset = el('button', 'pcb-icon-btn');
    reset.type = 'button';
    reset.setAttribute('aria-label', 'Start a new conversation');
    reset.title = 'Start over';
    reset.innerHTML = ICON.reset;
    reset.setAttribute('data-act', 'reset');
    var min = el('button', 'pcb-icon-btn');
    min.type = 'button';
    min.setAttribute('aria-label', 'Minimize assistant');
    min.title = 'Minimize';
    min.innerHTML = ICON.down;
    min.setAttribute('data-act', 'close');
    head.appendChild(vh); head.appendChild(reset); head.appendChild(min);

    var log = el('div', 'pcb-log');
    log.setAttribute('role', 'log');
    log.setAttribute('aria-live', 'polite');
    log.setAttribute('aria-relevant', 'additions');
    log.setAttribute('aria-label', 'Conversation');
    log.tabIndex = 0;

    var form = el('form', 'pcb-form');
    form.setAttribute('novalidate', '');
    form.autocomplete = 'off';
    var lab = el('label', 'pcb-sr', 'Ask a question about Tejas\u2019s portfolio');
    lab.setAttribute('for', 'pcb-input');
    var input = el('input', 'pcb-input');
    input.id = 'pcb-input';
    input.type = 'text';
    input.maxLength = MAX_LEN;
    input.placeholder = 'Ask a question\u2026';
    input.autocomplete = 'off';
    input.setAttribute('enterkeyhint', 'send');
    var send = el('button', 'pcb-send');
    send.type = 'submit';
    send.disabled = true;
    send.setAttribute('aria-label', 'Send message');
    send.innerHTML = ICON.send;
    form.appendChild(lab); form.appendChild(input); form.appendChild(send);

    var foot = el('div', 'pcb-foot', 'Answers come from the public pages of this portfolio.');
    panel.appendChild(head); panel.appendChild(log); panel.appendChild(form); panel.appendChild(foot);

    var launcher = el('button', 'pcb-launcher');
    launcher.type = 'button';
    launcher.setAttribute('aria-label', 'Open portfolio assistant');
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-controls', 'pcb-panel');
    launcher.innerHTML = ICON.bot + ICON.down;
    launcher.firstChild.setAttribute('class', 'pcb-face pcb-i-chat');
    launcher.lastChild.setAttribute('class', 'pcb-i-close');

    // speech bubble: text (opens the chat), optional voice button, dismiss, optional action buttons
    var b = el('div', 'pcb-greet');
    b.hidden = true;
    b.setAttribute('role', 'status');
    var row = el('div', 'pcb-greet-row');
    var bText = el('button', 'pcb-greet-open');
    bText.type = 'button';
    bText.setAttribute('data-act', 'bubble-open');
    var bVoice = el('button', 'pcb-icon-btn pcb-greet-play');
    bVoice.type = 'button';
    bVoice.innerHTML = ICON.speaker;
    bVoice.setAttribute('data-act', 'voice');
    var bX = el('button', 'pcb-icon-btn');
    bX.type = 'button';
    bX.setAttribute('aria-label', 'Dismiss message');
    bX.title = 'Dismiss';
    bX.innerHTML = ICON.x;
    bX.setAttribute('data-act', 'bubble-x');
    row.appendChild(bText); row.appendChild(bVoice); row.appendChild(bX);
    var bActs = el('div', 'pcb-greet-actions');
    bActs.hidden = true;
    b.appendChild(row); b.appendChild(bActs);

    host.appendChild(aura); host.appendChild(b); host.appendChild(panel); host.appendChild(launcher);
    ui.bubble = b; ui.bubbleText = bText; ui.bubbleVoice = bVoice; ui.bubbleActions = bActs;
    ui.voiceBtns = [vh, bVoice];
    setVoiceUi(false);
    ui.panel = panel; ui.log = log; ui.input = input; ui.send = send; ui.launcher = launcher; ui.form = form;
  }

  PCB.actions['open-chat'] = function () { userOpen(); };

  function wire() {
    ui.launcher.addEventListener('click', function () { state.open ? closePanel() : userOpen(); });
    ui.form.addEventListener('submit', function (e) { e.preventDefault(); sendTyped(); });
    ui.input.addEventListener('input', function () { ui.send.disabled = state.busy || !ui.input.value.trim(); });

    host.addEventListener('click', function (e) {
      var t = e.target;
      var act = t.closest && t.closest('[data-act]');
      if (act) {
        var a2 = act.getAttribute('data-act');
        if (a2 === 'close') closePanel();
        else if (a2 === 'reset') startOver();
        else if (a2 === 'bubble-open') userOpen();
        else if (a2 === 'voice') { clearTimeout(bubble.timer); toggleVoice(); }
        else if (a2 === 'bubble-x') { hideBubble(); PCB.session.set('quiet', 1); ui.launcher.focus(); }
        return;
      }
      var bact = t.closest && t.closest('[data-bact]');
      if (bact) {
        var name = bact.getAttribute('data-bact');
        hideBubble();
        var fn = PCB.actions[name];
        if (fn) fn('bubble');
        return;
      }
      var chip = t.closest && t.closest('.pcb-chip');
      if (chip) {
        var local = chip.getAttribute('data-action');
        if (local) {
          var h = PCB.actions[local];
          if (h) { push({ role: 'user', text: chip.textContent, local: true }); h('chat'); }
        } else {
          ask(chip.textContent, { intent: chip.getAttribute('data-intent') });
        }
        return;
      }
      var retry = t.closest && t.closest('[data-retry]');
      if (retry) { retryLast(retry); return; }
      var a = t.closest && t.closest('a.pcb-link');
      if (a && a.getAttribute('href').charAt(0) === '/') {
        try { sessionStorage.setItem(REOPEN_KEY, '1'); } catch (x) { /* ignore */ }
      }
    });

    host.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.open) { e.stopPropagation(); closePanel(); }
    });

    // On phones, step aside while the visitor is typing in one of the page's own fields.
    document.addEventListener('focusin', function (e) {
      if (!small() || host.contains(e.target)) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) host.classList.add('pcb-away');
    });
    document.addEventListener('focusout', function (e) {
      if (!host.contains(e.target)) host.classList.remove('pcb-away');
    });
    window.addEventListener('scroll', onScroll, { passive: true });
  }


  // The robot's eyes follow the pointer a little (desktop only, skipped for reduced motion).
  function trackEyes() {
    if (reduced || !(window.matchMedia && matchMedia('(pointer: fine)').matches)) return;
    var raf = 0, px = 0, py = 0;
    function apply() {
      raf = 0;
      var r = ui.launcher.getBoundingClientRect();
      if (!r.width) return;
      var dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2);
      var d = Math.sqrt(dx * dx + dy * dy) || 1, k = Math.min(d / 260, 1);
      host.style.setProperty('--pcb-lx', (dx / d * k * 2.2).toFixed(2) + 'px');
      host.style.setProperty('--pcb-ly', (dy / d * k * 1.6).toFixed(2) + 'px');
    }
    function centre() { host.style.setProperty('--pcb-lx', '0px'); host.style.setProperty('--pcb-ly', '0px'); }
    document.addEventListener('pointermove', function (e) {
      px = e.clientX; py = e.clientY;
      if (!raf) raf = (window.requestAnimationFrame || setTimeout)(apply);
    }, { passive: true });
    document.documentElement.addEventListener('mouseleave', centre);
  }

  function mount() {
    if (host.getAttribute('data-ready')) return;
    host.setAttribute('data-ready', '1');
    applyTheme();
    load();
    if (!state.msgs.length) seedWelcome();
    build();
    renderAll();
    wire();
    host.classList.add('pcb-in');
    trackEyes();
    PCB.mounted = true;
    autoVoice();
    scheduleGreeting();

    var reopen = false;
    try { reopen = sessionStorage.getItem(REOPEN_KEY) === '1'; sessionStorage.removeItem(REOPEN_KEY); } catch (e) { /* ignore */ }
    if (reopen && !small()) openPanel({ silent: true });

    PCB.mountCbs.splice(0).forEach(function (fn) { try { fn(); } catch (e) { /* a broken add-on must not break the chat */ } });
  }

  function whenReady(fn) {
    var tries = 0;
    (function check() {
      var ld = document.getElementById('ld');
      if (ld && !ld.classList.contains('off') && tries++ < 24) { setTimeout(check, 250); return; }
      fn();
    })();
  }
  function start() {
    var go = function () { whenReady(mount); };
    if ('requestIdleCallback' in window) requestIdleCallback(go, { timeout: 1500 }); else setTimeout(go, 300);
  }
  if (document.readyState === 'complete') start(); else window.addEventListener('load', start, { once: true });
})();
