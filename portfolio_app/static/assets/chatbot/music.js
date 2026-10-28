/*
  Portfolio assistant - music player and music permission (loads after chatbot.js).

  - Adds ONE floating player to the existing widget (no second chatbot, no second player): a vinyl
    dock in the bottom-left corner that opens the full player.
  - Tracks come from GET /api/chatbot/music/, which lists the audio files inside the sub-folders of
      portfolio_app/static/assets/music/   (for example calm/, energetic/, flute/ - each folder is one mood)
    If there are no audio files, no music button, question or chip is shown at all.
  - Music NEVER starts on its own. The assistant asks first ("Would you like me to play some
    music?"). Pressing Yes, or pressing play in the player, is the visitor's permission.
  - The answer (yes / no), language, volume and position are kept for this browser tab only
    (sessionStorage), so the question is not repeated and the music can carry on across pages.
  - If the browser blocks playback, a clear Play button/message is shown instead of failing silently.
*/
(function () {
  'use strict';
  var PCB = window.PCB;
  if (!PCB || window.__pcbMusic) return;
  window.__pcbMusic = true;

  var el = PCB.el, ICON = PCB.ICON, host = PCB.host;
  var PL_KEY = 'pcb:pl2';                       // cached playlist for this tab
  var PL_TTL = 10 * 60 * 1000;
  // Categories ("moods") come from the music folders, e.g. calm / energetic / flute. M.cats keeps their order.
  var LABELS = {};
  function labelOf(id) {
    return LABELS[id] || String(id).replace(/^\d+[\s_.-]*/, '').replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); });
  }
  var ASK_TEXT = 'Would you like me to play some music? \uD83C\uDFB5';

  var M = {
    tracks: [], byLang: {}, cats: [],
    lang: '', cur: null, seekTo: 0, errs: 0, blocked: false, wantResume: false,
    vol: 0.6, muted: false, ui: {}
  };
  var audio = null;

  // ------------------------------------------------------------------ saved choice (this tab)
  function saved() { return PCB.session.get('music') || {}; }
  function patch(p) {
    var cur = saved();
    for (var k in p) { if (Object.prototype.hasOwnProperty.call(p, k)) cur[k] = p[k]; }
    PCB.session.set('music', cur);
  }
  function perm() { return saved().perm || null; }
  function fmt(t) {
    if (!isFinite(t) || t < 0) t = 0;
    var m = Math.floor(t / 60), s = Math.floor(t % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // ------------------------------------------------------------------ playlist
  function fetchPlaylist() {
    try {
      var c = JSON.parse(sessionStorage.getItem(PL_KEY) || 'null');
      if (c && Array.isArray(c.tracks) && Date.now() - c.ts < PL_TTL) return Promise.resolve(c.tracks);
    } catch (e) { /* ignore */ }
    if (!PCB.cfg.music) return Promise.resolve([]);
    return fetch(PCB.cfg.music, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var tracks = d && d.ok && Array.isArray(d.tracks) ? d.tracks.filter(valid) : [];
        try { sessionStorage.setItem(PL_KEY, JSON.stringify({ ts: Date.now(), tracks: tracks })); } catch (e) { /* ignore */ }
        return tracks;
      })
      .catch(function () { return []; });          // no music UI if the list can't be loaded
  }
  function valid(t) {
    return t && typeof t.id === 'string' && typeof t.title === 'string' && typeof t.url === 'string' &&
           typeof t.lang === 'string' && /^[A-Za-z0-9_-]{1,40}$/.test(t.lang) &&
           ((t.url.charAt(0) === '/' && t.url.charAt(1) !== '/') || /^https:\/\/[^\s]+$/.test(t.url));
  }
  function listFor(lang) { return M.byLang[lang] || []; }
  function defaultLang() {                                  // sensible default: the first category that has tracks
    for (var i = 0; i < M.cats.length; i++) { if (listFor(M.cats[i]).length) return M.cats[i]; }
    return '';
  }
  function others(l) { return M.cats.filter(function (c) { return c !== l && listFor(c).length; }); }

  // ------------------------------------------------------------------ audio
  function ensureAudio() {
    if (audio) return audio;
    audio = new Audio();
    audio.preload = 'none';
    audio.volume = M.vol;
    audio.muted = M.muted;
    audio.addEventListener('play', function () { onPlayState(true); });
    audio.addEventListener('pause', function () { onPlayState(false); });
    audio.addEventListener('ended', function () { next(true); });
    audio.addEventListener('loadedmetadata', function () {
      if (M.seekTo > 0 && isFinite(audio.duration)) {
        try { audio.currentTime = Math.min(M.seekTo, Math.max(0, audio.duration - 1)); } catch (e) { /* ignore */ }
      }
      M.seekTo = 0;
      paintTime();
    });
    var lastSave = 0;
    audio.addEventListener('timeupdate', function () {
      paintTime();
      var now = Date.now();
      if (now - lastSave > 2000) { lastSave = now; patch({ t: audio.currentTime }); }
    });
    audio.addEventListener('error', function () {
      if (!M.cur) return;
      M.errs++;
      if (M.errs <= listFor(M.cur.lang).length) next(true);           // skip a broken file, but never loop forever
      else { setNote('Sorry, this music could not be loaded right now.'); onPlayState(false); }
    });
    window.addEventListener('pagehide', function () {
      if (audio && M.cur) patch({ t: audio.currentTime, tid: M.cur.id, playing: !audio.paused });
    });
    return audio;
  }
  function onPlayState(playing) {
    PCB.musicActive = playing;
    host.classList.toggle('pcb-playing', playing);
    if (playing) { PCB.stopVoice(); M.blocked = false; host.classList.remove('pcb-attn'); setNote(''); }
    patch({ playing: playing });
    paintControls();
    paintList();
    if ('mediaSession' in navigator) { try { navigator.mediaSession.playbackState = playing ? 'playing' : 'paused'; } catch (e) { /* ignore */ } }
  }
  function tryPlay() {
    PCB.stopVoice();
    var a = ensureAudio();
    var p;
    try { p = a.play(); } catch (e) { p = Promise.reject(e); }
    return Promise.resolve(p).then(function () { M.errs = 0; return true; }, function (err) {
      if (err && err.name === 'NotAllowedError') blocked();
      return false;                                   // other errors arrive through the 'error' event
    });
  }
  function blocked() {
    M.blocked = true;
    onPlayState(false);
    host.classList.add('pcb-attn');
    setNote('Your browser needs one more tap. Press play to start the music.');
  }
  function setTrack(tr, t) {
    M.cur = tr;
    M.lang = tr.lang;
    M.seekTo = t || 0;
    var a = ensureAudio();
    a.src = tr.url;
    patch({ tid: tr.id, lang: tr.lang, t: t || 0 });
    paintNow(); paintList(); paintTime();
    if ('mediaSession' in navigator && window.MediaMetadata) {
      try { navigator.mediaSession.metadata = new MediaMetadata({ title: tr.title, artist: 'Portfolio music', album: labelOf(tr.lang) }); } catch (e) { /* ignore */ }
    }
  }
  function playTrack(tr) { grant(); setTrack(tr, 0); return tryPlay(); }
  function stepIndex(dir) {
    var list = listFor(M.cur ? M.cur.lang : M.lang);
    if (!list.length) return null;
    var i = M.cur ? list.indexOf(M.cur) : -1;
    return list[(i + dir + list.length) % list.length];
  }
  function next(auto) { var t = stepIndex(1); if (t) { setTrack(t, 0); tryPlay(); } else if (auto) onPlayState(false); }
  function prev() {
    if (audio && audio.currentTime > 4) { audio.currentTime = 0; return; }
    var t = stepIndex(-1); if (t) { setTrack(t, 0); tryPlay(); }
  }
  function togglePlay() {
    ensureAudio();
    if (!M.cur) {                                       // first press of play = permission + start
      var l = listFor(M.lang).length ? M.lang : defaultLang();
      var first = listFor(l)[0];
      if (first) playTrack(first);
      return;
    }
    if (audio.paused) { grant(); tryPlay(); } else { audio.pause(); }
  }
  function grant() { if (perm() !== 'yes') patch({ perm: 'yes', asked: true }); paintFoot(); }
  function startLang(lang) {
    var list = listFor(lang);
    if (!list.length) return false;
    M.lang = lang;
    patch({ lang: lang });
    playTrack(list[0]);
    return true;
  }

  // ------------------------------------------------------------------ player UI
  function build() {
    var u = M.ui;

    // Vinyl dock (bottom-left): a disc that spins while music plays and widens into a "now playing" pill.
    var dock = el('div', 'pcb-dock');
    dock.setAttribute('data-active', '0');
    var btn = el('button', 'pcb-disc');
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Open music player');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', 'pcb-player');
    btn.innerHTML = ICON.disc;
    var info = el('div', 'pcb-dock-info');
    var txt = el('button', 'pcb-dock-text');
    txt.type = 'button';
    txt.setAttribute('aria-label', 'Open music player');
    u.dTitle = el('span', 'pcb-dock-t', '');
    u.dSub = el('span', 'pcb-dock-s', '');
    txt.appendChild(u.dTitle); txt.appendChild(u.dSub);
    u.dPlay = el('button', 'pcb-dock-play');
    u.dPlay.type = 'button';
    u.dPlay.setAttribute('data-pl', 'dock-play');
    info.appendChild(txt); info.appendChild(u.dPlay);
    dock.appendChild(btn); dock.appendChild(info);

    var pl = el('div', 'pcb-player');
    pl.id = 'pcb-player';
    pl.setAttribute('role', 'dialog');
    pl.setAttribute('aria-modal', 'false');
    pl.setAttribute('aria-label', 'Music player');
    pl.tabIndex = -1;
    pl.hidden = true;

    var head = el('div', 'pcb-pl-head');
    head.appendChild(el('span', 'pcb-pl-title', 'Music'));
    var seg = el('div', 'pcb-seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'Music mood');
    M.cats.forEach(function (l) {
      var b = el('button', 'pcb-seg-btn', labelOf(l));
      b.type = 'button';
      b.setAttribute('data-lang', l);
      seg.appendChild(b);
    });
    seg.hidden = M.cats.length < 2;                         // one category: nothing to choose
    var close = el('button', 'pcb-icon-btn');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close music player');
    close.innerHTML = ICON.down;
    close.setAttribute('data-pl', 'close');
    head.appendChild(close);

    var now = el('div', 'pcb-pl-now');
    var art = el('div', 'pcb-pl-art');
    art.setAttribute('aria-hidden', 'true');
    art.innerHTML = ICON.note;
    var meta = el('div', 'pcb-pl-meta');
    u.track = el('div', 'pcb-pl-track', 'Nothing playing');
    u.sub = el('div', 'pcb-pl-sub', '');
    meta.appendChild(u.track); meta.appendChild(u.sub);
    now.appendChild(art); now.appendChild(meta);

    u.note = el('div', 'pcb-pl-note');
    u.note.setAttribute('role', 'status');
    u.note.hidden = true;

    var seek = el('div', 'pcb-pl-seek');
    u.cur = el('span', 'pcb-pl-time', '0:00');
    u.seek = el('input', 'pcb-range');
    u.seek.type = 'range'; u.seek.min = '0'; u.seek.max = '1000'; u.seek.value = '0';
    u.seek.setAttribute('aria-label', 'Seek');
    u.dur = el('span', 'pcb-pl-time', '0:00');
    seek.appendChild(u.cur); seek.appendChild(u.seek); seek.appendChild(u.dur);

    var ctl = el('div', 'pcb-pl-ctl');
    var bPrev = el('button', 'pcb-pl-btn'); bPrev.type = 'button'; bPrev.setAttribute('aria-label', 'Previous track'); bPrev.innerHTML = ICON.prev; bPrev.setAttribute('data-pl', 'prev');
    u.play = el('button', 'pcb-pl-btn pcb-pl-main'); u.play.type = 'button'; u.play.setAttribute('data-pl', 'play');
    var bNext = el('button', 'pcb-pl-btn'); bNext.type = 'button'; bNext.setAttribute('aria-label', 'Next track'); bNext.innerHTML = ICON.next; bNext.setAttribute('data-pl', 'next');
    ctl.appendChild(bPrev); ctl.appendChild(u.play); ctl.appendChild(bNext);

    var vol = el('div', 'pcb-pl-vol');
    u.mute = el('button', 'pcb-pl-btn pcb-pl-small'); u.mute.type = 'button'; u.mute.setAttribute('data-pl', 'mute');
    u.vol = el('input', 'pcb-range');
    u.vol.type = 'range'; u.vol.min = '0'; u.vol.max = '100'; u.vol.value = String(Math.round(M.vol * 100));
    u.vol.setAttribute('aria-label', 'Volume');
    vol.appendChild(u.mute); vol.appendChild(u.vol);

    u.list = el('ul', 'pcb-pl-list');
    u.list.setAttribute('aria-label', 'Tracks');
    u.foot = el('div', 'pcb-pl-foot');

    pl.appendChild(head); pl.appendChild(seg); pl.appendChild(now); pl.appendChild(u.note); pl.appendChild(seek);
    pl.appendChild(ctl); pl.appendChild(vol); pl.appendChild(u.list); pl.appendChild(u.foot);

    host.appendChild(dock); host.appendChild(pl);
    u.btn = btn; u.dock = dock; u.dText = txt; u.panel = pl; u.seg = seg;
  }

  function fill(input, pct) { input.style.setProperty('--pcb-fill', pct + '%'); }
  function setNote(text) { M.ui.note.textContent = text; M.ui.note.hidden = !text; }
  function paintNow() {
    var u = M.ui, tr = M.cur;
    u.track.textContent = tr ? tr.title : 'Nothing playing';
    var list = listFor(tr ? tr.lang : M.lang);
    u.sub.textContent = tr ? labelOf(tr.lang) + ' \u00B7 ' + (list.indexOf(tr) + 1) + ' of ' + list.length
                           : labelOf(M.lang) + ' \u00B7 ' + list.length + (list.length === 1 ? ' track' : ' tracks');
    u.dTitle.textContent = tr ? tr.title : '';
    u.dSub.textContent = tr ? labelOf(tr.lang) + ' \u00B7 ' + (list.indexOf(tr) + 1) + ' of ' + list.length : '';
    u.dock.setAttribute('data-active', tr ? '1' : '0');
    Array.prototype.forEach.call(u.seg.children, function (b) {
      var l = b.getAttribute('data-lang');
      b.setAttribute('aria-pressed', String(l === M.lang));
      b.disabled = listFor(l).length === 0;
    });
  }
  function paintControls() {
    var u = M.ui, playing = !!(audio && !audio.paused);
    u.play.innerHTML = playing ? ICON.pause : ICON.play;
    u.play.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    u.mute.innerHTML = M.muted || M.vol === 0 ? ICON.mute : ICON.vol;
    u.mute.setAttribute('aria-label', M.muted ? 'Unmute' : 'Mute');
    u.mute.setAttribute('aria-pressed', String(M.muted));
    fill(u.vol, M.muted ? 0 : M.vol * 100);
    u.btn.setAttribute('aria-label', playing ? 'Open music player (music is playing)' : 'Open music player');
    u.dPlay.innerHTML = playing ? ICON.pause : ICON.play;
    u.dPlay.setAttribute('aria-label', playing ? 'Pause music' : 'Play music');
  }
  function paintTime() {
    var u = M.ui;
    if (!audio || !u.seek) return;
    var d = audio.duration, t = audio.currentTime;
    u.cur.textContent = fmt(t);
    u.dur.textContent = isFinite(d) ? fmt(d) : '0:00';
    if (document.activeElement !== u.seek) u.seek.value = isFinite(d) && d > 0 ? String(Math.round(t / d * 1000)) : '0';
    fill(u.seek, u.seek.value / 10);
  }
  function paintList() {
    var u = M.ui, list = listFor(M.lang);
    u.list.textContent = '';
    if (!list.length) {
      var li0 = el('li', 'pcb-pl-empty', 'No ' + labelOf(M.lang) + ' tracks yet.');
      u.list.appendChild(li0);
      return;
    }
    list.forEach(function (tr) {
      var li = el('li');
      var b = el('button', 'pcb-pl-item');
      b.type = 'button';
      b.setAttribute('data-track', tr.id);
      var active = M.cur === tr;
      if (active) { b.setAttribute('aria-current', 'true'); b.className += ' pcb-on'; }
      b.appendChild(el('span', 'pcb-pl-item-t', tr.title));
      if (active && audio && !audio.paused) b.appendChild(el('span', 'pcb-pl-item-s', 'Playing'));
      li.appendChild(b);
      u.list.appendChild(li);
    });
  }
  function paintFoot() {
    var u = M.ui;
    if (!u.foot) return;
    u.foot.textContent = '';
    if (perm() === 'yes') {
      var off = el('button', 'pcb-pl-off', 'Turn music off');
      off.type = 'button';
      off.setAttribute('data-pl', 'off');
      u.foot.appendChild(el('span', null, 'Music is on'));
      u.foot.appendChild(off);
    } else {
      u.foot.appendChild(el('span', null, 'Music plays only when you press play.'));
    }
  }
  function paintAll() { paintNow(); paintControls(); paintTime(); paintList(); paintFoot(); }

  // ------------------------------------------------------------------ open / close
  // Logical state (not the `hidden` attribute, which only flips after the closing animation).
  function isOpen() { return host.getAttribute('data-player') === 'open'; }
  function openPlayer() {
    if (PCB.narrow()) PCB.closeChat({ noFocus: true });
    PCB.hideBubble();
    var u = M.ui;
    PCB.panelBusy = true;
    host.setAttribute('data-player', 'open');
    u.btn.setAttribute('aria-expanded', 'true');
    u.panel.hidden = false;
    void u.panel.offsetWidth;
    u.panel.classList.add('pcb-open');
    paintAll();
    if (window.matchMedia && matchMedia('(pointer: fine)').matches) u.play.focus(); else u.panel.focus();
  }
  function closePlayer(opts) {
    var u = M.ui;
    if (!u.panel || !isOpen()) return;
    PCB.panelBusy = false;
    host.removeAttribute('data-player');
    u.btn.setAttribute('aria-expanded', 'false');
    u.panel.classList.remove('pcb-open');
    var done = function () { if (!host.getAttribute('data-player')) u.panel.hidden = true; };
    if (PCB.reduced) done(); else setTimeout(done, 230);
    if (!opts || !opts.noFocus) u.btn.focus();
    setTimeout(PCB.flushBubbles, 600);
  }
  PCB.closePlayer = closePlayer;

  // ------------------------------------------------------------------ permission conversation
  function say(src, userText, botMsg) {
    if (src === 'bubble') PCB.push({ role: 'user', text: userText, local: true });
    botMsg.role = 'bot'; botMsg.local = true; botMsg.links = botMsg.links || [];
    PCB.push(botMsg);
  }
  function switchChip(lang) {                               // up to three other moods to jump to
    return others(lang).slice(0, 3).map(function (o) { return { label: 'Play ' + labelOf(o) + ' instead', action: 'music-lang-' + o }; });
  }
  var A = PCB.actions;
  A['music-yes'] = function (src) {
    patch({ perm: 'yes', asked: true });
    var lang = saved().lang && listFor(saved().lang).length ? saved().lang : defaultLang();
    startLang(lang);
    var sugg = switchChip(lang).concat([{ label: 'Open the player', action: 'music-open' }]);
    say(src, 'Yes, play music', { text: '\uD83C\uDFB5 Playing ' + labelOf(lang) + ' music. You can ' + (M.cats.length > 1 ? 'switch the mood, ' : '') + 'change tracks or set the volume in the player.', sugg: sugg });
    paintFoot();
    if (src === 'bubble') PCB.showBubble({ text: 'Playing ' + labelOf(lang) + ' music \uD83C\uDFB5', kind: 'info', ttl: 6000,
      actions: others(lang).slice(0, 2).map(function (o) { return { label: 'Try ' + labelOf(o), act: 'music-lang-' + o }; }) });
  };
  A['music-no'] = function (src) {
    patch({ perm: 'no', asked: true, playing: false });
    if (audio) audio.pause();
    say(src, 'No thanks', { text: "No problem, I won't play any music. If you change your mind, the \uD83C\uDFB5 button opens the player any time.",
      sugg: [{ label: 'Show me your projects', intent: 'projects' }, { label: 'What are your skills?', intent: 'skills' }] });
    paintFoot();
  };
  function langAction(lang) {
    return function (src) {
      if (!listFor(lang).length) return;
      patch({ perm: 'yes', asked: true });
      startLang(lang);
      say(src, 'Play ' + labelOf(lang), { text: '\uD83C\uDFB5 Switched to ' + labelOf(lang) + ' music.',
        sugg: switchChip(lang).concat([{ label: 'Open the player', action: 'music-open' }]) });
      paintFoot();
    };
  }
  A['music-open'] = function () { openPlayer(); };
  // Welcome-chip: an explicit request, so it works even after the visitor said No earlier.
  A['music-play'] = function (src) { if (perm() === 'yes') openPlayer(); else A['music-yes'](src); };
  A['music-resume'] = function () { grant(); ensureAudio(); if (!M.cur) togglePlay(); else tryPlay(); };

  // Hide the Yes/No chips once the visitor has answered (also on pages visited later).
  PCB.filters.push(function (chip) {
    if (chip.action === 'music-yes' || chip.action === 'music-no') return !perm();
    return true;
  });

  function askInBubble() {
    if (perm() || saved().asked || PCB.state.open) return;
    patch({ asked: true });
    PCB.showBubble({ text: ASK_TEXT, kind: 'music', ttl: 25000,
      actions: [{ label: 'Yes, play', act: 'music-yes' }, { label: 'No thanks', act: 'music-no' }] });
  }
  function askInChat() {
    patch({ asked: true });
    PCB.push({ role: 'bot', local: true, text: ASK_TEXT, links: [],
      sugg: [{ label: 'Yes, play music', action: 'music-yes' }, { label: 'No thanks', action: 'music-no' }] });
  }
  PCB.chatOpenCbs.push(function (info) {
    if (perm()) return;
    // ask once: in the chat if the bubble question was just on screen or never shown
    if (info.bubbleKind === 'music' || !saved().asked) askInChat();
  });

  // ------------------------------------------------------------------ resume on a later page
  var GESTURES = ['pointerdown', 'touchend', 'keydown'];
  function resumeFromSession() {
    var s = saved();
    if (perm() !== 'yes' || !s.playing) return;
    var tr = null;
    listFor(s.lang || defaultLang()).forEach(function (t) { if (t.id === s.tid) tr = t; });
    if (!tr) M.tracks.forEach(function (t) { if (t.id === s.tid) tr = t; });
    if (!tr) return;
    setTrack(tr, s.t || 0);
    tryPlay().then(function (ok) {
      if (ok) return;
      // Blocked on this page: show a clear Play button, and carry on at the visitor's first tap.
      M.wantResume = true;
      PCB.whenBubbleFree(function () {
        if (M.blocked && !(audio && !audio.paused)) {
          PCB.showBubble({ text: 'Your music is paused. Tap to resume \uD83C\uDFB5', kind: 'music-resume', ttl: 15000, actions: [{ label: 'Play', act: 'music-resume' }] });
        }
      });
      var onGesture = function (e) {
        GESTURES.forEach(function (g) { document.removeEventListener(g, onGesture, true); });
        if (host.contains(e.target) || !M.wantResume) return;
        M.wantResume = false;
        tryPlay();
      };
      GESTURES.forEach(function (g) { document.addEventListener(g, onGesture, true); });
    });
  }

  // ------------------------------------------------------------------ events
  function wire() {
    var u = M.ui;
    var toggle = function () { isOpen() ? closePlayer() : openPlayer(); };
    u.btn.addEventListener('click', toggle);
    u.dText.addEventListener('click', toggle);
    u.dPlay.addEventListener('click', function () { togglePlay(); });
    u.panel.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); closePlayer(); }
    });
    u.panel.addEventListener('click', function (e) {
      var t = e.target;
      var seg = t.closest && t.closest('[data-lang]');
      if (seg) {
        var l = seg.getAttribute('data-lang');
        if (!listFor(l).length) return;
        if (audio && !audio.paused) { startLang(l); } else { M.lang = l; patch({ lang: l }); M.cur = (M.cur && M.cur.lang === l) ? M.cur : null; paintAll(); }
        return;
      }
      var item = t.closest && t.closest('[data-track]');
      if (item) {
        var id = item.getAttribute('data-track');
        listFor(M.lang).forEach(function (tr) { if (tr.id === id) playTrack(tr); });
        return;
      }
      var b = t.closest && t.closest('[data-pl]');
      if (!b) return;
      var a = b.getAttribute('data-pl');
      if (a === 'close') closePlayer();
      else if (a === 'play') togglePlay();
      else if (a === 'next') { grant(); if (!M.cur) togglePlay(); else next(false); }
      else if (a === 'prev') { grant(); if (!M.cur) togglePlay(); else prev(); }
      else if (a === 'mute') { M.muted = !M.muted; ensureAudio().muted = M.muted; patch({ muted: M.muted }); paintControls(); }
      else if (a === 'off') {
        if (audio) audio.pause();
        patch({ perm: 'no', playing: false });
        setNote('Music is off. Press play any time to turn it back on.');
        paintAll();
      }
    });
    u.seek.addEventListener('input', function () {
      fill(u.seek, u.seek.value / 10);
      if (audio && isFinite(audio.duration)) audio.currentTime = (u.seek.value / 1000) * audio.duration;
    });
    u.vol.addEventListener('input', function () {
      M.vol = u.vol.value / 100;
      ensureAudio().volume = M.vol;
      if (M.vol > 0 && M.muted) { M.muted = false; audio.muted = false; }
      patch({ vol: M.vol, muted: M.muted });
      paintControls();
    });
    if ('mediaSession' in navigator) {
      [['play', function () { grant(); tryPlay(); }], ['pause', function () { if (audio) audio.pause(); }],
       ['nexttrack', function () { next(false); }], ['previoustrack', function () { prev(); }]].forEach(function (h) {
        try { navigator.mediaSession.setActionHandler(h[0], h[1]); } catch (e) { /* not supported */ }
      });
    }
  }

  // ------------------------------------------------------------------ placement
  // The dock sits in the bottom-left corner. The Homepage has a fixed social-icon rail (.soc) there
  // on large screens, so on that page the dock rests just above the rail instead of covering it.
  function placeDock() {
    var bottom = 16, left = 16;
    var soc = document.querySelector('.soc');
    if (soc && getComputedStyle(soc).display !== 'none') {
      var r = soc.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        bottom = Math.max(16, Math.round(window.innerHeight - r.top + 14));
        left = Math.max(16, Math.round(r.left + r.width / 2 - 28));      // line up with the icon column
      }
    }
    host.style.setProperty('--pcb-dock-b', bottom + 'px');
    host.style.setProperty('--pcb-dock-l', left + 'px');
  }
  var placeRaf = 0;
  function onResize() {
    if (placeRaf) return;
    placeRaf = (window.requestAnimationFrame || setTimeout)(function () { placeRaf = 0; placeDock(); });
  }

  // ------------------------------------------------------------------ start
  function init() {
    fetchPlaylist().then(function (tracks) {
      if (!tracks.length) return;                         // no MP3 files added yet: stay completely out of the way
      M.tracks = tracks;
      tracks.forEach(function (t) {
        if (!M.byLang[t.lang]) { M.byLang[t.lang] = []; M.cats.push(t.lang); }
        M.byLang[t.lang].push(t);
        LABELS[t.lang] = (typeof t.label === 'string' && t.label) ? t.label.slice(0, 40) : labelOf(t.lang);
      });
      M.cats.forEach(function (c) { A['music-lang-' + c] = langAction(c); });
      var s = saved();
      if (typeof s.vol === 'number') M.vol = Math.min(1, Math.max(0, s.vol));
      M.muted = !!s.muted;
      M.lang = s.lang && listFor(s.lang).length ? s.lang : defaultLang();
      build();
      placeDock();
      window.addEventListener('resize', onResize);
      wire();
      paintAll();
      PCB.welcomeExtra.push({ label: perm() === 'yes' ? 'Open the music player' : 'Play some music \uD83C\uDFB5', action: 'music-play' });
      PCB.refreshWelcome();
      resumeFromSession();
      if (!perm() && !s.asked) PCB.whenBubbleFree(askInBubble);
    });
  }
  PCB.onMount(init);
})();
