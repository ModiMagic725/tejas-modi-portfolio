(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };

  // Mobile sidebar
  var side = $('#sidebar'), scrim = $('#scrim'), btn = $('#menuBtn');
  function toggle(open) {
    if (!side || !btn) return;
    side.classList.toggle('open', open);
    scrim.hidden = !open;
    btn.setAttribute('aria-expanded', open);
    document.body.style.overflow = open ? 'hidden' : '';
  }
  if (btn) btn.addEventListener('click', function () { toggle(!side.classList.contains('open')); });
  if (scrim) scrim.addEventListener('click', function () { toggle(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') toggle(false); });

  // Dismiss alerts
  document.addEventListener('click', function (e) {
    var x = e.target.closest('.alert-x');
    if (x) x.parentElement.remove();
  });

  // Close account menu on outside click
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.user-menu[open]').forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });

  // Password visibility (login page)
  var pw = $('#pwToggle');
  if (pw) pw.addEventListener('click', function () {
    var input = pw.parentElement.querySelector('input'), show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    pw.setAttribute('aria-pressed', show);
    pw.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
})();

// Confirm before destructive actions:  <form data-confirm="Delete this?"> ...
(function () {
  'use strict';
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (f.matches && f.matches('form[data-confirm]') && !window.confirm(f.getAttribute('data-confirm'))) e.preventDefault();
  });

  // Preview newly chosen images:  <input type="file" data-preview="#boxId">
  document.addEventListener('change', function (e) {
    var inp = e.target;
    if (!inp.matches || !inp.matches('input[type=file][data-preview]')) return;
    var box = document.querySelector(inp.getAttribute('data-preview'));
    if (!box) return;
    box.innerHTML = '';
    Array.prototype.slice.call(inp.files, 0, 12).forEach(function (f) {
      if (!/^image\//.test(f.type)) return;
      var img = document.createElement('img');
      img.className = 'thumb';
      img.alt = f.name;
      img.src = URL.createObjectURL(f);
      img.onload = function () { URL.revokeObjectURL(img.src); };
      box.appendChild(img);
    });
  });
})();

// Sidebar groups (Profile, Skills): smooth open / close
(function () {
  'use strict';
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.side-toggle') : null;
    if (!b) return;
    var group = b.parentElement, open = !group.classList.contains('open');
    group.classList.toggle('open', open);
    b.setAttribute('aria-expanded', open);
  });
})();