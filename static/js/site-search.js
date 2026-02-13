/* static/js/site-search.js
   Lightweight, dependency-free live search for products + services.
   Renders suggestions in the topbar and falls back to GET submit to /store/. */
(() => {
  if (window.__bgmSiteSearchInit) return;
  window.__bgmSiteSearchInit = true;

  const initWidget = (widget) => {
    const input = widget.querySelector('.bgm-topbar__search-input');
    const menu = widget.querySelector('[data-site-search-menu]');
    const clearBtn = widget.querySelector('[data-site-search-clear]');
    if (!input || !menu) return;

    const productsUrl = widget.dataset.productsUrl || '';
    const servicesUrl = widget.dataset.servicesUrl || '';
    const productsPage = widget.dataset.productsPage || '/store/';
    const servicesPage = widget.dataset.servicesPage || '/accounts/#services';
    const minChars = Math.max(1, parseInt(widget.dataset.minChars || '2', 10) || 2);
    const maxPerGroup = Math.max(1, parseInt(widget.dataset.maxResults || '6', 10) || 6);

    let debounceTimer = 0;
    let lastQuery = '';
    let abortController = null;
    let focusables = [];
    let focusIndex = -1;

    const setMenuOpen = (open) => {
      const isOpen = !menu.hasAttribute('hidden');
      if (open === isOpen) return;
      if (open) menu.removeAttribute('hidden');
      else menu.setAttribute('hidden', '');
      input.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) {
        focusIndex = -1;
        focusables = [];
      }
    };

    const clearMenu = () => {
      while (menu.firstChild) menu.removeChild(menu.firstChild);
    };

    const normalizeQuery = (value) => (value || '').trim();

    const urlWithQuery = (base, q) => {
      const query = encodeURIComponent(q);
      if (!base) return '';
      const hashIndex = base.indexOf('#');
      const head = hashIndex >= 0 ? base.slice(0, hashIndex) : base;
      const tail = hashIndex >= 0 ? base.slice(hashIndex) : '';
      const sep = head.includes('?') ? '&' : '?';
      return `${head}${sep}q=${query}${tail}`;
    };

    const addAction = (href, label, hint) => {
      const a = document.createElement('a');
      a.className = 'bgm-topbar__search-action';
      a.href = href;
      const span = document.createElement('span');
      span.textContent = label;
      const small = document.createElement('small');
      small.textContent = hint;
      a.appendChild(span);
      a.appendChild(small);
      menu.appendChild(a);
    };

    const addGroup = (label) => {
      const h = document.createElement('div');
      h.className = 'bgm-topbar__search-group';
      h.textContent = label;
      menu.appendChild(h);
    };

    const addEmpty = (text) => {
      const div = document.createElement('div');
      div.className = 'bgm-topbar__search-empty';
      div.textContent = text;
      menu.appendChild(div);
    };

    const addItem = ({ href, title, subtitle, imageUrl }) => {
      const a = document.createElement('a');
      a.className = 'bgm-topbar__search-item';
      a.href = href;

      const thumb = document.createElement('span');
      thumb.className = 'bgm-topbar__search-thumb';
      if (imageUrl) {
        const img = document.createElement('img');
        img.src = imageUrl;
        img.alt = '';
        img.loading = 'lazy';
        img.decoding = 'async';
        thumb.appendChild(img);
      }

      const text = document.createElement('span');
      text.className = 'bgm-topbar__search-text';

      const t = document.createElement('div');
      t.className = 'bgm-topbar__search-title';
      t.textContent = title || '';
      text.appendChild(t);

      if (subtitle) {
        const sub = document.createElement('div');
        sub.className = 'bgm-topbar__search-sub';
        sub.textContent = subtitle;
        text.appendChild(sub);
      }

      a.appendChild(thumb);
      a.appendChild(text);
      menu.appendChild(a);
    };

    const syncFocusables = () => {
      focusables = Array.from(menu.querySelectorAll('a[href]'));
      focusIndex = -1;
    };

    const renderResults = (query, products, services) => {
      clearMenu();

      const q = normalizeQuery(query);
      if (!q || q.length < minChars) {
        setMenuOpen(false);
        return;
      }

      const productsSearchHref = urlWithQuery(productsPage, q);
      const servicesSearchHref = urlWithQuery(servicesPage, q);

      addAction(productsSearchHref, `Search products for "${q}"`, 'Products');
      addAction(servicesSearchHref, `Search services for "${q}"`, 'Services');

      const hasProducts = Array.isArray(products) && products.length > 0;
      const hasServices = Array.isArray(services) && services.length > 0;

      if (!hasProducts && !hasServices) {
        addEmpty('No matches yet. Try a different keyword.');
        setMenuOpen(true);
        syncFocusables();
        return;
      }

      if (hasProducts) {
        addGroup('Products');
        products.slice(0, maxPerGroup).forEach((p) => {
          addItem({
            href: p.url || productsSearchHref,
            title: p.name || 'Product',
            subtitle: p.category || '',
            imageUrl: p.image || '',
          });
        });
      }

      if (hasServices) {
        addGroup('Services');
        services.slice(0, maxPerGroup).forEach((s) => {
          const serviceHref = urlWithQuery(servicesPage, s.name || q);
          addItem({
            href: serviceHref,
            title: s.name || 'Service',
            subtitle: s.category || '',
            imageUrl: s.image || '',
          });
        });
      }

      setMenuOpen(true);
      syncFocusables();
    };

    const renderLoading = (query) => {
      clearMenu();
      addEmpty(`Searching for "${normalizeQuery(query)}"...`);
      setMenuOpen(true);
      syncFocusables();
    };

    const fetchJson = async (url, signal) => {
      const resp = await fetch(url, {
        method: 'GET',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return resp.json();
    };

    const runSearch = async (query) => {
      const q = normalizeQuery(query);
      if (!q || q.length < minChars) {
        // Allow the same query to be re-run after clearing/backspacing.
        lastQuery = '';
        clearMenu();
        setMenuOpen(false);
        return;
      }
      if (q === lastQuery) return;
      lastQuery = q;

      if (abortController) abortController.abort();
      const controller = 'AbortController' in window ? new AbortController() : null;
      abortController = controller;
      const signal = controller ? controller.signal : undefined;

      renderLoading(q);

      const productHref = productsUrl ? urlWithQuery(productsUrl, q) : '';
      const serviceHref = servicesUrl ? urlWithQuery(servicesUrl, q) : '';

      const [productsRes, servicesRes] = await Promise.allSettled([
        productHref ? fetchJson(productHref, signal) : Promise.resolve({ results: [] }),
        serviceHref ? fetchJson(serviceHref, signal) : Promise.resolve({ results: [] }),
      ]);

      // Ignore results from aborted or stale (superseded) searches.
      if (controller && controller.signal && controller.signal.aborted) return;
      if (abortController !== controller) return;

      const products =
        productsRes.status === 'fulfilled' && productsRes.value && productsRes.value.results
          ? productsRes.value.results
          : [];
      const services =
        servicesRes.status === 'fulfilled' && servicesRes.value && servicesRes.value.results
          ? servicesRes.value.results
          : [];

      renderResults(q, products, services);
    };

    const scheduleSearch = () => {
      if (debounceTimer) window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(() => runSearch(input.value), 160);
    };

    const syncClear = () => {
      if (!clearBtn) return;
      const hasValue = Boolean(normalizeQuery(input.value));
      if (hasValue) clearBtn.removeAttribute('hidden');
      else clearBtn.setAttribute('hidden', '');
    };

    input.addEventListener('input', () => {
      syncClear();
      scheduleSearch();
    });

    input.addEventListener('focus', () => {
      syncClear();
      if (normalizeQuery(input.value).length >= minChars && menu.childElementCount) {
        setMenuOpen(true);
        syncFocusables();
      }
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        setMenuOpen(false);
        return;
      }
      if (e.key === 'ArrowDown') {
        if (menu.hasAttribute('hidden')) return;
        if (!focusables.length) syncFocusables();
        if (!focusables.length) return;
        e.preventDefault();
        focusIndex = Math.min(focusIndex + 1, focusables.length - 1);
        focusables[focusIndex].focus();
      }
    });

    menu.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setMenuOpen(false);
        input.focus();
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!focusables.length) syncFocusables();
        if (!focusables.length) return;
        e.preventDefault();
        const dir = e.key === 'ArrowDown' ? 1 : -1;
        const next = focusables.indexOf(document.activeElement) + dir;
        if (next < 0) input.focus();
        else if (next >= focusables.length) focusables[focusables.length - 1].focus();
        else focusables[next].focus();
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        input.value = '';
        lastQuery = '';
        syncClear();
        clearMenu();
        setMenuOpen(false);
        input.focus();
      });
    }

    document.addEventListener(
      'pointerdown',
      (e) => {
        if (widget.contains(e.target)) return;
        setMenuOpen(false);
      },
      { passive: true }
    );

    // Initial state
    syncClear();
    setMenuOpen(false);
  };

  const boot = () => {
    const widgets = document.querySelectorAll('[data-site-search]');
    if (!widgets.length) return;
    widgets.forEach(initWidget);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
