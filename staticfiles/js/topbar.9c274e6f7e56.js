/* static/js/topbar.js
   Mobile overlay nav: accessible, focus-trapped, robust, desktop-safe. */
(() => {
  if (document.querySelector('.contact-fab')) {
    document.body.classList.add('has-contact-fab');
  }

  const header = document.querySelector('.bgm-topbar');
  const toggle = document.querySelector('.bgm-topbar__toggle');
  const nav = document.getElementById('bgmSiteNav');
  if (!header || !toggle || !nav) return;

  const syncHeight = () => {
    const height = Math.ceil(header.getBoundingClientRect().height);
    document.documentElement.style.setProperty('--bgm-topbar-height', `${height}px`);
  };

  if ('ResizeObserver' in window) {
    const ro = new ResizeObserver(syncHeight);
    ro.observe(header);
  }

  window.addEventListener('load', syncHeight);
  window.addEventListener('resize', syncHeight);
  syncHeight();

  const mq = window.matchMedia('(max-width: 960px)');
  let lastFocused = null;

  const getFocusable = () =>
    nav.querySelectorAll(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );

  // inert fallback (keeps nav out of the focus order when closed)
  const setInert = (on) => {
    if (on) {
      nav.setAttribute('aria-hidden', 'true');
      if ('inert' in nav) {
        nav.inert = true;
      } else {
        getFocusable().forEach((el) => {
          if (!el.dataset.prevTabindex && el.hasAttribute('tabindex')) {
            el.dataset.prevTabindex = el.getAttribute('tabindex');
          }
          el.setAttribute('tabindex', '-1');
        });
      }
    } else {
      nav.removeAttribute('aria-hidden');
      if ('inert' in nav) {
        nav.inert = false;
      } else {
        getFocusable().forEach((el) => {
          if (el.dataset.prevTabindex) {
            el.setAttribute('tabindex', el.dataset.prevTabindex);
            delete el.dataset.prevTabindex;
          } else {
            el.removeAttribute('tabindex');
          }
        });
      }
    }
  };

  const open = () => {
    if (header.classList.contains('bgm-topbar--open')) return;
    lastFocused = document.activeElement;
    header.classList.add('bgm-topbar--open');
    document.body.classList.add('nav-open');
    toggle.setAttribute('aria-expanded', 'true');
    setInert(false);

    const focusables = getFocusable();
    (focusables[0] || toggle).focus();

    document.addEventListener('keydown', onKeyDown, true);
    nav.addEventListener('click', onNavClick, true);
  };

  const close = () => {
    if (!header.classList.contains('bgm-topbar--open')) return;
    header.classList.remove('bgm-topbar--open');
    document.body.classList.remove('nav-open');
    toggle.setAttribute('aria-expanded', 'false');
    setInert(true);

    document.removeEventListener('keydown', onKeyDown, true);
    nav.removeEventListener('click', onNavClick, true);

    (lastFocused || toggle).focus();
  };

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'Tab') {
      const f = Array.from(getFocusable());
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const onNavClick = (e) => {
    // Close when clicking any link or the empty overlay area
    if (e.target.closest('a')) {
      close();
      return;
    }
    if (e.target === nav) close();
  };

  const onToggle = () =>
    header.classList.contains('bgm-topbar--open') ? close() : open();

  const applyMode = () => {
    if (mq.matches) {
      // Mobile
      setInert(true);
      toggle.addEventListener('click', onToggle);
    } else {
      // Desktop
      close();           // ensure clean state
      setInert(false);   // nav must be reachable on desktop
      toggle.removeEventListener('click', onToggle);
    }
  };

  mq.addEventListener('change', applyMode);
  applyMode();
})();

/* Preserve scroll position across same-page filter/search reloads (GET forms + filter links). */
(() => {
  const KEY = 'bgm:scrollrestore:v1';
  const TTL_MS = 15000;

  const read = () => {
    try {
      return JSON.parse(sessionStorage.getItem(KEY) || 'null');
    } catch {
      return null;
    }
  };

  const write = (payload) => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(payload));
    } catch {
      /* ignore */
    }
  };

  const clear = () => {
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  };

  const clampY = (y) => {
    const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    return Math.min(Math.max(0, y), max);
  };

  const restore = () => {
    const payload = read();
    if (!payload || typeof payload !== 'object') return;
    if (payload.path !== window.location.pathname) return;
    if (typeof payload.y !== 'number' || !Number.isFinite(payload.y)) return;
    if (typeof payload.ts !== 'number' || !Number.isFinite(payload.ts)) return;
    if (Date.now() - payload.ts > TTL_MS) {
      clear();
      return;
    }

    clear();
    const y = payload.y;
    const prev = document.documentElement.style.scrollBehavior;
    document.documentElement.style.scrollBehavior = 'auto';
    // Run after current scripts so layout is settled as much as possible.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        window.scrollTo(0, clampY(y));
        if (prev) {
          document.documentElement.style.scrollBehavior = prev;
        } else {
          document.documentElement.style.removeProperty('scroll-behavior');
        }
      });
    });
  };

  restore();
  window.addEventListener('pageshow', restore);

  // GET filter/search forms (same pathname): store scroll before navigation.
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    if (method !== 'get') return;
    if (!form.classList.contains('filters') && !form.hasAttribute('data-preserve-scroll')) return;

    let actionUrl = null;
    try {
      actionUrl = new URL(form.getAttribute('action') || window.location.href, window.location.href);
    } catch {
      return;
    }
    if (actionUrl.origin !== window.location.origin) return;
    if (actionUrl.pathname !== window.location.pathname) return;

    write({ path: actionUrl.pathname, y: window.scrollY, ts: Date.now() });
  }, true);

  // Filter links that keep the same pathname but change the query string.
  document.addEventListener('click', (event) => {
    if (event.defaultPrevented) return;
    if (event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const a = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!a) return;
    if (a.hasAttribute('download')) return;
    if (a.target && a.target.toLowerCase() === '_blank') return;
    if (a.hasAttribute('data-no-preserve-scroll')) return;

    let url = null;
    try {
      url = new URL(a.href, window.location.href);
    } catch {
      return;
    }
    if (url.origin !== window.location.origin) return;
    if (url.pathname !== window.location.pathname) return;
    if (url.search === window.location.search) return; // hash-only navigation doesn't reload

    write({ path: url.pathname, y: window.scrollY, ts: Date.now() });
  }, true);
})();
