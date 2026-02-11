/* static/js/project-journal-feed.js
   Lightweight enhancements:
   - Image skeleton fade-in
   - Before/After slider (desktop pointer devices)
   - "Load more" feed pagination (progressive enhancement) */

(() => {
  const initSkeleton = (root = document) => {
    const medias = root.querySelectorAll('[data-skeleton]');
    medias.forEach((media) => {
      if (media.dataset.skeletonInit === '1') return;
      media.dataset.skeletonInit = '1';

      const img = media.querySelector('img');
      if (!img) return;

      const mark = () => media.classList.add('is-loaded');
      if (img.complete && img.naturalWidth > 0) {
        mark();
        return;
      }
      img.addEventListener('load', mark, { once: true });
      img.addEventListener('error', () => media.classList.add('is-loaded'), { once: true });
    });
  };

  const initCompare = (root = document) => {
    const canSlider = window.matchMedia('(pointer: fine)').matches && window.matchMedia('(min-width: 960px)').matches;
    const compares = root.querySelectorAll('[data-compare]');
    compares.forEach((el) => {
      if (el.dataset.compareInit === '1') return;
      el.dataset.compareInit = '1';

      const before = el.querySelector('[data-kind="before"] img');
      const after = el.querySelector('[data-kind="after"] img');
      const range = el.querySelector('input[type="range"]');
      if (!before || !after || !range) return;
      if (!canSlider) return;

      el.classList.add('pj-compare--slider');

      const setPos = (value) => {
        const v = Math.max(0, Math.min(100, Number(value)));
        el.style.setProperty('--pos', `${v}%`);
      };

      setPos(range.value || 50);
      range.addEventListener('input', () => setPos(range.value));
    });
  };

  const initLoadMore = () => {
    const feed = document.querySelector('[data-feed]');
    const btn = document.querySelector('[data-feed-load-more]');
    if (!feed || !btn) return;

    let busy = false;

    const parseNextUrl = (root) => {
      const marker = root.querySelector('[data-feed-next]');
      if (!marker) return '';
      return marker.getAttribute('data-next-url') || '';
    };

    const extractAndAppend = (html) => {
      const tmp = document.createElement('div');
      tmp.innerHTML = html;

      // Remove old next marker (we only keep the newest one).
      feed.querySelectorAll('[data-feed-next]').forEach((el) => el.remove());

      const nodes = Array.from(tmp.childNodes);
      nodes.forEach((node) => {
        feed.appendChild(node);
      });

      const next = parseNextUrl(feed);
      if (next) {
        btn.dataset.nextUrl = next;
        btn.setAttribute('href', next.replace(/([?&])fragment=1(&|$)/, '$1').replace(/[?&]$/, ''));
        btn.hidden = false;
      } else {
        btn.hidden = true;
      }

      initSkeleton(feed);
      initCompare(feed);
    };

    const load = async () => {
      const next = btn.dataset.nextUrl || '';
      if (!next || busy) return;
      busy = true;
      btn.setAttribute('aria-busy', 'true');

      try {
        const res = await fetch(next, {
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'fetch' },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const html = await res.text();
        extractAndAppend(html);
      } catch (err) {
        // Leave the normal link behavior as fallback.
        btn.hidden = false;
      } finally {
        busy = false;
        btn.removeAttribute('aria-busy');
      }
    };

    btn.addEventListener('click', (e) => {
      const next = btn.dataset.nextUrl || '';
      if (!next) return;
      e.preventDefault();
      load();
    });

    // Optional: auto-load when the button is near the viewport.
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) load();
        }
      }, { rootMargin: '600px' });
      io.observe(btn);
    }
  };

  const boot = () => {
    initSkeleton();
    initCompare();
    initLoadMore();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
