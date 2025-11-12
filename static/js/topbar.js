// static/js/topbar.js
(() => {
  const header = document.querySelector('header.site-header');
  const toggle = header?.querySelector('.site-header__toggle');
  const nav    = document.getElementById('siteNav');
  if (!header || !toggle || !nav) return;

  // Prevent double-binding
  if (header.dataset.bgmTopbarBound === '1') return;
  header.dataset.bgmTopbarBound = '1';

  const mql = window.matchMedia('(max-width: 960px)');
  let lastFocus = null;

  const isOpen = () => header.classList.contains('site-header--open');

  function setOpen(open){
    header.classList.toggle('site-header--open', open);
    document.body.classList.toggle('nav-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    nav.setAttribute('aria-hidden', open ? 'false' : 'true');

    if (open) {
      lastFocus = document.activeElement;
      const first = nav.querySelector('a,button,[tabindex]:not([tabindex="-1"])');
      setTimeout(() => (first || nav).focus({ preventScroll:true }), 0);
      document.addEventListener('keydown', onKey);
    } else {
      document.removeEventListener('keydown', onKey);
      if (lastFocus) lastFocus.focus({ preventScroll:true });
    }
  }

  function onKey(e){
    if (!mql.matches || !isOpen()) return;
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key !== 'Tab') return;

    // Focus trap
    const nodes = nav.querySelectorAll('a,button,[tabindex]:not([tabindex="-1"])');
    const list = Array.from(nodes).filter(el => !el.disabled && el.offsetParent !== null);
    if (!list.length) return;
    const first = list[0], last = list[list.length - 1];
    if (e.shiftKey && document.activeElement === first){ e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last){ e.preventDefault(); first.focus(); }
  }

  // Toggle open/close
  toggle.addEventListener('click', (e) => {
    if (!mql.matches) return;
    e.preventDefault();
    setOpen(!isOpen());
  });

  // Close when any menu item is activated
  nav.addEventListener('click', (e) => {
    if (!mql.matches) return;
    if (e.target.closest('a,button')) setOpen(false);
  });

  // Close safely when resizing to desktop
  mql.addEventListener?.('change', (ev) => { if (!ev.matches) setOpen(false); });

  // Initial ARIA
  toggle.setAttribute('aria-expanded', 'false');
  nav.setAttribute('aria-hidden', 'true');
})();
