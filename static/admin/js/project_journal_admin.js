/* static/admin/js/project_journal_admin.js
   Admin enhancements for ProjectJournalEntry:
   - Bulk drag&drop upload into Before/After inlines
   - Drag&drop sorting that updates sort_order
   - Live preview of the public feed card */

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const waitFrame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));

  const getInlineGroups = () => $$('.inline-group');

  const findInlineGroup = (needle) => {
    const want = (needle || '').toLowerCase();
    for (const group of getInlineGroups()) {
      const h2 = $('h2', group);
      const title = (h2 ? h2.textContent : '').toLowerCase();
      if (title.includes(want)) return group;
    }
    return null;
  };

  const getInlineTbody = (group) => $('table tbody', group);

  const getFormRows = (group) => {
    const tbody = getInlineTbody(group);
    if (!tbody) return [];
    return $$('tr.form-row', tbody).filter((row) => !row.classList.contains('empty-form'));
  };

  const updateSortOrders = (group) => {
    const rows = getFormRows(group);
    rows.forEach((row, idx) => {
      const input = $('input[id$="-sort_order"]', row);
      if (input) input.value = String(idx * 10);
    });
  };

  const makeSortable = (group) => {
    const tbody = getInlineTbody(group);
    if (!tbody) return;

    let dragging = null;

    const refresh = () => {
      getFormRows(group).forEach((row) => {
        row.classList.add('pj-sort-row');
        row.setAttribute('draggable', 'true');
      });
    };

    refresh();

    tbody.addEventListener('dragstart', (e) => {
      const row = e.target && e.target.closest ? e.target.closest('tr.form-row') : null;
      if (!row || row.classList.contains('empty-form')) return;
      dragging = row;
      row.classList.add('pj-sort-row--dragging');
      e.dataTransfer.effectAllowed = 'move';
      try {
        e.dataTransfer.setData('text/plain', 'pj-sort');
      } catch {
        /* ignore */
      }
    });

    tbody.addEventListener('dragend', () => {
      if (!dragging) return;
      dragging.classList.remove('pj-sort-row--dragging');
      dragging = null;
      updateSortOrders(group);
    });

    tbody.addEventListener('dragover', (e) => {
      if (!dragging) return;
      e.preventDefault();
      const row = e.target && e.target.closest ? e.target.closest('tr.form-row') : null;
      if (!row || row === dragging || row.classList.contains('empty-form')) return;

      const rect = row.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      if (before) {
        tbody.insertBefore(dragging, row);
      } else {
        tbody.insertBefore(dragging, row.nextSibling);
      }
    });

    // When new rows are added by the default "Add another" link, re-bind.
    const mo = new MutationObserver(() => refresh());
    mo.observe(tbody, { childList: true });
  };

  const setFileInput = (input, file) => {
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    } catch {
      return false;
    }
  };

  const updateRowPreviewFromFile = (row, file) => {
    const cell = $('td.field-image_preview', row);
    if (!cell) return;
    const url = URL.createObjectURL(file);
    cell.innerHTML = `<img src="${url}" alt="" style="height:64px;width:96px;object-fit:cover;border-radius:10px;border:1px solid #e5e7eb;">`;
  };

  const addInlineRow = async (group) => {
    const addLink = $('.add-row a', group);
    if (!addLink) return false;
    addLink.click();
    await waitFrame();
    await waitFrame();
    return true;
  };

  const nextEmptyFileInput = (group) => {
    const rows = getFormRows(group);
    for (const row of rows) {
      // Prefer empty extra forms, not existing ("has_original") rows.
      if (row.classList.contains('has_original')) continue;
      const input = $('input[type="file"]', row);
      if (input && (!input.files || input.files.length === 0)) return input;
    }
    // Fallback: allow using any empty file input.
    for (const row of rows) {
      const input = $('input[type="file"]', row);
      if (input && (!input.files || input.files.length === 0)) return input;
    }
    return null;
  };

  const bindInlineFilePreview = (group) => {
    const tbody = getInlineTbody(group);
    if (!tbody) return;
    tbody.addEventListener('change', (e) => {
      const input = e.target;
      if (!(input instanceof HTMLInputElement) || input.type !== 'file') return;
      if (!input.files || !input.files.length) return;
      const row = input.closest('tr.form-row');
      if (!row) return;
      updateRowPreviewFromFile(row, input.files[0]);
      queuePreviewUpdate();
    });
  };

  const mountDropzone = (group, kindLabel) => {
    const anchor = $('table', group);
    if (!anchor) return;

    const dz = document.createElement('div');
    dz.className = 'pj-dropzone';
    dz.innerHTML = `<strong>Drop ${kindLabel} photos here</strong><span>or click to pick</span>`;
    anchor.parentNode.insertBefore(dz, anchor);

    const handleFiles = async (files) => {
      const list = Array.from(files || []).filter((f) => f && f.type && f.type.startsWith('image/'));
      if (!list.length) return;

      for (const file of list) {
        let input = nextEmptyFileInput(group);
        if (!input) {
          const added = await addInlineRow(group);
          if (!added) break;
          input = nextEmptyFileInput(group);
        }
        if (!input) break;
        const row = input.closest('tr.form-row');
        setFileInput(input, file);
        if (row) updateRowPreviewFromFile(row, file);
      }

      updateSortOrders(group);
      queuePreviewUpdate();
    };

    dz.addEventListener('click', async () => {
      let input = nextEmptyFileInput(group);
      if (!input) {
        const added = await addInlineRow(group);
        if (added) input = nextEmptyFileInput(group);
      }
      if (input) input.click();
    });

    dz.addEventListener('dragover', (e) => {
      e.preventDefault();
      dz.classList.add('is-over');
    });
    dz.addEventListener('dragleave', () => dz.classList.remove('is-over'));
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('is-over');
      handleFiles(e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files : []);
    });
  };

  // ---- Live preview ----
  const previewRoot = $('[data-pj-preview]');
  const previewEls = previewRoot ? {
    beforeImg: $('[data-preview-image="before"]', previewRoot),
    afterImg: $('[data-preview-image="after"]', previewRoot),
    title: $('[data-preview-field="title"]', previewRoot),
    highlight: $('[data-preview-field="highlight"]', previewRoot),
    excerpt: $('[data-preview-field="excerpt"]', previewRoot),
    chips: $('[data-preview-field="chips"]', previewRoot),
    ctas: $('[data-preview-field="ctas"]', previewRoot),
  } : null;

  const safeText = (v) => (v == null ? '' : String(v)).trim();

  const previewSetText = (el, text, fallback = '') => {
    if (!el) return;
    const value = safeText(text) || fallback;
    el.textContent = value;
  };

  const buildChips = () => {
    if (!previewEls || !previewEls.chips) return;
    previewEls.chips.innerHTML = '';

    const cats = $('#id_categories');
    if (cats && cats instanceof HTMLSelectElement) {
      const selected = Array.from(cats.selectedOptions || []).map((o) => safeText(o.textContent)).filter(Boolean);
      selected.slice(0, 6).forEach((name) => {
        const chip = document.createElement('span');
        chip.className = 'pj-live-preview__chip';
        chip.textContent = name;
        previewEls.chips.appendChild(chip);
      });
    }

    const tagsRaw = safeText($('#id_tags') ? $('#id_tags').value : '');
    const tags = tagsRaw ? tagsRaw.split(',').map((t) => t.trim()).filter(Boolean) : [];
    tags.slice(0, 6).forEach((tag) => {
      const chip = document.createElement('span');
      chip.className = 'pj-live-preview__chip';
      chip.textContent = `#${tag}`;
      previewEls.chips.appendChild(chip);
    });
  };

  const buildCTAs = () => {
    if (!previewEls || !previewEls.ctas) return;
    previewEls.ctas.innerHTML = '';

    const pairs = [
      { label: $('#id_cta_primary_label'), url: $('#id_cta_primary_url'), cls: 'pj-live-preview__btn--primary' },
      { label: $('#id_cta_secondary_label'), url: $('#id_cta_secondary_url'), cls: '' },
      { label: $('#id_cta_tertiary_label'), url: $('#id_cta_tertiary_url'), cls: '' },
    ];

    pairs.forEach((pair) => {
      const label = safeText(pair.label ? pair.label.value : '');
      const url = safeText(pair.url ? pair.url.value : '');
      if (!label || !url) return;
      const a = document.createElement('a');
      a.className = `pj-live-preview__btn ${pair.cls}`.trim();
      a.href = '#';
      a.textContent = label;
      previewEls.ctas.appendChild(a);
    });
  };

  const setPreviewImage = (kind, src) => {
    if (!previewEls) return;
    const img = kind === 'before' ? previewEls.beforeImg : previewEls.afterImg;
    if (!img) return;
    if (src) {
      img.src = src;
      img.style.display = '';
    } else {
      img.removeAttribute('src');
      img.style.display = 'none';
    }
  };

  const findFirstInlineImageSrc = (group) => {
    if (!group) return '';

    // Prefer newly selected files.
    const fileInputs = $$('input[type="file"]', group);
    for (const input of fileInputs) {
      if (input.files && input.files.length) {
        return URL.createObjectURL(input.files[0]);
      }
    }

    // Fallback to existing previews rendered by the inline.
    const img = $('td.field-image_preview img', group);
    return img ? img.getAttribute('src') || '' : '';
  };

  const beforeGroup = findInlineGroup('before');
  const afterGroup = findInlineGroup('after');

  const updatePreview = () => {
    if (!previewEls) return;

    previewSetText(previewEls.title, $('#id_title') ? $('#id_title').value : '', 'Untitled build');

    const highlight = safeText($('#id_result_highlight') ? $('#id_result_highlight').value : '');
    if (previewEls.highlight) {
      previewEls.highlight.textContent = highlight;
      previewEls.highlight.style.display = highlight ? '' : 'none';
    }

    previewSetText(previewEls.excerpt, $('#id_excerpt') ? $('#id_excerpt').value : '', 'Short summary…');

    buildChips();
    buildCTAs();

    setPreviewImage('before', findFirstInlineImageSrc(beforeGroup));
    setPreviewImage('after', findFirstInlineImageSrc(afterGroup));
  };

  let previewQueued = false;
  const queuePreviewUpdate = () => {
    if (!previewEls) return;
    if (previewQueued) return;
    previewQueued = true;
    requestAnimationFrame(() => {
      previewQueued = false;
      updatePreview();
    });
  };

  const bindPreviewInputs = () => {
    const ids = [
      'id_title',
      'id_excerpt',
      'id_result_highlight',
      'id_tags',
      'id_categories',
      'id_cta_primary_label',
      'id_cta_primary_url',
      'id_cta_secondary_label',
      'id_cta_secondary_url',
      'id_cta_tertiary_label',
      'id_cta_tertiary_url',
    ];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', queuePreviewUpdate);
      el.addEventListener('change', queuePreviewUpdate);
    });
  };

  // ---- Boot ----
  const boot = () => {
    if (beforeGroup) {
      mountDropzone(beforeGroup, 'BEFORE');
      bindInlineFilePreview(beforeGroup);
      makeSortable(beforeGroup);
      updateSortOrders(beforeGroup);
    }
    if (afterGroup) {
      mountDropzone(afterGroup, 'AFTER');
      bindInlineFilePreview(afterGroup);
      makeSortable(afterGroup);
      updateSortOrders(afterGroup);
    }

    bindPreviewInputs();
    updatePreview();

    // Prevent preview CTA links from navigating inside admin.
    if (previewRoot) {
      previewRoot.addEventListener('click', (e) => {
        const a = e.target && e.target.closest ? e.target.closest('a') : null;
        if (a) e.preventDefault();
      });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
