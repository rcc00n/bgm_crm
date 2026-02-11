/* static/js/project-journal-feed.js
   Lightweight enhancements:
   - Image skeleton fade-in
   - Before/After slider (desktop pointer devices)
   - "Load more" feed pagination (progressive enhancement) */

(() => {
  const COMPARE_HINT_KEY = 'pj_compare_hint_dismissed_v1';
  let compareHintShown = false;

  const isCompareHintDismissed = () => {
    try {
      return window.localStorage.getItem(COMPARE_HINT_KEY) === '1';
    } catch (err) {
      return false;
    }
  };

  const dismissCompareHintForever = () => {
    try { window.localStorage.setItem(COMPARE_HINT_KEY, '1'); } catch (err) {}
  };

  const initSkeleton = (root = document) => {
    const medias = root.querySelectorAll('[data-skeleton]');
    medias.forEach((media) => {
      if (media.dataset.skeletonInit === '1') return;
      media.dataset.skeletonInit = '1';

      const img = media.querySelector('img');
      if (!img) return;

      const mark = () => media.classList.add('is-loaded');
      if (img.complete) {
        mark();
        return;
      }
      const fallbackTimer = window.setTimeout(mark, 4500);
      const markOnce = () => {
        window.clearTimeout(fallbackTimer);
        mark();
      };
      img.addEventListener('load', markOnce, { once: true });
      img.addEventListener('error', markOnce, { once: true });
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
      const sourcesScript = el.querySelector('[data-compare-sources]');
      const prevBtn = el.querySelector('[data-compare-prev]');
      const nextBtn = el.querySelector('[data-compare-next]');
      const pager = el.querySelector('[data-compare-pager]');

      const resetSkeleton = (mediaEl, imgEl) => {
        if (!mediaEl || !imgEl) return;
        mediaEl.classList.remove('is-loaded');
        const mark = () => mediaEl.classList.add('is-loaded');
        if (imgEl.complete) {
          mark();
          return;
        }
        const fallbackTimer = window.setTimeout(mark, 4500);
        const markOnce = () => {
          window.clearTimeout(fallbackTimer);
          mark();
        };
        imgEl.addEventListener('load', markOnce, { once: true });
        imgEl.addEventListener('error', markOnce, { once: true });
      };

      const ratioClasses = [
        'pj-compare--ratio-landscape',
        'pj-compare--ratio-mixed',
        'pj-compare--ratio-portrait',
      ];

      const applyCompareRatioClass = () => {
        if (!el.classList.contains('pj-compare--slider')) return;

        ratioClasses.forEach((cls) => el.classList.remove(cls));

        const beforeRatio = before && before.naturalWidth && before.naturalHeight
          ? (before.naturalWidth / before.naturalHeight)
          : 0;
        const afterRatio = after && after.naturalWidth && after.naturalHeight
          ? (after.naturalWidth / after.naturalHeight)
          : 0;

        if (!beforeRatio || !afterRatio) {
          el.classList.add('pj-compare--ratio-landscape');
          return;
        }

        const beforePortrait = beforeRatio < 0.92;
        const afterPortrait = afterRatio < 0.92;

        if (beforePortrait && afterPortrait) {
          el.classList.add('pj-compare--ratio-portrait');
          return;
        }

        if (beforePortrait || afterPortrait) {
          el.classList.add('pj-compare--ratio-mixed');
          return;
        }

        el.classList.add('pj-compare--ratio-landscape');
      };

      if (before) before.addEventListener('load', applyCompareRatioClass);
      if (after) after.addEventListener('load', applyCompareRatioClass);

      // Photo set navigation (multi-photo before/after).
      let gallery = null;
      try {
        gallery = sourcesScript ? JSON.parse(sourcesScript.textContent || '{}') : null;
      } catch (err) {
        gallery = null;
      }

      const beforeList = Array.isArray(gallery && gallery.before) ? gallery.before : [];
      const afterList = Array.isArray(gallery && gallery.after) ? gallery.after : [];
      const totalSets = Math.max(beforeList.length, afterList.length);

      const resolveItem = (list, idx) => {
        if (!Array.isArray(list) || list.length === 0) return null;
        if (idx >= 0 && idx < list.length) return list[idx];
        return list[list.length - 1] || null;
      };

      const applyItem = (imgEl, item) => {
        if (!imgEl || !item || !item.src) return;
        imgEl.src = item.src;
        imgEl.srcset = item.srcset || '';
        imgEl.alt = item.alt || imgEl.alt || '';
      };

      if (before && after && totalSets > 1 && prevBtn && nextBtn && pager) {
        // Ensure set index 0 matches the server-rendered markup (thumbnails/srcset),
        // so we don't force a full-size media swap on init.
        if (beforeList.length > 0) {
          beforeList[0] = {
            ...beforeList[0],
            src: before.getAttribute('src') || beforeList[0].src,
            srcset: before.getAttribute('srcset') || beforeList[0].srcset || '',
            alt: before.getAttribute('alt') || beforeList[0].alt || '',
          };
        }
        if (afterList.length > 0) {
          afterList[0] = {
            ...afterList[0],
            src: after.getAttribute('src') || afterList[0].src,
            srcset: after.getAttribute('srcset') || afterList[0].srcset || '',
            alt: after.getAttribute('alt') || afterList[0].alt || '',
          };
        }

        el.dataset.hasGallery = '1';
        let idx = 0;

        const update = () => {
          const b = resolveItem(beforeList, idx);
          const a = resolveItem(afterList, idx);

          const beforeMedia = before.closest('[data-skeleton]');
          const afterMedia = after.closest('[data-skeleton]');

          applyItem(before, b);
          applyItem(after, a);

          if (b) resetSkeleton(beforeMedia, before);
          if (a) resetSkeleton(afterMedia, after);

          pager.textContent = `${idx + 1} / ${totalSets}`;
          window.requestAnimationFrame(applyCompareRatioClass);
        };

        const move = (delta) => {
          idx = (idx + delta + totalSets) % totalSets;
          update();
        };

        prevBtn.addEventListener('click', () => move(-1));
        nextBtn.addEventListener('click', () => move(1));
        el.addEventListener('keydown', (e) => {
          if (e.target && e.target.matches && e.target.matches('input[type="range"]')) return;
          if (e.key === 'ArrowLeft') move(-1);
          if (e.key === 'ArrowRight') move(1);
        });

        update();
      }

      // Before/After slider (desktop pointer devices).
      if (!before || !after || !range || !canSlider) return;

      el.classList.add('pj-compare--slider');

      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

      const setPos = (value) => {
        const v = Math.max(0, Math.min(100, Number(value)));
        el.style.setProperty('--pos', `${v}%`);
      };

      setPos(range.value || 50);
      applyCompareRatioClass();
      range.addEventListener('input', () => setPos(range.value));

      const setFromClientX = (clientX) => {
        const rect = el.getBoundingClientRect();
        if (!rect.width) return;
        const pct = ((clientX - rect.left) / rect.width) * 100;
        const v = Math.max(0, Math.min(100, Math.round(pct)));
        range.value = String(v);
        setPos(v);
      };

      let dragging = false;
      el.addEventListener('pointerdown', (e) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        if (e.isPrimary === false) return;
        if (e.target && e.target.closest && e.target.closest('[data-compare-prev],[data-compare-next]')) return;
        e.preventDefault(); // prevent native image dragging/selection and keep dragging consistent
        dragging = true;
        try { el.setPointerCapture(e.pointerId); } catch (err) {}
        setFromClientX(e.clientX);
      });
      el.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        setFromClientX(e.clientX);
      });
      const stopDragging = () => { dragging = false; };
      el.addEventListener('pointerup', stopDragging);
      el.addEventListener('pointercancel', stopDragging);

      // One-time interactive hint: nudge + pulse until the user interacts.
      if (!compareHintShown && !isCompareHintDismissed()) {
        compareHintShown = true;
        el.classList.add('pj-compare--hint');

        let hintInterval = 0;
        let hintBusy = false;

        const dismiss = () => {
          if (!el.classList.contains('pj-compare--hint')) return;
          el.classList.remove('pj-compare--hint');
          if (hintInterval) window.clearInterval(hintInterval);
          dismissCompareHintForever();
        };

        el.addEventListener('pointerdown', (e) => {
          // Don't treat photo navigation as "using the slider".
          if (e.target && e.target.closest && e.target.closest('[data-compare-prev],[data-compare-next]')) return;
          dismiss();
        }, { once: true, capture: true });
        range.addEventListener('input', dismiss, { once: true });
        range.addEventListener('keydown', dismiss, { once: true });

        if (!prefersReducedMotion) {
          const remind = () => {
            if (!el.classList.contains('pj-compare--hint')) return;
            if (hintBusy) return;
            hintBusy = true;

            // Restart the knob pulse animation.
            el.classList.remove('pj-compare--remind');
            // eslint-disable-next-line no-unused-expressions
            el.offsetWidth; // force reflow to restart CSS animation
            el.classList.add('pj-compare--remind');
            window.setTimeout(() => el.classList.remove('pj-compare--remind'), 1300);

            const base = Math.max(0, Math.min(100, Number(range.value || 50)));
            const seq = [
              Math.max(0, Math.min(100, base + 12)),
              Math.max(0, Math.min(100, base - 12)),
              base,
            ];

            const step = (i) => {
              if (!el.classList.contains('pj-compare--hint')) return;
              const v = seq[i];
              range.value = String(v);
              setPos(v);
              if (i + 1 < seq.length) {
                window.setTimeout(() => step(i + 1), 420);
              } else {
                hintBusy = false;
              }
            };

            step(0);
          };

          // Initial hint, then repeat every 5 seconds until first use.
          window.setTimeout(remind, 650);
          hintInterval = window.setInterval(remind, 5000);
        }
      }
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
