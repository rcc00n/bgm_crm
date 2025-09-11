# core/context_processors_core.py
from django.urls import resolve
from django.templatetags.static import static

# подложи сюда свои временные изображения в static/img/
HERO_MAP = {
    "home":            "img/hero-home.jpg",
    "client-dashboard":"img/hero-services.jpg",
    "store":           "img/hero-products.jpg",
    "merch":           "img/hero-merch.jpg",
    "dealer-status":   "img/hero-dealers.jpg",
    "financing":       "img/hero-financing.jpg",
    "our-story":       "img/hero-about.jpg",
}

FALLBACK = "img/hero-preview.png"  # дефолт, если для роута нет картинки

def hero_media(request):
    try:
        url_name = resolve(request.path_info).url_name or ""
    except Exception:
        url_name = ""

    path = HERO_MAP.get(url_name, FALLBACK)
    return {
        "hero_media": {
            "src": static(path),
            "alt": f"BGM — {url_name or 'preview'}",
        }
    }
