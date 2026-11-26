/* Heirloom Unbound site: tiny, no dependencies. */
(function () {
  var d = document, root = d.documentElement;
  root.classList.add('js');

  /* ---- Config: everything that goes live is OFF until C L sets it. ---- */
  var CONFIG = window.HEIRLOOM_SITE || {};
  // CONFIG.waitlistEndpoint: URL that accepts POST {email, interest, consent, source}. Empty = preview mode, nothing sent.
  // CONFIG.analytics: {provider:'plausible'|'umami', domain:'', src:''}. Empty/absent = no analytics script is loaded.

  /* Mobile menu */
  var btn = d.querySelector('.menu-btn'), nav = d.getElementById('nav');
  if (btn && nav) btn.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  /* Reveal on scroll (respects reduced motion; content is visible without JS) */
  var els = d.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { rootMargin: '0px 0px -8% 0px' });
    els.forEach(function (el) { io.observe(el); });
  } else els.forEach(function (el) { el.classList.add('in'); });

  /* Waitlist forms */
  d.querySelectorAll('form[data-waitlist]').forEach(function (f) {
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var status = f.querySelector('.status'), email = f.querySelector('input[type=email]');
      if (!email.checkValidity()) { status.textContent = 'Please enter a valid email address.'; email.focus(); return; }
      var consent = f.querySelector('input[name=consent]');
      if (consent && !consent.checked) { status.textContent = 'Please tick the box so we may email you about Heirloom.'; consent.focus(); return; }
      var data = { email: email.value.trim(), interest: (f.querySelector('select') || {}).value || '', consent: true, source: location.pathname };
      if (!CONFIG.waitlistEndpoint) {
        status.textContent = 'Preview only: the waitlist is not connected yet, so nothing was sent or saved.';
        track('waitlist_preview');
        return;
      }
      status.textContent = 'Saving…';
      fetch(CONFIG.waitlistEndpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
        .then(function (r) { if (!r.ok) throw 0; status.textContent = "You're on the list. We'll write when the beta opens."; f.reset(); track('waitlist_join'); })
        .catch(function () { status.textContent = 'Something went wrong. Please try again in a minute.'; });
    });
  });

  /* Analytics hook: off by default, cookieless providers only. */
  function track(name) { try { if (window.plausible) window.plausible(name); else if (window.umami) window.umami.track(name); } catch (e) {} }
  window.heirloomTrack = track;
  var a = CONFIG.analytics;
  if (a && a.provider && a.domain) {
    var s = d.createElement('script'); s.defer = true;
    if (a.provider === 'plausible') { s.src = a.src || 'https://plausible.io/js/script.js'; s.setAttribute('data-domain', a.domain); }
    else if (a.provider === 'umami') { s.src = a.src; s.setAttribute('data-website-id', a.domain); }
    d.head.appendChild(s);
  }
  d.querySelectorAll('[data-track]').forEach(function (el) { el.addEventListener('click', function () { track(el.getAttribute('data-track')); }); });
})();
