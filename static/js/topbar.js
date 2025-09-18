(function(){
  const header = document.querySelector('.site-header');
  if (!header) return;

  const toggle = header.querySelector('.site-header__toggle');
  const nav = header.querySelector('nav');
  if (!toggle || !nav) return;

  const body = document.body;
  const docEl = document.documentElement;
  const mq = window.matchMedia('(max-width: 960px)');

  const updateHeight = () => {
    const height = header.getBoundingClientRect().height;
    if (height > 0) {
      const value = `${Math.round(height)}px`;
      header.style.setProperty('--site-header-height', value);
      docEl.style.setProperty('--site-header-height', value);
    }
  };

  let resizeTimer = null;
  const onResize = () => {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(updateHeight, 120);
  };

  const closeMenu = ({ focusToggle = true } = {}) => {
    header.classList.remove('site-header--open');
    body.classList.remove('nav-open');
    toggle.setAttribute('aria-expanded', 'false');
    if (focusToggle) {
      try {
        toggle.focus({ preventScroll: true });
      } catch (err) {
        toggle.focus();
      }
    }
  };

  const openMenu = () => {
    header.classList.add('site-header--open');
    body.classList.add('nav-open');
    toggle.setAttribute('aria-expanded', 'true');
    updateHeight();
    const focusable = nav.querySelector('a, button, [tabindex]:not([tabindex="-1"])');
    if (focusable) {
      try {
        focusable.focus({ preventScroll: true });
      } catch (err) {
        focusable.focus();
      }
    }
  };

  const toggleMenu = () => {
    if (header.classList.contains('site-header--open')) {
      closeMenu({ focusToggle: false });
    } else {
      openMenu();
    }
  };

  const handleMediaChange = (event) => {
    if (!event.matches) {
      closeMenu({ focusToggle: false });
    }
    updateHeight();
  };

  toggle.addEventListener('click', toggleMenu);

  window.addEventListener('resize', onResize, { passive: true });
  window.addEventListener('orientationchange', updateHeight, { passive: true });

  window.addEventListener('keyup', (event) => {
    if (event.key === 'Escape' && header.classList.contains('site-header--open')) {
      closeMenu();
    }
  });

  nav.addEventListener('click', (event) => {
    const link = event.target.closest('a');
    if (!link) return;
    if (mq.matches) {
      closeMenu({ focusToggle: false });
    }
  });

  if (mq.addEventListener) {
    mq.addEventListener('change', handleMediaChange);
  } else if (mq.addListener) {
    mq.addListener(handleMediaChange);
  }

  document.addEventListener('DOMContentLoaded', updateHeight);
  updateHeight();
})();
