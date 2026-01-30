from __future__ import annotations

import copy
import html
import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Tuple

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.template.loader import render_to_string
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


def _wrap_tokens_outside_tags(html_text: str) -> str:
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
                    out.append(
                        f'<span data-copy-field="{field_attr}" contenteditable="true" spellcheck="false">'
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


def inject_preview_spans(html_text: str) -> str:
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
            processed.append(_wrap_tokens_outside_tags(part))
    return "".join(processed)


def inject_preview_helpers(
    html_text: str,
    base_href: str,
    layout_config: Optional[Dict[str, Any]] = None,
    layout_overrides: Optional[Dict[str, Any]] = None,
) -> str:
    layout_config = layout_config or {}
    layout_overrides = normalize_layout_overrides(layout_overrides or {})
    layout_config_json = json.dumps(layout_config)
    layout_state_json = json.dumps(layout_overrides)

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
</style>
"""

    script = """
<script>
  (function() {
    const fields = Array.from(document.querySelectorAll('[data-copy-field]'));

    const byField = {};

    const setNodeValue = (node, value) => {
      const text = value == null ? '' : String(value);
      const lines = text.split(/\n/);
      node.textContent = '';
      lines.forEach((line, idx) => {
        if (idx) node.appendChild(document.createElement('br'));
        node.appendChild(document.createTextNode(line));
      });
    };

    fields.forEach(node => {
      const field = node.dataset.copyField;
      if (!field) return;
      node.setAttribute('contenteditable', 'true');
      node.setAttribute('spellcheck', 'false');
      byField[field] = byField[field] || [];
      byField[field].push(node);

      node.addEventListener('input', () => {
        const value = node.innerText.replace(/\r/g, '');
        (byField[field] || []).forEach(item => {
          if (item !== node) {
            setNodeValue(item, value);
          }
        });
        if (window.parent) {
          window.parent.postMessage({ type: 'pagecopy:update', field, value }, '*');
        }
      });

      node.addEventListener('blur', () => {
        if (window.parent) {
          window.parent.postMessage({ type: 'pagecopy:blur', field }, '*');
        }
      });
    });

    window.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.type !== 'pagecopy:sync') return;
      const field = data.field;
      const value = data.value;
      (byField[field] || []).forEach(node => setNodeValue(node, value));
    });

    const layoutConfig = __LAYOUT_CONFIG__;
    const layoutState = __LAYOUT_STATE__;
    const layoutKeys = Object.keys(layoutConfig || {});
    const layoutNodes = new Map();
    let layoutModeActive = false;
    let currentMode = 'desktop';

    const normalizeMode = (mode) => (mode === 'mobile' ? 'mobile' : 'desktop');
    const getModeState = () => {
      layoutState.desktop = layoutState.desktop || {};
      layoutState.mobile = layoutState.mobile || {};
      return layoutState[currentMode];
    };

    const applyLayout = () => {
      const state = getModeState();
      layoutNodes.forEach((nodes, key) => {
        const coords = state[key] || {};
        const x = Number(coords.x || 0);
        const y = Number(coords.y || 0);
        nodes.forEach(node => {
          if (x || y) {
            node.style.transform = `translate3d(${x}px, ${y}px, 0)`;
          } else {
            node.style.transform = '';
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
    };

    const syncLayoutState = () => {
      if (window.parent) {
        window.parent.postMessage({ type: 'pagecopy:layout', layout: layoutState }, '*');
      }
    };

    const resetLayout = (scope) => {
      if (scope === 'all') {
        layoutState.desktop = {};
        layoutState.mobile = {};
      } else {
        layoutState[currentMode] = {};
      }
      applyLayout();
      syncLayoutState();
    };

    if (layoutKeys.length) {
      layoutKeys.forEach(key => {
        const meta = layoutConfig[key] || {};
        const selector = meta.selector || meta;
        if (!selector) return;
        const nodes = Array.from(document.querySelectorAll(selector));
        if (!nodes.length) return;
        nodes.forEach(node => {
          node.dataset.layoutKey = key;
        });
        layoutNodes.set(key, nodes);
      });

      applyLayout();

      let dragKey = null;
      let dragStartX = 0;
      let dragStartY = 0;
      let originX = 0;
      let originY = 0;

      const onPointerDown = (event) => {
        if (!layoutModeActive) return;
        if (event.button && event.button !== 0) return;
        const target = event.target.closest('[data-layout-key]');
        if (!target) return;
        const key = target.dataset.layoutKey;
        if (!key || !layoutNodes.has(key)) return;
        event.preventDefault();
        dragKey = key;
        const state = getModeState();
        const coords = state[key] || {};
        originX = Number(coords.x || 0);
        originY = Number(coords.y || 0);
        dragStartX = event.clientX;
        dragStartY = event.clientY;
        target.setPointerCapture(event.pointerId);
      };

      const onPointerMove = (event) => {
        if (!layoutModeActive || !dragKey) return;
        event.preventDefault();
        const dx = event.clientX - dragStartX;
        const dy = event.clientY - dragStartY;
        const nextX = Math.round(originX + dx);
        const nextY = Math.round(originY + dy);
        const state = getModeState();
        state[dragKey] = { x: nextX, y: nextY };
        applyLayout();
      };

      const onPointerUp = (event) => {
        if (!layoutModeActive || !dragKey) return;
        event.preventDefault();
        dragKey = null;
        syncLayoutState();
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
    script = script.replace("__LAYOUT_CONFIG__", layout_config_json)
    script = script.replace("__LAYOUT_STATE__", layout_state_json)

    if "</head>" in html_text:
        html_text = html_text.replace(
            "</head>",
            f'<base href="{html.escape(base_href, quote=True)}">{style}</head>',
            1,
        )
    else:
        html_text = f'<base href="{html.escape(base_href, quote=True)}">{style}' + html_text

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
    ctx.setdefault("contact_prefill", {"name": "", "email": "", "phone": ""})
    ctx.setdefault("profile", None)
    ctx.setdefault("appointments", [])
    return ctx


def build_store_context(request: HttpRequest) -> Dict[str, Any]:
    from store.forms import ProductFilterForm
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

    context = build_preview_context(request, model_cls, preview_copy)
    html_text = render_to_string(config.template, context=context, request=request)
    html_text = inject_preview_spans(html_text)
    raw_copy = getattr(preview_copy, "_instance", preview_copy)
    layout_config = layout_config_for_model(model_cls)
    layout_overrides = getattr(raw_copy, "layout_overrides", None)
    html_text = inject_preview_helpers(
        html_text,
        base_href,
        layout_config=layout_config,
        layout_overrides=layout_overrides,
    )
    return html_text
