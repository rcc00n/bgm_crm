/* static/js/project-journal-feed.js
   Lightweight enhancements:
   - Image skeleton fade-in
   - Before/After slider (desktop pointer devices)
   - Desktop album modal for statement photos
   - "Load more" feed pagination (progressive enhancement) */

(() => {
  const COMPARE_HINT_KEY = 'pj_compare_hint_dismissed_v1';
  let compareHintShown = false;
  let albumModalApi = null;

  const isDesktopLayout = () => window.matchMedia('(min-width: 960px)').matches;

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
    const canSlider = window.matchMedia('(pointer: fine)').matches && isDesktopLayout();
    const compares = root.querySelectorAll('[data-compare]');
    compares.forEach((el) => {
      if (el.dataset.compareInit === '1') return;
      el.dataset.compareInit = '1';

      const card = el.closest('[data-feed-card]');
      const desktopMode = card ? (card.dataset.displayMode || 'slider') : 'slider';

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

      const recoverBrokenSrcset = (imgEl) => {
        if (!imgEl) return false;
        const src = imgEl.getAttribute('src') || '';
        const srcset = imgEl.getAttribute('srcset') || '';
        if (!src || !srcset) return false;
        imgEl.setAttribute('srcset', '');
        imgEl.src = src;
        return true;
      };

      const ensureImageSourceGuard = (imgEl) => {
        if (!imgEl || imgEl.dataset.compareGuardInit === '1') return;
        imgEl.dataset.compareGuardInit = '1';

        const maybeRecover = () => {
          const renderable = imgEl.naturalWidth > 0 && imgEl.naturalHeight > 0;
          if (renderable) return;
          if (imgEl.dataset.compareSrcsetRecovered === '1') return;
          if (!imgEl.getAttribute('srcset')) return;
          imgEl.dataset.compareSrcsetRecovered = '1';
          recoverBrokenSrcset(imgEl);
        };

        // If decode already failed before JS booted, recover immediately.
        if (imgEl.complete && (imgEl.naturalWidth === 0 || imgEl.naturalHeight === 0)) {
          maybeRecover();
        }

        imgEl.addEventListener('error', maybeRecover);
        imgEl.addEventListener('load', () => {
          if (imgEl.naturalWidth > 0 && imgEl.naturalHeight > 0) {
            imgEl.dataset.compareSrcsetRecovered = '0';
          }
        });
      };

      ensureImageSourceGuard(before);
      ensureImageSourceGuard(after);

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
        imgEl.dataset.compareSrcsetRecovered = '0';
        imgEl.src = item.src;
        imgEl.srcset = item.srcset || '';
        imgEl.alt = item.alt || imgEl.alt || '';
        ensureImageSourceGuard(imgEl);
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
      if (desktopMode === 'album') return;

      el.classList.add('pj-compare--slider');

      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      let stopHint = () => {};

      const setPos = (value) => {
        const v = Math.max(0, Math.min(100, Number(value)));
        el.style.setProperty('--pos', `${v}%`);
      };

      setPos(range.value || 50);
      applyCompareRatioClass();
      range.addEventListener('input', () => {
        setPos(range.value);
        stopHint();
      });
      range.addEventListener('change', stopHint);
      range.addEventListener('keydown', (e) => {
        if (
          e.key === 'ArrowLeft'
          || e.key === 'ArrowRight'
          || e.key === 'Home'
          || e.key === 'End'
          || e.key === 'PageUp'
          || e.key === 'PageDown'
        ) {
          stopHint();
        }
      });

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
        stopHint();
        e.preventDefault(); // prevent native image dragging/selection and keep dragging consistent
        dragging = true;
        try { el.setPointerCapture(e.pointerId); } catch (err) {}
        setFromClientX(e.clientX);
      });
      el.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        stopHint();
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
        let hintInitialTimeout = 0;
        let hintPulseTimeout = 0;
        let hintStepTimeout = 0;

        const dismiss = () => {
          if (!el.classList.contains('pj-compare--hint') && !hintInterval && !hintInitialTimeout && !hintPulseTimeout && !hintStepTimeout) return;
          el.classList.remove('pj-compare--hint');
          el.classList.remove('pj-compare--remind');

          if (hintInterval) window.clearInterval(hintInterval);
          if (hintInitialTimeout) window.clearTimeout(hintInitialTimeout);
          if (hintPulseTimeout) window.clearTimeout(hintPulseTimeout);
          if (hintStepTimeout) window.clearTimeout(hintStepTimeout);

          hintInterval = 0;
          hintInitialTimeout = 0;
          hintPulseTimeout = 0;
          hintStepTimeout = 0;
          hintBusy = false;
          dismissCompareHintForever();
        };
        stopHint = dismiss;

        el.addEventListener('pointerdown', (e) => {
          // Don't treat photo navigation as "using the slider".
          if (e.target && e.target.closest && e.target.closest('[data-compare-prev],[data-compare-next]')) return;
          dismiss();
        }, { capture: true });
        range.addEventListener('input', dismiss);
        range.addEventListener('keydown', dismiss);
        range.addEventListener('change', dismiss);

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
            hintPulseTimeout = window.setTimeout(() => {
              el.classList.remove('pj-compare--remind');
              hintPulseTimeout = 0;
            }, 1300);

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
                hintStepTimeout = window.setTimeout(() => {
                  hintStepTimeout = 0;
                  step(i + 1);
                }, 420);
              } else {
                hintBusy = false;
              }
            };

            step(0);
          };

          // Initial hint, then repeat every 5 seconds until first use.
          hintInitialTimeout = window.setTimeout(() => {
            hintInitialTimeout = 0;
            remind();
          }, 650);
          hintInterval = window.setInterval(remind, 5000);
        }
      }
    });
  };

  const albumStageLabel = (stage) => {
    if (stage === 'before') return 'Before';
    if (stage === 'process') return 'Process';
    if (stage === 'after') return 'After';
    return 'Build photo';
  };

  const initMobileReel = (root = document) => {
    const reels = root.querySelectorAll('[data-mobile-reel]');
    reels.forEach((reel) => {
      if (reel.dataset.reelInit === '1') return;
      reel.dataset.reelInit = '1';

      const compare = reel.closest('[data-compare]');
      const script = compare ? compare.querySelector('[data-compare-sources]') : null;
      let sources = null;
      try {
        sources = script ? JSON.parse(script.textContent || '{}') : null;
      } catch (err) {
        sources = null;
      }

      const toItems = (list, stage) => {
        if (!Array.isArray(list)) return [];
        return list
          .filter((item) => item && item.src)
          .map((item) => ({
            src: item.src,
            srcset: item.srcset || '',
            alt: item.alt || '',
            stage,
          }));
      };

      const beforeList = toItems(sources && sources.before, 'before');
      const processList = toItems(sources && sources.process, 'process');
      const afterList = toItems(sources && sources.after, 'after');
      const items = [...beforeList, ...processList, ...afterList];

      if (!items.length) {
        reel.hidden = true;
        return;
      }

      const img = reel.querySelector('[data-mobile-image]');
      const labelEl = reel.querySelector('[data-mobile-label]');
      const pager = reel.querySelector('[data-mobile-pager]');
      const prevBtn = reel.querySelector('[data-mobile-prev]');
      const nextBtn = reel.querySelector('[data-mobile-next]');
      const media = reel.querySelector('[data-mobile-media]');

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

      let idx = items.findIndex((item) => item.stage === 'after');
      if (idx < 0) idx = 0;

      const update = () => {
        const item = items[idx] || items[0];
        if (!item || !img) return;
        img.src = item.src;
        img.srcset = item.srcset || '';
        const label = albumStageLabel(item.stage);
        img.alt = item.alt || img.alt || `${label} photo`;
        if (labelEl) labelEl.textContent = label;
        if (pager) pager.textContent = `${idx + 1} / ${items.length}`;
        resetSkeleton(media, img);

        const canNavigate = items.length > 1;
        if (prevBtn) prevBtn.style.display = canNavigate ? '' : 'none';
        if (nextBtn) nextBtn.style.display = canNavigate ? '' : 'none';
        if (pager) pager.style.display = canNavigate ? '' : 'none';
      };

      const move = (delta) => {
        idx = (idx + delta + items.length) % items.length;
        update();
      };

      if (prevBtn) prevBtn.addEventListener('click', () => move(-1));
      if (nextBtn) nextBtn.addEventListener('click', () => move(1));

      update();
    });
  };

  const getAlbumModalApi = () => {
    if (albumModalApi) return albumModalApi;

    const modal = document.createElement('div');
    modal.className = 'pj-album-modal';
    modal.setAttribute('data-album-modal', '1');
    modal.setAttribute('hidden', 'hidden');
    modal.innerHTML = `
      <div class="pj-album-modal__dialog" role="dialog" aria-modal="true" aria-label="Build photo album">
        <header class="pj-album-modal__top">
          <h2 class="pj-album-modal__title" data-album-title>Build album</h2>
          <button class="pj-album-modal__close" type="button" data-album-close aria-label="Close">×</button>
        </header>
        <div class="pj-album-modal__viewer">
          <button class="pj-album-modal__nav pj-album-modal__nav--prev" type="button" data-album-prev aria-label="Previous photo">‹</button>
          <img class="pj-album-modal__image" data-album-image alt="">
          <button class="pj-album-modal__nav pj-album-modal__nav--next" type="button" data-album-next aria-label="Next photo">›</button>
        </div>
        <footer class="pj-album-modal__footer">
          <div>
            <p class="pj-album-modal__stage" data-album-stage>Build photo</p>
            <p class="pj-album-modal__caption" data-album-caption></p>
          </div>
          <div class="pj-album-modal__count" data-album-count>1 / 1</div>
        </footer>
      </div>
    `;
    document.body.appendChild(modal);

    const titleEl = modal.querySelector('[data-album-title]');
    const imageEl = modal.querySelector('[data-album-image]');
    const stageEl = modal.querySelector('[data-album-stage]');
    const captionEl = modal.querySelector('[data-album-caption]');
    const countEl = modal.querySelector('[data-album-count]');
    const prevBtn = modal.querySelector('[data-album-prev]');
    const nextBtn = modal.querySelector('[data-album-next]');
    const closeBtn = modal.querySelector('[data-album-close]');

    const state = {
      items: [],
      idx: 0,
      title: 'Build album',
    };

    const isOpen = () => modal.classList.contains('is-open');

    const render = () => {
      if (!state.items.length || !imageEl) return;
      const item = state.items[state.idx] || state.items[0];
      if (!item || !item.src) return;

      if (titleEl) titleEl.textContent = state.title || 'Build album';
      imageEl.src = item.src;
      imageEl.srcset = item.srcset || '';
      imageEl.alt = item.alt || state.title || 'Build photo';
      if (stageEl) stageEl.textContent = albumStageLabel(item.stage);
      if (captionEl) captionEl.textContent = item.alt || state.title || '';
      if (countEl) countEl.textContent = `${state.idx + 1} / ${state.items.length}`;

      const canNavigate = state.items.length > 1;
      if (prevBtn) prevBtn.style.display = canNavigate ? '' : 'none';
      if (nextBtn) nextBtn.style.display = canNavigate ? '' : 'none';
    };

    const move = (delta) => {
      if (!state.items.length) return;
      state.idx = (state.idx + delta + state.items.length) % state.items.length;
      render();
    };

    const close = () => {
      modal.classList.remove('is-open');
      modal.setAttribute('hidden', 'hidden');
      document.body.classList.remove('pj-album-open');
    };

    const open = (items, startIdx = 0, title = 'Build album') => {
      if (!Array.isArray(items)) return;
      const prepared = items.filter((item) => item && item.src);
      if (!prepared.length) return;

      state.items = prepared;
      state.idx = Math.max(0, Math.min(prepared.length - 1, Number(startIdx) || 0));
      state.title = title || 'Build album';
      render();
      modal.removeAttribute('hidden');
      modal.classList.add('is-open');
      document.body.classList.add('pj-album-open');
    };

    if (prevBtn) prevBtn.addEventListener('click', () => move(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => move(1));
    if (closeBtn) closeBtn.addEventListener('click', close);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) close();
    });
    document.addEventListener('keydown', (e) => {
      if (!isOpen()) return;
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowLeft') move(-1);
      if (e.key === 'ArrowRight') move(1);
    });

    albumModalApi = { open, close };
    return albumModalApi;
  };

  const initAlbum = (root = document) => {
    const cards = root.querySelectorAll('[data-album-card]');
    cards.forEach((card) => {
      if (card.dataset.albumInit === '1') return;
      card.dataset.albumInit = '1';

      const feedCard = card.closest('[data-feed-card]');
      const mode = feedCard ? (feedCard.dataset.displayMode || 'slider') : 'slider';
      if (mode !== 'album') return;

      let sources = null;
      const script = card.querySelector('[data-album-sources]');
      try {
        sources = script ? JSON.parse(script.textContent || '{}') : null;
      } catch (err) {
        sources = null;
      }

      const toItems = (list, stage) => {
        if (!Array.isArray(list)) return [];
        return list
          .filter((item) => item && item.src)
          .map((item) => ({
            src: item.src,
            srcset: item.srcset || '',
            alt: item.alt || '',
            stage,
          }));
      };

      const items = [
        ...toItems(sources && sources.before, 'before'),
        ...toItems(sources && sources.process, 'process'),
        ...toItems(sources && sources.after, 'after'),
      ];

      if (!items.length) {
        card.hidden = true;
        return;
      }

      const countEl = card.querySelector('[data-album-count]');
      if (countEl) countEl.textContent = `${items.length} photos`;

      const openBtn = card.querySelector('[data-album-open]');
      if (!openBtn) return;

      let startIdx = items.findIndex((item) => item.stage === 'after');
      if (startIdx < 0) startIdx = 0;

      const titleEl = card.querySelector('.pj-album-teaser__title');
      const albumTitle = titleEl ? (titleEl.textContent || '').trim() : 'Build album';
      const modalApi = getAlbumModalApi();

      openBtn.addEventListener('click', () => {
        if (!isDesktopLayout()) return;
        modalApi.open(items, startIdx, albumTitle || 'Build album');
      });
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
      initMobileReel(feed);
      initAlbum(feed);
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

  const initContactFab = () => {
    const fab = document.getElementById('contactFab');
    const modal = document.getElementById('contactModal');
    if (!fab || !modal) return;
    if (fab.dataset.contactInit === '1') return;
    fab.dataset.contactInit = '1';

    const closeBtn = modal.querySelector('.contact-close');
    if (!closeBtn) return;

    const copyLabel = 'Copy';
    const copySuccess = 'Copied';
    const copyFailed = 'Copy failed';
    let lastFocus = null;

    const getFocusable = () =>
      modal.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])');

    const closeModal = () => {
      if (!modal.hasAttribute('open')) return;
      modal.removeAttribute('open');
      fab.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('modal-open');
      document.removeEventListener('keydown', onKey, true);
      if (lastFocus && typeof lastFocus.focus === 'function') {
        try { lastFocus.focus(); } catch (_) {}
      }
    };

    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
        return;
      }
      if (e.key !== 'Tab') return;

      const list = Array.from(getFocusable()).filter((el) => el.offsetParent !== null);
      if (!list.length) return;
      const first = list[0];
      const last = list[list.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    const openModal = () => {
      if (modal.hasAttribute('open')) return;
      lastFocus = document.activeElement;
      modal.setAttribute('open', '');
      fab.setAttribute('aria-expanded', 'true');
      document.body.classList.add('modal-open');
      window.setTimeout(() => closeBtn.focus(), 0);
      document.addEventListener('keydown', onKey, true);
    };

    fab.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });

    modal.querySelectorAll('[data-copy]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const value = btn.dataset.copy || '';
        if (!value) return;
        const original = btn.textContent || copyLabel;

        try {
          await navigator.clipboard.writeText(value);
          btn.textContent = copySuccess;
        } catch (err) {
          btn.textContent = copyFailed;
        }

        window.setTimeout(() => {
          btn.textContent = original;
        }, 1200);
      });
    });
  };

  const boot = () => {
    initSkeleton();
    initCompare();
    initMobileReel();
    initAlbum();
    initLoadMore();
    initContactFab();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
