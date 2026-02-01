from __future__ import annotations

import copy
import html
import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Tuple

from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.db import models
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils.timezone import now
from django.urls import reverse

from core.models import (
    AboutPageCopy,
    ClientPortalPageCopy,
    DealerStatusPageCopy,
    FinancingPageCopy,
    HomePageCopy,
    MerchPageCopy,
    PageFontSetting,
    ServicesPageCopy,
    StorePageCopy,
    Service,
)
from core.services.fonts import build_page_font_context
from core.services.page_layout import build_layout_styles, layout_config_for_model, normalize_layout_overrides
from core.services.page_sections import get_page_sections

TOKEN_START_RE = re.compile(r"\[\[\[PCF:([a-zA-Z0-9_]+)\]\]\]")
TOKEN_END_RE = re.compile(r"\[\[\[/PCF:([a-zA-Z0-9_]+)\]\]\]")
TOKEN_MARK_RE = re.compile(r"\[\[\[/?PCF:[^\]]+\]\]\]")


@dataclass
class PreviewConfig:
    template: str
    copy_key: str
    header_key: Optional[str] = None
    context_builder: Optional[Callable[[HttpRequest], Dict[str, Any]]] = None
    use_anonymous_user: bool = True


class PreviewCopy:
    def __init__(self, instance, text_fields):
        self._instance = instance
        self._text_fields = set(text_fields)

    def __getattr__(self, name: str):
        value = getattr(self._instance, name)
        if name in self._text_fields:
            if value is None or value == "":
                return ""
            safe_value = str(value)
            return f"[[[PCF:{name}]]]{safe_value}[[[/PCF:{name}]]]"
        return value

    def __str__(self) -> str:
        return str(self._instance)


class DummyDealerApplication:
    status = "pending"
    business_name = "Sample Dealer"
    created_at = now()
    reviewed_at = now()

    def get_status_display(self):
        return "Pending"

    def get_preferred_tier_display(self):
        return "Gold"


class DummyOrderSummary:
    def __init__(self):
        self.id = 12345

    def get_status_display(self):
        return "Processing"


def _match_token(text: str, index: int) -> Optional[Tuple[str, str, int]]:
    start_match = TOKEN_START_RE.match(text, index)
    if start_match:
        return ("start", start_match.group(1), start_match.end())
    end_match = TOKEN_END_RE.match(text, index)
    if end_match:
        return ("end", end_match.group(1), end_match.end())
    return None


def _wrap_tokens_outside_tags(html_text: str, field_types: Optional[Dict[str, str]] = None) -> str:
    out = []
    in_tag = False
    quote: Optional[str] = None
    stack = []
    i = 0
    length = len(html_text)

    while i < length:
        if not in_tag:
            token = _match_token(html_text, i)
            if token:
                kind, field, end = token
                if kind == "start":
                    field_attr = html.escape(field, quote=True)
                    copy_type = (field_types or {}).get(field, "plain")
                    copy_type_attr = html.escape(copy_type, quote=True)
                    out.append(
                        f'<span data-copy-field="{field_attr}" '
                        f'data-copy-type="{copy_type_attr}" '
                        f'contenteditable="true" spellcheck="false">'
                    )
                    stack.append(field)
                else:
                    if stack:
                        stack.pop()
                    out.append("</span>")
                i = end
                continue
        else:
            token = _match_token(html_text, i)
            if token:
                i = token[2]
                continue

        ch = html_text[i]
        out.append(ch)

        if in_tag:
            if quote:
                if ch == quote:
                    quote = None
            else:
                if ch in ("\"", "'"):
                    quote = ch
                elif ch == ">":
                    in_tag = False
        else:
            if ch == "<":
                in_tag = True
        i += 1

    while stack:
        out.append("</span>")
        stack.pop()

    return "".join(out)


