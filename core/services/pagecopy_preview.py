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
    let currentMode = 'desktop';

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
      };

      document.addEventListener('pointerdown', onPointerDown);
      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', onPointerUp);
    }

    window.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.type === 'pagecopy:mode') {
        currentMode = normalizeMode(data.mode);
        applyLayout();
        return;
      }
      if (data.type === 'pagecopy:layout-mode') {
        setLayoutMode(data.active);
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
