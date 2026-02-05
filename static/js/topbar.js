/* static/js/topbar.js
   Mobile overlay nav: accessible, focus-trapped, robust, desktop-safe. */
(() => {
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