def inject_preview_spans(html_text: str, field_types: Optional[Dict[str, str]] = None) -> str:
    parts = re.split(
        r"(<script\b.*?</script>|<style\b.*?</style>)",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    processed = []
    for part in parts:
        if part.lower().startswith("<script") or part.lower().startswith("<style"):
            processed.append(TOKEN_MARK_RE.sub("", part))
        else:
            processed.append(_wrap_tokens_outside_tags(part, field_types=field_types))
    return "".join(processed)


def inject_preview_helpers(
    html_text: str,
    base_href: str,
    layout_config: Optional[Dict[str, Any]] = None,
    layout_overrides: Optional[Dict[str, Any]] = None,
    save_url: Optional[str] = None,
    pagecopy_meta: Optional[Dict[str, Any]] = None,
    editor_config: Optional[Dict[str, Any]] = None,
    editor_upload_url: Optional[str] = None,
    editor_browse_url: Optional[str] = None,
) -> str:
    layout_config = layout_config or {}
    layout_overrides = normalize_layout_overrides(layout_overrides or {})
    layout_config_json = json.dumps(layout_config)
    layout_state_json = json.dumps(layout_overrides)
    save_url_json = json.dumps(save_url or "")
    pagecopy_meta_json = json.dumps(pagecopy_meta or {})
    editor_config_json = json.dumps(editor_config or {})
    editor_upload_url_json = json.dumps(editor_upload_url or "")
    editor_browse_url_json = json.dumps(editor_browse_url or "")

    style = """
<style>
  [data-copy-field] {
    outline: 1px dashed rgba(239, 68, 68, 0.45);
    outline-offset: 2px;
    cursor: text;
    transition: outline-color 0.2s ease, background 0.2s ease;
  }

  [data-copy-field]:hover {
    outline-color: rgba(239, 68, 68, 0.85);
  }

  [data-copy-field]:focus {
    outline: 2px solid rgba(37, 99, 235, 0.8);
    background: rgba(37, 99, 235, 0.08);
  }

  body.pagecopy-layout-mode [data-layout-key] {
    outline: 1px dashed rgba(14, 165, 233, 0.7);
    outline-offset: 2px;
    cursor: move;
    touch-action: none;
    user-select: none;
  }

  body.pagecopy-layout-mode [data-layout-key]:hover {
    outline-color: rgba(56, 189, 248, 0.95);
  }

  body a,
  body.pagecopy-preview-frame a {
    pointer-events: none;
    cursor: default;
  }

  .pagecopy-layout-handle {
    position: absolute;
    right: -6px;
    bottom: -6px;
    width: 14px;
    height: 14px;
    background: #38bdf8;
    border: 2px solid #0ea5e9;
    border-radius: 4px;
    box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.2);
    cursor: se-resize;
    display: none;
  }

  body.pagecopy-layout-mode [data-layout-key] .pagecopy-layout-handle {
    display: block;
  }

  body.pagecopy-section-mode .builder-section {
    outline: 1px dashed rgba(34, 197, 94, 0.55);
    outline-offset: -8px;
  }

  .pagecopy-section-handle {
    position: absolute;
    top: 12px;
    left: 12px;
    z-index: 6;
    width: 34px;
    height: 34px;
    border-radius: 999px;
    border: 1px solid rgba(15, 23, 42, 0.35);
    background: rgba(15, 23, 42, 0.82);
    color: #f8fafc;
    display: none;
    align-items: center;
    justify-content: center;
    cursor: grab;
    box-shadow: 0 10px 22px rgba(15, 23, 42, 0.35);
  }

  body.pagecopy-section-mode .pagecopy-section-handle {
    display: flex;
  }

  .pagecopy-section-handle svg {
    width: 18px;
    height: 18px;
    stroke: #f8fafc;
  }

  .pagecopy-section-placeholder {
    border: 2px dashed rgba(34, 197, 94, 0.45);
    border-radius: 12px;
    margin: 12px 0;
  }

  .pagecopy-section-dragging {
    opacity: 0.92;
    cursor: grabbing;
  }

  .pagecopy-section-dragging .pagecopy-section-handle {
    cursor: grabbing;
  }

  .pagecopy-inspector {
    position: fixed;
    top: 24px;
    left: 24px;
    width: 320px;
    background: #0f172a;
    color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 14px;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.45);
    z-index: 99999;
    font-size: 12px;
  }

  .pagecopy-inspector__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(15, 23, 42, 0.9);
    border-bottom: 1px solid rgba(148, 163, 184, 0.25);
    cursor: move;
    border-radius: 14px 14px 0 0;
  }

  .pagecopy-inspector__title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .pagecopy-inspector__close {
    background: transparent;
    border: 0;
    color: #e2e8f0;
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
  }

  .pagecopy-inspector__body {
    padding: 10px 12px 14px;
    display: grid;
    gap: 10px;
  }

  .pagecopy-inspector__group {
    display: grid;
    gap: 6px;
  }

  .pagecopy-inspector__group-title {
    font-size: 11px;
    color: #94a3b8;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .pagecopy-inspector label {
    font-size: 11px;
    color: #cbd5f5;
    display: block;
    margin-bottom: 4px;
  }

  .pagecopy-inspector input,
  .pagecopy-inspector textarea,
  .pagecopy-inspector select {
    width: 100%;
    background: rgba(15, 23, 42, 0.8);
    color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 12px;
  }

  .pagecopy-inspector textarea {
    min-height: 72px;
    resize: vertical;
  }

  .pagecopy-inspector__row {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }

  .pagecopy-inspector__actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  .pagecopy-inspector__button {
    background: #2563eb;
    border: 0;
    color: #fff;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
  }

  .pagecopy-inspector__button--ghost {
    background: transparent;
    border: 1px solid rgba(148, 163, 184, 0.4);
    color: #e2e8f0;
  }

  .pagecopy-inspector__meta {
    font-size: 11px;
    color: #94a3b8;
  }
</style>
"""

    script = """
<script>
  (function() {
    document.body.classList.add('pagecopy-preview-frame');

    const fields = Array.from(document.querySelectorAll('[data-copy-field]'));
    const saveUrl = __PAGECOPY_SAVE_URL__;
    const pagecopyMeta = __PAGECOPY_META__;
    const editorConfig = __PAGECOPY_EDITOR_CONFIG__;
    const editorUploadUrl = __PAGECOPY_EDITOR_UPLOAD_URL__;
    const editorBrowseUrl = __PAGECOPY_EDITOR_BROWSE_URL__;
    const canAutosave = !!(
      saveUrl && pagecopyMeta && pagecopyMeta.model && pagecopyMeta.object_id
    );

    const byField = {};
    const editors = new Map();
    const saveTimers = new Map();
    const lastValues = new Map();
    const savedValues = new Map();
    let suppressEditorChange = false;
    let pendingSaves = 0;
    let hasError = false;

    const notifyAutosave = (state, detail) => {
      if (window.parent) {
        window.parent.postMessage({ type: 'pagecopy:autosave', state, detail }, '*');
      }
    };

    const getCookie = (name) => {
      const value = `; ${document.cookie}`;
      const parts = value.split(`; ${name}=`);
      if (parts.length === 2) {
        return decodeURIComponent(parts.pop().split(';').shift());
      }
      return '';
    };

    const readPlainValue = (node) => {
      const htmlValue = (node.innerHTML || '').replace(/\r/g, '');
      const normalized = htmlValue
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/(div|p|li|h[1-6])>/gi, '\n')
        .replace(/<(div|p|li|h[1-6])[^>]*>/gi, '');
      const temp = document.createElement('div');
      temp.innerHTML = normalized;
      let text = temp.textContent || '';
      text = text.replace(/\u00a0/g, ' ');
      return text;
    };

    const readRichValue = (node) => {
      let htmlValue = node.innerHTML || '';
      htmlValue = htmlValue.replace(/\r/g, '');
      return htmlValue;
    };

    const setNodeValue = (node, value) => {
      const htmlValue = value == null ? '' : String(value);
      const copyType = node.dataset.copyType || 'plain';
      const editor = editors.get(node);
      if (editor) {
        suppressEditorChange = true;
        editor.setData(htmlValue || '', {
          callback: () => {
            suppressEditorChange = false;
          }
        });
        return;
      }
      if (copyType === 'rich') {
        node.innerHTML = htmlValue;
        return;
      }
      if (htmlValue.indexOf('<') === -1 && htmlValue.indexOf('&') === -1 && htmlValue.includes('\n')) {
        const lines = htmlValue.split(/\n/);
        node.textContent = '';
        lines.forEach((line, idx) => {
          if (idx) node.appendChild(document.createElement('br'));
          node.appendChild(document.createTextNode(line));
        });
      } else {
        node.textContent = htmlValue;
      }
    };

    const updateAutosaveState = () => {
      if (!canAutosave) return;
      if (pendingSaves > 0) {
        notifyAutosave('saving');
      } else if (hasError) {
        notifyAutosave('error');
      } else {
        notifyAutosave('saved');
      }
    };

    const commitSave = (field, value) => {
      if (!canAutosave) return;
      if (lastValues.get(field) !== value) return;
      if (savedValues.get(field) === value) {
        updateAutosaveState();
        return;
      }
      pendingSaves += 1;
      updateAutosaveState();
      const payload = {
        model: pagecopyMeta.model,
        object_id: pagecopyMeta.object_id,
        field,
        value,
      };
      fetch(saveUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(payload),
      })
        .then((response) => {
          if (!response.ok) throw new Error('Request failed');
          return response.json();
        })
        .then(() => {
          savedValues.set(field, value);
          hasError = false;
        })
        .catch(() => {
          hasError = true;
        })
        .finally(() => {
          pendingSaves = Math.max(0, pendingSaves - 1);
          updateAutosaveState();
        });
    };

    const scheduleSave = (field, value, immediate) => {
      if (!canAutosave) return;
      const textValue = value == null ? '' : String(value);
      lastValues.set(field, textValue);
      hasError = false;
      notifyAutosave('dirty', { field });
      const existing = saveTimers.get(field);
      if (existing) clearTimeout(existing);
      if (immediate) {
        commitSave(field, textValue);
        return;
      }
      const timer = setTimeout(() => commitSave(field, textValue), 500);
      saveTimers.set(field, timer);
    };

    const syncFieldValue = (field, value, sourceNode) => {
      (byField[field] || []).forEach(item => {
        if (item !== sourceNode) {
          setNodeValue(item, value);
        }
      });
    };

    const handleFieldChange = (field, value, sourceNode) => {
      syncFieldValue(field, value, sourceNode);
      if (window.parent) {
        window.parent.postMessage({ type: 'pagecopy:update', field, value }, '*');
      }
      scheduleSave(field, value, false);
    };

    const handleFieldBlur = (field, value) => {
      if (window.parent) {
        window.parent.postMessage({ type: 'pagecopy:blur', field }, '*');
      }
      scheduleSave(field, value, true);
    };

    fields.forEach(node => {
      const field = node.dataset.copyField;
      if (!field) return;
      const copyType = node.dataset.copyType || 'plain';
      node.setAttribute('contenteditable', 'true');
      node.setAttribute('spellcheck', 'false');
      byField[field] = byField[field] || [];
      byField[field].push(node);

      node.addEventListener('input', () => {
        if (editors.has(node)) return;
        const value = copyType === 'rich' ? readRichValue(node) : readPlainValue(node);
        handleFieldChange(field, value, node);
      });

      node.addEventListener('blur', () => {
        if (editors.has(node)) return;
        const value = copyType === 'rich' ? readRichValue(node) : readPlainValue(node);
        handleFieldBlur(field, value);
      });
    });

    if (window.CKEDITOR && typeof CKEDITOR.inline === 'function') {
      CKEDITOR.disableAutoInline = true;
      const config = Object.assign({}, editorConfig || {});
      if (editorUploadUrl) {
        config.filebrowserUploadUrl = editorUploadUrl;
        config.filebrowserUploadMethod = 'form';
      }
      if (editorBrowseUrl) {
        config.filebrowserBrowseUrl = editorBrowseUrl;
      }
      fields.forEach(node => {
        const field = node.dataset.copyField;
        if (!field) return;
        const copyType = node.dataset.copyType || 'plain';
        if (copyType !== 'rich') return;
        const editor = CKEDITOR.inline(node, config);
        editors.set(node, editor);
        editor.on('change', () => {
          if (suppressEditorChange) return;
          handleFieldChange(field, editor.getData(), node);
        });
        editor.on('blur', () => {
          if (suppressEditorChange) return;
          handleFieldBlur(field, editor.getData());
        });
      });
    }

    window.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.type !== 'pagecopy:sync') return;
      const field = data.field;
      const value = data.value;
      (byField[field] || []).forEach(node => setNodeValue(node, value));
    });

    const layoutConfig = __LAYOUT_CONFIG__;
    const layoutState = __LAYOUT_STATE__;
    const sectionLayoutState = { desktop: {}, mobile: {} };
    const layoutNodes = new Map();
    let layoutModeActive = false;
    let sectionModeActive = false;
    let currentMode = 'desktop';
    const inspectorRegistry = new Map();
    let inspectorZIndex = 10000;

    const normalizeMode = (mode) => (mode === 'mobile' ? 'mobile' : 'desktop');
    const getModeState = () => {
      layoutState.desktop = layoutState.desktop || {};
      layoutState.mobile = layoutState.mobile || {};
      return layoutState[currentMode];
    };
    const getSectionModeState = () => {
      sectionLayoutState.desktop = sectionLayoutState.desktop || {};
      sectionLayoutState.mobile = sectionLayoutState.mobile || {};
      return sectionLayoutState[currentMode];
    };

    const parseNumber = (value) => {
      const num = Number(value);
      return Number.isFinite(num) ? Math.round(num) : 0;
    };
    const parseWidth = (value) => {
      const num = Number(value);
      if (!Number.isFinite(num)) return null;
      const width = Math.round(num);
      return width > 0 ? width : null;
    };

    const ensureHandle = (node) => {
      if (!node || node.querySelector('.pagecopy-layout-handle')) return;
      const computed = window.getComputedStyle(node);
      if (computed && computed.position === 'static') {
        node.style.position = 'relative';
      }
      const handle = document.createElement('span');
      handle.className = 'pagecopy-layout-handle';
      handle.setAttribute('aria-hidden', 'true');
      node.appendChild(handle);
    };

    const registerLayoutNodes = (key, nodes, meta) => {
      if (!nodes || !nodes.length) return;
      const kind = meta && meta.kind ? meta.kind : 'pagecopy';
      const sectionId = meta && meta.sectionId ? meta.sectionId : null;
      nodes.forEach(node => {
        node.dataset.layoutKey = key;
        node.dataset.layoutKind = kind;
        if (sectionId) {
          node.dataset.sectionId = sectionId;
        }
        ensureHandle(node);
      });
      layoutNodes.set(key, { nodes, kind, sectionId });
    };

    const applyLayout = () => {
      layoutNodes.forEach((meta, key) => {
        const state = meta.kind === 'section' ? getSectionModeState() : getModeState();
        const coords = state[key] || {};
        const x = Number(coords.x || 0);
        const y = Number(coords.y || 0);
        const w = coords.w ? Number(coords.w) : null;
        (meta.nodes || []).forEach(node => {
          if (meta.kind === 'section') {
            const isMobile = currentMode === 'mobile';
            const xVar = isMobile ? '--layout-x-mobile' : '--layout-x';
            const yVar = isMobile ? '--layout-y-mobile' : '--layout-y';
            const wVar = isMobile ? '--layout-w-mobile' : '--layout-w';
            node.style.setProperty(xVar, `${x}px`);
            node.style.setProperty(yVar, `${y}px`);
            if (w) {
              node.style.setProperty(wVar, `${w}px`);
            } else {
              node.style.removeProperty(wVar);
            }
            node.style.transform = '';
            node.style.width = '';
            return;
          }
          if (x || y) {
            node.style.transform = `translate3d(${x}px, ${y}px, 0)`;
          } else {
            node.style.transform = '';
          }
          if (w) {
            node.style.width = `${w}px`;
          } else {
            node.style.width = '';
          }
        });
      });
    };

    const humanizeLabel = (value) => {
      return String(value || '').replace(/_/g, ' ').trim();
    };

    const bringInspectorToFront = (panel) => {
      inspectorZIndex += 1;
      panel.style.zIndex = String(20000 + inspectorZIndex);
    };

    const makePanelDraggable = (panel, handle) => {
      if (!panel || !handle) return;
      let dragging = false;
      let startX = 0;
      let startY = 0;
      let startLeft = 0;
      let startTop = 0;

      const onPointerDown = (event) => {
        if (event.button && event.button !== 0) return;
        event.preventDefault();
        const rect = panel.getBoundingClientRect();
        startLeft = rect.left;
        startTop = rect.top;
        startX = event.clientX;
        startY = event.clientY;
        dragging = true;
        panel.style.left = `${startLeft}px`;
        panel.style.top = `${startTop}px`;
        panel.style.right = 'auto';
        panel.style.bottom = 'auto';
        bringInspectorToFront(panel);
        handle.setPointerCapture(event.pointerId);
      };

      const onPointerMove = (event) => {
        if (!dragging) return;
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        const nextLeft = Math.max(8, startLeft + dx);
        const nextTop = Math.max(8, startTop + dy);
        panel.style.left = `${nextLeft}px`;
        panel.style.top = `${nextTop}px`;
      };

      const onPointerUp = (event) => {
        if (!dragging) return;
        dragging = false;
        try {
          handle.releasePointerCapture(event.pointerId);
        } catch (err) {
          // ignore
        }
      };

      handle.addEventListener('pointerdown', onPointerDown);
      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', onPointerUp);
    };

    const getLayoutValuesForKey = (key, kind) => {
      const state = kind === 'section' ? getSectionModeState() : getModeState();
      const coords = state[key] || {};
      return {
        x: Number(coords.x || 0),
        y: Number(coords.y || 0),
        w: coords.w != null ? Number(coords.w) : '',
      };
    };

    const setLayoutValuesForKey = (key, kind, values) => {
      if (!key) return;
      const state = kind === 'section' ? getSectionModeState() : getModeState();
      const nextX = parseNumber(values.x);
      const nextY = parseNumber(values.y);
      const nextW = parseWidth(values.w);
      if (!nextX && !nextY && !nextW) {
        delete state[key];
      } else {
        state[key] = { x: nextX, y: nextY, w: nextW };
      }
      applyLayout();
      if (kind === 'section') {
        syncSectionLayoutState(key);
      } else {
        syncLayoutState();
      }
    };

    const refreshInspectorLayoutValues = (key) => {
      inspectorRegistry.forEach((entry) => {
        if (!entry.layoutKey || entry.layoutKey !== key) return;
        if (!entry.layoutInputs) return;
        const values = getLayoutValuesForKey(entry.layoutKey, entry.layoutKind);
        entry.layoutInputs.x.value = values.x;
        entry.layoutInputs.y.value = values.y;
        entry.layoutInputs.w.value = values.w === '' ? '' : values.w;
        if (entry.layoutInputs.modeLabel) {
          entry.layoutInputs.modeLabel.textContent = currentMode === 'mobile' ? 'Mobile' : 'Desktop';
        }
      });
    };

    const refreshAllInspectorLayouts = () => {
      inspectorRegistry.forEach((entry) => {
        if (!entry.layoutInputs) return;
        const values = getLayoutValuesForKey(entry.layoutKey, entry.layoutKind);
        entry.layoutInputs.x.value = values.x;
        entry.layoutInputs.y.value = values.y;
        entry.layoutInputs.w.value = values.w === '' ? '' : values.w;
        if (entry.layoutInputs.modeLabel) {
          entry.layoutInputs.modeLabel.textContent = currentMode === 'mobile' ? 'Mobile' : 'Desktop';
        }
      });
    };

    const createInspector = (config) => {
      const panel = document.createElement('div');
      panel.className = 'pagecopy-inspector';
      bringInspectorToFront(panel);

      const header = document.createElement('div');
      header.className = 'pagecopy-inspector__header';

      const title = document.createElement('div');
      title.className = 'pagecopy-inspector__title';
      title.textContent = config.title || 'Edit';

      const closeButton = document.createElement('button');
      closeButton.type = 'button';
      closeButton.className = 'pagecopy-inspector__close';
      closeButton.textContent = 'x';

      header.appendChild(title);
      header.appendChild(closeButton);
      panel.appendChild(header);

      const body = document.createElement('div');
      body.className = 'pagecopy-inspector__body';
      panel.appendChild(body);

      const entry = {
        panel,
        field: config.field || '',
        copyType: config.copyType || 'plain',
        node: config.node || null,
        layoutKey: config.layoutKey || '',
        layoutKind: config.layoutKind || 'pagecopy',
        layoutInputs: null,
        fieldInput: null,
        modeLabel: null,
      };

      if (entry.field && entry.node) {
        const group = document.createElement('div');
        group.className = 'pagecopy-inspector__group';
        const groupTitle = document.createElement('div');
        groupTitle.className = 'pagecopy-inspector__group-title';
        groupTitle.textContent = 'Content';
        const label = document.createElement('label');
        label.textContent = humanizeLabel(entry.field);
        const input = document.createElement('textarea');
        input.value = entry.copyType === 'rich' ? readRichValue(entry.node) : readPlainValue(entry.node);
        input.addEventListener('input', () => {
          const value = input.value;
          if (entry.node) {
            setNodeValue(entry.node, value);
          }
          handleFieldChange(entry.field, value, entry.node);
        });
        input.addEventListener('blur', () => {
          const value = input.value;
          handleFieldBlur(entry.field, value);
        });
        group.appendChild(groupTitle);
        group.appendChild(label);
        group.appendChild(input);
        body.appendChild(group);
        entry.fieldInput = input;
      }

      if (entry.layoutKey) {
        const layoutGroup = document.createElement('div');
        layoutGroup.className = 'pagecopy-inspector__group';
        const groupTitle = document.createElement('div');
        groupTitle.className = 'pagecopy-inspector__group-title';
        groupTitle.textContent = 'Layout';
        const meta = document.createElement('div');
        meta.className = 'pagecopy-inspector__meta';
        meta.textContent = currentMode === 'mobile' ? 'Mobile' : 'Desktop';
        const row = document.createElement('div');
        row.className = 'pagecopy-inspector__row';

        const xWrap = document.createElement('div');
        const xLabel = document.createElement('label');
        xLabel.textContent = 'X';
        const xInput = document.createElement('input');
        xInput.type = 'number';
        xInput.step = '1';

        const yWrap = document.createElement('div');
        const yLabel = document.createElement('label');
        yLabel.textContent = 'Y';
        const yInput = document.createElement('input');
        yInput.type = 'number';
        yInput.step = '1';

        const wWrap = document.createElement('div');
        const wLabel = document.createElement('label');
        wLabel.textContent = 'Width';
        const wInput = document.createElement('input');
        wInput.type = 'number';
        wInput.step = '1';
        wInput.placeholder = 'auto';

        xWrap.appendChild(xLabel);
        xWrap.appendChild(xInput);
        yWrap.appendChild(yLabel);
        yWrap.appendChild(yInput);
        wWrap.appendChild(wLabel);
        wWrap.appendChild(wInput);
        row.appendChild(xWrap);
        row.appendChild(yWrap);
        row.appendChild(wWrap);

        const actions = document.createElement('div');
        actions.className = 'pagecopy-inspector__actions';
        const resetButton = document.createElement('button');
        resetButton.type = 'button';
        resetButton.className = 'pagecopy-inspector__button pagecopy-inspector__button--ghost';
        resetButton.textContent = 'Reset layout';
        actions.appendChild(resetButton);

        const updateLayout = () => {
          setLayoutValuesForKey(entry.layoutKey, entry.layoutKind, {
            x: xInput.value,
            y: yInput.value,
            w: wInput.value,
          });
          refreshInspectorLayoutValues(entry.layoutKey);
        };
        let layoutTimer = null;
        const queueLayoutUpdate = () => {
          clearTimeout(layoutTimer);
          layoutTimer = setTimeout(updateLayout, 120);
        };

        xInput.addEventListener('input', queueLayoutUpdate);
        yInput.addEventListener('input', queueLayoutUpdate);
        wInput.addEventListener('input', queueLayoutUpdate);
        resetButton.addEventListener('click', () => {
          xInput.value = 0;
          yInput.value = 0;
          wInput.value = '';
          updateLayout();
        });

        layoutGroup.appendChild(groupTitle);
        layoutGroup.appendChild(meta);
        layoutGroup.appendChild(row);
        layoutGroup.appendChild(actions);
        body.appendChild(layoutGroup);

        entry.layoutInputs = { x: xInput, y: yInput, w: wInput, modeLabel: meta };
        const values = getLayoutValuesForKey(entry.layoutKey, entry.layoutKind);
        entry.layoutInputs.x.value = values.x;
        entry.layoutInputs.y.value = values.y;
        entry.layoutInputs.w.value = values.w === '' ? '' : values.w;
      }

      closeButton.addEventListener('click', () => {
        inspectorRegistry.delete(config.key);
        panel.remove();
      });

      panel.addEventListener('pointerdown', () => bringInspectorToFront(panel));
      makePanelDraggable(panel, header);
      return entry;
    };

    const openInspector = (event, fieldNode, layoutNode) => {
      if (!event) return;
      const field = fieldNode ? fieldNode.dataset.copyField : '';
      const copyType = fieldNode ? fieldNode.dataset.copyType || 'plain' : 'plain';
      const layoutKey = layoutNode ? layoutNode.dataset.layoutKey : '';
      const layoutKind = layoutNode ? layoutNode.dataset.layoutKind || 'pagecopy' : 'pagecopy';
      const key = field ? `field:${field}` : (layoutKey ? `layout:${layoutKey}` : '');
      if (!key) return;

      let entry = inspectorRegistry.get(key);
      if (!entry) {
        const title = field ? `Edit ${humanizeLabel(field)}` : `Layout ${humanizeLabel(layoutKey)}`;
        entry = createInspector({
          key,
          title,
          field,
          copyType,
          node: fieldNode,
          layoutKey,
          layoutKind,
        });
        inspectorRegistry.set(key, entry);
        document.body.appendChild(entry.panel);
        const rect = entry.panel.getBoundingClientRect();
        const left = Math.min(window.innerWidth - rect.width - 12, event.clientX + 16);
        const top = Math.min(window.innerHeight - rect.height - 12, event.clientY + 16);
        entry.panel.style.left = `${Math.max(12, left)}px`;
        entry.panel.style.top = `${Math.max(12, top)}px`;
      } else {
        entry.node = fieldNode || entry.node;
        if (entry.fieldInput && entry.node) {
          entry.fieldInput.value = entry.copyType === 'rich' ? readRichValue(entry.node) : readPlainValue(entry.node);
        }
        if (entry.layoutInputs) {
          const values = getLayoutValuesForKey(entry.layoutKey, entry.layoutKind);
          entry.layoutInputs.x.value = values.x;
          entry.layoutInputs.y.value = values.y;
          entry.layoutInputs.w.value = values.w === '' ? '' : values.w;
          if (entry.layoutInputs.modeLabel) {
            entry.layoutInputs.modeLabel.textContent = currentMode === 'mobile' ? 'Mobile' : 'Desktop';
          }
        }
        bringInspectorToFront(entry.panel);
      }
    };

    const setSectionMode = (active) => {
      sectionModeActive = !!active;
      document.body.classList.toggle('pagecopy-section-mode', sectionModeActive);
    };

    const ensureSectionHandles = () => {
      const sections = Array.from(document.querySelectorAll('.builder-section[data-section-id]'));
      sections.forEach((section) => {
        if (section.querySelector('.pagecopy-section-handle')) return;
        const handle = document.createElement('button');
        handle.type = 'button';
        handle.className = 'pagecopy-section-handle';
        handle.setAttribute('aria-label', 'Move section');
        handle.innerHTML = (
          '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<path d="M7 11V5a1 1 0 0 1 2 0v6"/>' +
          '<path d="M9 11V4a1 1 0 0 1 2 0v7"/>' +
          '<path d="M11 11V4a1 1 0 0 1 2 0v7"/>' +
          '<path d="M13 11V5a1 1 0 0 1 2 0v8"/>' +
          '<path d="M15 13l1.5-1a1 1 0 0 1 1.5.8V18c0 2-1.5 3-3 3H9c-2 0-3-1-3.5-2L4 15a1 1 0 0 1 1.4-1.4l2.6 2"/>' +
          '</svg>'
        );
        section.insertBefore(handle, section.firstChild);
      });
    };

    const notifySectionOrder = () => {
      if (!window.parent) return;
      const order = Array.from(document.querySelectorAll('.builder-section[data-section-id]'))
        .map((section) => section.dataset.sectionId)
        .filter(Boolean);
      if (!order.length) return;
      window.parent.postMessage({ type: 'pagecopy:section-order', order, meta: pagecopyMeta || null }, '*');
    };

    const setupSectionDrag = () => {
      let dragSection = null;
      let dragHandle = null;
      let dragStartY = 0;
      let placeholder = null;

      const onPointerDown = (event) => {
        if (!sectionModeActive) return;
        const handle = event.target.closest('.pagecopy-section-handle');
        if (!handle) return;
        if (event.button && event.button !== 0) return;
        const section = handle.closest('.builder-section[data-section-id]');
        if (!section) return;
        event.preventDefault();
        dragSection = section;
        dragHandle = handle;
        dragStartY = event.clientY;
        const rect = section.getBoundingClientRect();
        placeholder = document.createElement('div');
        placeholder.className = 'pagecopy-section-placeholder';
        placeholder.style.height = `${rect.height}px`;
        section.parentNode.insertBefore(placeholder, section.nextSibling);
        section.classList.add('pagecopy-section-dragging');
        section.style.width = `${rect.width}px`;
        section.style.transform = 'translate3d(0, 0, 0)';
        handle.setPointerCapture(event.pointerId);
      };

      const onPointerMove = (event) => {
        if (!dragSection) return;
        const dy = event.clientY - dragStartY;
        dragSection.style.transform = `translate3d(0, ${dy}px, 0)`;
        const sections = Array.from(document.querySelectorAll('.builder-section[data-section-id]')).filter(
          (section) => section !== dragSection
        );
        const pointerY = event.clientY;
        let inserted = false;
        sections.forEach((section) => {
          if (inserted) return;
          const rect = section.getBoundingClientRect();
          if (pointerY < rect.top + rect.height / 2) {
            section.parentNode.insertBefore(placeholder, section);
            inserted = true;
          }
        });
        if (!inserted && placeholder) {
          const parent = dragSection.parentNode;
          if (parent) {
            parent.appendChild(placeholder);
          }
        }
      };

      const onPointerUp = (event) => {
        if (!dragSection) return;
        event.preventDefault();
        dragSection.classList.remove('pagecopy-section-dragging');
        dragSection.style.transform = '';
        dragSection.style.width = '';
        if (dragHandle) {
          try {
            dragHandle.releasePointerCapture(event.pointerId);
          } catch (err) {
            // ignore
          }
        }
        if (placeholder && placeholder.parentNode) {
          placeholder.parentNode.insertBefore(dragSection, placeholder);
        }
        if (placeholder && placeholder.parentNode) {
          placeholder.parentNode.removeChild(placeholder);
        }
        placeholder = null;
        dragSection = null;
        dragHandle = null;
        notifySectionOrder();
      };

      document.addEventListener('pointerdown', onPointerDown);
      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', onPointerUp);
    };

    const setLayoutMode = (active) => {
      layoutModeActive = !!active;
      document.body.classList.toggle('pagecopy-layout-mode', layoutModeActive);
      fields.forEach(node => {
        node.setAttribute('contenteditable', layoutModeActive ? 'false' : 'true');
      });
      editors.forEach(editor => {
        try {
          editor.setReadOnly(layoutModeActive);
        } catch (err) {
          // ignore
        }
      });
    };

    const syncLayoutState = () => {
      if (window.parent) {
        window.parent.postMessage({ type: 'pagecopy:layout', layout: layoutState }, '*');
      }
    };

    const syncSectionLayoutState = (key) => {
      const meta = layoutNodes.get(key);
      if (!meta || meta.kind !== 'section') return;
      if (window.parent) {
        const state = getSectionModeState()[key] || {};
        window.parent.postMessage(
          { type: 'pagecopy:section-layout', sectionId: meta.sectionId, mode: currentMode, layout: state },
          '*'
        );
      }
    };

    const syncAllSectionLayoutState = () => {
      layoutNodes.forEach((meta, key) => {
        if (meta.kind === 'section') {
          syncSectionLayoutState(key);
        }
      });
    };

    const resetLayout = (scope) => {
      if (scope === 'all') {
        layoutState.desktop = {};
        layoutState.mobile = {};
        sectionLayoutState.desktop = {};
        sectionLayoutState.mobile = {};
      } else {
        layoutState[currentMode] = {};
        sectionLayoutState[currentMode] = {};
      }
      applyLayout();
      syncLayoutState();
      syncAllSectionLayoutState();
      refreshAllInspectorLayouts();
    };

    Object.keys(layoutConfig || {}).forEach(key => {
      const meta = layoutConfig[key] || {};
      const selector = meta.selector || meta;
      if (!selector) return;
      const nodes = Array.from(document.querySelectorAll(selector));
      if (!nodes.length) return;
      registerLayoutNodes(key, nodes, { kind: 'pagecopy' });
    });

    const sectionNodes = Array.from(document.querySelectorAll('[data-layout-section][data-section-id]'));
    sectionNodes.forEach(node => {
      const sectionId = node.dataset.sectionId;
      if (!sectionId) return;
      const key = `section-${sectionId}`;
      registerLayoutNodes(key, [node], { kind: 'section', sectionId });
      const desktop = {
        x: parseNumber(node.dataset.layoutX),
        y: parseNumber(node.dataset.layoutY),
        w: parseWidth(node.dataset.layoutW),
      };
      const mobile = {
        x: parseNumber(node.dataset.layoutXMobile),
        y: parseNumber(node.dataset.layoutYMobile),
        w: parseWidth(node.dataset.layoutWMobile),
      };
      if (desktop.x || desktop.y || desktop.w) {
        sectionLayoutState.desktop[key] = desktop;
      }
      if (mobile.x || mobile.y || mobile.w) {
        sectionLayoutState.mobile[key] = mobile;
      }
    });

    if (layoutNodes.size) {
      applyLayout();

      let dragKey = null;
      let dragMeta = null;
      let dragStartX = 0;
      let dragStartY = 0;
      let originX = 0;
      let originY = 0;
      let resizeKey = null;
      let resizeMeta = null;
      let resizeStartX = 0;
      let resizeStartWidth = 0;

      const onPointerDown = (event) => {
        if (!layoutModeActive) return;
        if (event.button && event.button !== 0) return;
        const handle = event.target.closest('.pagecopy-layout-handle');
        if (handle) {
          const target = handle.closest('[data-layout-key]');
          if (!target) return;
          const key = target.dataset.layoutKey;
          const meta = layoutNodes.get(key);
          if (!meta) return;
          event.preventDefault();
          resizeKey = key;
          resizeMeta = meta;
          resizeStartX = event.clientX;
          resizeStartWidth = target.getBoundingClientRect().width;
          target.setPointerCapture(event.pointerId);
          return;
        }

        const target = event.target.closest('[data-layout-key]');
        if (!target) return;
        const key = target.dataset.layoutKey;
        const meta = layoutNodes.get(key);
        if (!meta) return;
        event.preventDefault();
        dragKey = key;
        dragMeta = meta;
        const state = meta.kind === 'section' ? getSectionModeState() : getModeState();
        const coords = state[key] || {};
        originX = Number(coords.x || 0);
        originY = Number(coords.y || 0);
        dragStartX = event.clientX;
        dragStartY = event.clientY;
        target.setPointerCapture(event.pointerId);
      };

      const onPointerMove = (event) => {
        if (!layoutModeActive) return;
        if (resizeKey && resizeMeta) {
          event.preventDefault();
          const dx = event.clientX - resizeStartX;
          const nextW = Math.max(160, Math.round(resizeStartWidth + dx));
          const state = resizeMeta.kind === 'section' ? getSectionModeState() : getModeState();
          const coords = state[resizeKey] || {};
          state[resizeKey] = { x: coords.x || 0, y: coords.y || 0, w: nextW };
          applyLayout();
          return;
        }
        if (!dragKey || !dragMeta) return;
        event.preventDefault();
        const dx = event.clientX - dragStartX;
        const dy = event.clientY - dragStartY;
        const nextX = Math.round(originX + dx);
        const nextY = Math.round(originY + dy);
        const state = dragMeta.kind === 'section' ? getSectionModeState() : getModeState();
        const coords = state[dragKey] || {};
        state[dragKey] = { x: nextX, y: nextY, w: coords.w || null };
        applyLayout();
      };

      const onPointerUp = (event) => {
        if (!layoutModeActive) return;
        if (resizeKey && resizeMeta) {
          event.preventDefault();
          const key = resizeKey;
          resizeKey = null;
          resizeMeta = null;
          if (layoutNodes.get(key)?.kind === 'section') {
            syncSectionLayoutState(key);
          } else {
            syncLayoutState();
          }
          refreshInspectorLayoutValues(key);
          return;
        }
        if (!dragKey || !dragMeta) return;
        event.preventDefault();
        const key = dragKey;
        dragKey = null;
        dragMeta = null;
        if (layoutNodes.get(key)?.kind === 'section') {
          syncSectionLayoutState(key);
        } else {
          syncLayoutState();
        }
        refreshInspectorLayoutValues(key);
      };

      document.addEventListener('pointerdown', onPointerDown);
      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', onPointerUp);
    }

    ensureSectionHandles();
    setupSectionDrag();

    document.addEventListener('click', (event) => {
      if (!event || !event.target) return;
      if (event.target.closest('.pagecopy-inspector')) return;
      if (event.target.closest('.pagecopy-layout-handle')) return;
      if (event.target.closest('.pagecopy-section-handle')) return;
      if (layoutModeActive) return;
      const fieldNode = event.target.closest('[data-copy-field]');
      const layoutNode = event.target.closest('[data-layout-key]');
      if (!fieldNode && !layoutNode) return;
      openInspector(event, fieldNode, layoutNode);
    });

    window.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.type === 'pagecopy:mode') {
        currentMode = normalizeMode(data.mode);
        applyLayout();
        refreshAllInspectorLayouts();
        return;
      }
      if (data.type === 'pagecopy:layout-mode') {
        setLayoutMode(data.active);
        return;
      }
      if (data.type === 'pagecopy:section-mode') {
        setSectionMode(data.active);
        return;
      }
      if (data.type === 'pagecopy:layout-reset') {
        resetLayout(data.scope === 'all' ? 'all' : 'current');
      }
    });
  })();
</script>
"""
    ckeditor_src = static("ckeditor/ckeditor.js")
    script = script.replace("__LAYOUT_CONFIG__", layout_config_json)
    script = script.replace("__LAYOUT_STATE__", layout_state_json)
    script = script.replace("__PAGECOPY_SAVE_URL__", save_url_json)
    script = script.replace("__PAGECOPY_META__", pagecopy_meta_json)
    script = script.replace("__PAGECOPY_EDITOR_CONFIG__", editor_config_json)
    script = script.replace("__PAGECOPY_EDITOR_UPLOAD_URL__", editor_upload_url_json)
    script = script.replace("__PAGECOPY_EDITOR_BROWSE_URL__", editor_browse_url_json)

    head_inject = (
        f'<base href="{html.escape(base_href, quote=True)}">'
        f"{style}"
        f'<script src="{html.escape(ckeditor_src, quote=True)}"></script>'
    )
    if "</head>" in html_text:
        html_text = html_text.replace(
            "</head>",
            f"{head_inject}</head>",
            1,
        )
    else:
        html_text = f"{head_inject}" + html_text

    if "</body>" in html_text:
        html_text = html_text.replace("</body>", f"{script}</body>", 1)
    else:
        html_text += script

    return html_text


def build_home_context(request: HttpRequest) -> Dict[str, Any]:
    from accounts.views import HomeView

    view = HomeView()
    view.request = request
    return view.get_context_data()


def build_services_context(request: HttpRequest) -> Dict[str, Any]:
    from core.views import _build_catalog_context

    ctx = _build_catalog_context(request)
    ctx["font_settings"] = build_page_font_context(PageFontSetting.Page.SERVICES)
    ctx.setdefault("contact_prefill", {"name": "", "email": "", "phone": ""})
    ctx.setdefault("profile", None)
    ctx.setdefault("appointments", [])
    return ctx


def build_store_context(request: HttpRequest) -> Dict[str, Any]:
    from store.forms_store import ProductFilterForm
    from store.models import Category, Product
    from store.views import _apply_filters

    categories = Category.objects.filter(products__is_active=True).distinct()
    form = ProductFilterForm(request.GET or None)

    base_qs = (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related("compatible_models", "options")
        .order_by("-created_at")
    )

    filtered_qs = _apply_filters(base_qs, form)
    filters_active = form.is_valid() and any(form.cleaned_data.values())
    new_arrivals = None if filters_active else base_qs[:8]

    sections = []
    for category in categories:
        cat_base = (
            Product.objects.filter(is_active=True, category=category)
            .select_related("category")
            .prefetch_related("options")
            .order_by("-created_at")
        )
        if cat_base.exists():
            sections.append((category, cat_base[:8]))

    return {
        "categories": categories,
        "filter_form": form,
        "filters_active": filters_active,
        "products": filtered_qs[:24],
        "new_arrivals": new_arrivals,
        "sections": sections,
        "font_settings": build_page_font_context(PageFontSetting.Page.STORE),
    }


def build_merch_context(request: HttpRequest) -> Dict[str, Any]:
    return {}


def build_financing_context(request: HttpRequest) -> Dict[str, Any]:
    return {
        "font_settings": build_page_font_context(PageFontSetting.Page.FINANCING),
    }


def build_about_context(request: HttpRequest) -> Dict[str, Any]:
    return {}


def build_client_portal_context(request: HttpRequest) -> Dict[str, Any]:
    return {
        "profile": None,
        "services": Service.objects.all().order_by("name"),
        "appointments": [],
        "client_files": [],
        "notifications": [],
        "active_tab": "overview",
    }


def build_dealer_status_context(request: HttpRequest) -> Dict[str, Any]:
    dummy_tier = SimpleNamespace(
        code="GOLD",
        label="Gold",
        minimum_spend=50000,
        discount_percent=12,
        notes="",
    )
    return {
        "userprofile": None,
        "dealer_application": DummyDealerApplication(),
        "portal": {},
        "application_steps": ["Apply", "Review", "Approval"],
        "orders_snapshot": SimpleNamespace(total=12, open=3, completed=9, latest=DummyOrderSummary()),
        "tier_levels": [dummy_tier],
        "next_tier": dummy_tier,
        "current_threshold": 10000,
        "remaining_to_next": 40000,
        "lifetime_spent": 12000,
        "is_dealer": False,
    }


PREVIEW_CONFIG: Dict[type, PreviewConfig] = {
    HomePageCopy: PreviewConfig(
        template="client/bgm_home.html",
        copy_key="home_copy",
        context_builder=build_home_context,
    ),
    ServicesPageCopy: PreviewConfig(
        template="client/mainmenu.html",
        copy_key="services_copy",
        header_key="header_copy",
        context_builder=build_services_context,
    ),
    StorePageCopy: PreviewConfig(
        template="store/store_home.html",
        copy_key="store_copy",
        context_builder=build_store_context,
    ),
    MerchPageCopy: PreviewConfig(
        template="client/merch.html",
        copy_key="merch_copy",
        header_key="header_copy",
        context_builder=build_merch_context,
    ),
    FinancingPageCopy: PreviewConfig(
        template="financing.html",
        copy_key="financing_copy",
        header_key="header_copy",
        context_builder=build_financing_context,
    ),
    AboutPageCopy: PreviewConfig(
        template="client/our_story.html",
        copy_key="about_copy",
        header_key="header_copy",
        context_builder=build_about_context,
    ),
    ClientPortalPageCopy: PreviewConfig(
        template="client/dashboard.html",
        copy_key="portal_copy",
        context_builder=build_client_portal_context,
        use_anonymous_user=False,
    ),
    DealerStatusPageCopy: PreviewConfig(
        template="core/dealer/status.html",
        copy_key="dealer_copy",
        context_builder=build_dealer_status_context,
        use_anonymous_user=False,
    ),
}


def build_preview_context(request: HttpRequest, model_cls: type, preview_copy: Any) -> Dict[str, Any]:
    config = PREVIEW_CONFIG.get(model_cls)
    if not config:
        return {}

    ctx: Dict[str, Any] = {}
    if config.context_builder:
        ctx.update(config.context_builder(request))

    ctx[config.copy_key] = preview_copy
    if config.header_key:
        ctx[config.header_key] = preview_copy

    raw_copy = getattr(preview_copy, "_instance", preview_copy)
    ctx["layout_styles"] = build_layout_styles(model_cls, getattr(raw_copy, "layout_overrides", None))
    ctx["page_sections"] = get_page_sections(raw_copy)

    if config.use_anonymous_user:
        ctx["user"] = AnonymousUser()
        preview_request = copy.copy(request)
        preview_request.user = ctx["user"]
        ctx["request"] = preview_request

    if model_cls is HomePageCopy:
        gallery_url = (getattr(raw_copy, "gallery_cta_url", "") or "").strip() or reverse("project-journal")
        ctx["home_gallery_url"] = gallery_url
        gallery_items = ctx.get("home_gallery_items")
        if isinstance(gallery_items, list):
            for item in gallery_items:
                if isinstance(item, dict):
                    item["url"] = gallery_url

    return ctx


def render_pagecopy_preview(request: HttpRequest, model_cls: type, preview_copy: Any, base_href: str) -> str:
    config = PREVIEW_CONFIG.get(model_cls)
    if not config:
        return ""

    try:
        setattr(request, "pagecopy_preview_model", model_cls)
    except Exception:
        pass

    context = build_preview_context(request, model_cls, preview_copy)
    html_text = render_to_string(config.template, context=context, request=request)
    field_types = {}
    for field in model_cls._meta.get_fields():
        if isinstance(field, models.TextField):
            field_types[field.name] = "rich"
        elif isinstance(field, models.CharField):
            field_types[field.name] = "plain"
    html_text = inject_preview_spans(html_text, field_types=field_types)
    raw_copy = getattr(preview_copy, "_instance", preview_copy)
    layout_config = layout_config_for_model(model_cls)
    layout_overrides = getattr(raw_copy, "layout_overrides", None)
    try:
        save_url = reverse("admin-pagecopy-save-field")
    except Exception:
        save_url = None
    try:
        editor_upload_url = reverse("ckeditor_upload")
    except Exception:
        editor_upload_url = None
    try:
        editor_browse_url = reverse("ckeditor_browse")
    except Exception:
        editor_browse_url = None
    editor_config = getattr(settings, "CKEDITOR_CONFIGS", {}).get("pagecopy", {})
    if editor_upload_url:
        editor_upload_url = f"{editor_upload_url}?type=Images"
    pagecopy_meta = {
        "model": f"{model_cls._meta.app_label}.{model_cls._meta.model_name}",
        "object_id": getattr(raw_copy, "pk", None),
    }
    html_text = inject_preview_helpers(
        html_text,
        base_href,
        layout_config=layout_config,
        layout_overrides=layout_overrides,
        save_url=save_url,
        pagecopy_meta=pagecopy_meta,
        editor_config=editor_config,
        editor_upload_url=editor_upload_url,
        editor_browse_url=editor_browse_url,
    )
    return html_text
