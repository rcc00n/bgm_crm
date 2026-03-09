from __future__ import annotations

import csv
import hashlib
import mimetypes
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import slugify

from store.models import Product, ProductOption


MERCH_CATEGORY_SLUGS = {
    # BGM merch
    "merch",
    # Common vendor/apparel categories (defensive: user requested "do not touch merch").
    "apparel",
    "t-shirt",
    "tshirts",
    "hoodie",
    "hoodies",
    "hat",
    "hats",
    "sticker",
    "stickers",
    "sweater",
    "crewneck",
    "beanie",
}

MERCH_CATEGORY_NAME_HINTS = (
    "merch",
    "apparel",
    "t-shirt",
    "tshirt",
    "hoodie",
    "hat",
    "sticker",
    "sweater",
    "crewneck",
    "beanie",
)

NAME_MATCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "kit",
    "only",
    "or",
    "single",
    "system",
    "the",
    "inch",
    "universal",
    "with",
    "without",
    "w",
}

NAME_MATCH_VENDOR_TOKENS = {
    "chaos",
    "custom",
    "dieselr",
    "dirty",
    "ddc",
    "efi",
    "ez",
    "gdp",
    "live",
    "lynk",
    "mm3",
    "motorcraft",
    "mpvi4",
    "sct",
    "support",
    "tuning",
}

NAME_MATCH_FAMILY_ALIASES = {
    "cummins": frozenset({"cummins", "dodge", "ram"}),
    "duramax": frozenset({"duramax", "gm", "gmc", "chevy", "chevrolet"}),
    "ecodiesel": frozenset({"ecodiesel", "jeep", "gladiator"}),
    "powerstroke": frozenset({"powerstroke", "ford"}),
    "titan": frozenset({"nissan", "titan"}),
}
NAME_MATCH_PRESERVE_TOKENS = frozenset(
    alias
    for aliases in NAME_MATCH_FAMILY_ALIASES.values()
    for alias in aliases
)

NAME_MATCH_ENGINE_CODE_TOKENS = {
    "aisin",
    "e66",
    "lb7",
    "lbz",
    "lly",
    "lmm",
    "lml",
    "lm2",
    "lwn",
    "l5p",
    "lz0",
    "t87a",
}

NAME_MATCH_PHRASES = {
    "cat_dpf": frozenset({"cat", "dpf"}),
    "ccv": frozenset({"ccv"}),
    "downpipe_back_exhaust": frozenset({"downpipe", "back", "exhaust"}),
    "egr": frozenset({"egr"}),
    "harness": frozenset({"harness"}),
    "intercooler_piping": frozenset({"intercooler", "piping"}),
    "pcv": frozenset({"pcv"}),
    "support_pack": frozenset({"support", "pack"}),
    "switch": frozenset({"switch"}),
    "transmission_tune_file": frozenset({"transmission", "tune", "file"}),
    "tune_file": frozenset({"tune", "file"}),
    "unlock_cable": frozenset({"unlock", "cable"}),
    "y_bridge": frozenset({"y", "bridge"}),
}

YEAR_RANGE_RE = re.compile(r"\b(19\d{2}|20\d{2})(?:\.\d+)?\s*[-/]\s*(19\d{2}|20\d{2})(?:\.\d+)?\b")
YEAR_PLUS_RE = re.compile(r"\b(19\d{2}|20\d{2})(?:\.\d+)?\s*\+\b")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
IMAGE_CONTENT_TYPE_PREFIX = "image/"
KNOWN_IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _is_remote_image_value(value: str) -> bool:
    return value.startswith(("http://", "https://"))


@dataclass(frozen=True)
class RemoteImageCheck:
    ok: bool
    content_type: str = ""
    status_code: int = 0
    error: str = ""


class RemoteImageResolver:
    def __init__(self, *, timeout: float = 8.0, validate: bool = False, localize: bool = False):
        self.timeout = max(float(timeout or 0.0), 0.5)
        self.validate = bool(validate or localize)
        self.localize_enabled = bool(localize)
        self._checks: Dict[str, RemoteImageCheck] = {}
        self._localized: Dict[str, str] = {}

    def inspect(self, url: str) -> RemoteImageCheck:
        url = (url or "").strip()
        if not url:
            return RemoteImageCheck(ok=False, error="empty_url")
        if not _is_remote_image_value(url):
            return RemoteImageCheck(ok=True)
        cached = self._checks.get(url)
        if cached is not None:
            return cached
        if not self.validate:
            result = RemoteImageCheck(ok=True)
            self._checks[url] = result
            return result

        req = Request(url, method="GET", headers={"User-Agent": "BGM-CRM/1.0", "Accept": "image/*,*/*;q=0.8"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                status = int(getattr(resp, "status", 200) or 200)
                content_type = (resp.headers.get("Content-Type", "") or "").strip()
                if 200 <= status < 400 and content_type.startswith(IMAGE_CONTENT_TYPE_PREFIX):
                    try:
                        resp.read(1)
                    except Exception:
                        pass
                    result = RemoteImageCheck(ok=True, content_type=content_type, status_code=status)
                else:
                    result = RemoteImageCheck(
                        ok=False,
                        content_type=content_type,
                        status_code=status,
                        error=f"unexpected_response:{status}:{content_type}",
                    )
        except HTTPError as exc:
            result = RemoteImageCheck(
                ok=False,
                content_type=(exc.headers.get("Content-Type", "") or "").strip(),
                status_code=int(exc.code or 0),
                error=f"http_{exc.code}",
            )
        except URLError as exc:
            result = RemoteImageCheck(ok=False, error=f"url_error:{exc.reason}")
        except Exception as exc:
            result = RemoteImageCheck(ok=False, error=exc.__class__.__name__)

        self._checks[url] = result
        return result

    def is_usable(self, url: str) -> bool:
        return self.inspect(url).ok

    def localize(self, url: str) -> str:
        url = (url or "").strip()
        if not url or not _is_remote_image_value(url):
            return url
        cached = self._localized.get(url)
        if cached:
            return cached
        check = self.inspect(url)
        if not check.ok:
            raise ValueError(f"Cannot localize broken image URL: {url}")

        storage_name = self._storage_name(url, check.content_type)
        if default_storage.exists(storage_name):
            self._localized[url] = storage_name
            return storage_name

        req = Request(url, method="GET", headers={"User-Agent": "BGM-CRM/1.0", "Accept": "image/*,*/*;q=0.8"})
        with urlopen(req, timeout=self.timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            content_type = (resp.headers.get("Content-Type", "") or check.content_type).strip()
            if status < 200 or status >= 400 or not content_type.startswith(IMAGE_CONTENT_TYPE_PREFIX):
                raise ValueError(f"Unexpected response while downloading {url}: {status} {content_type}")
            body = resp.read()
            if not body:
                raise ValueError(f"Downloaded image is empty: {url}")

        saved_name = default_storage.save(storage_name, ContentFile(body))
        self._checks[url] = RemoteImageCheck(ok=True, content_type=content_type, status_code=200)
        self._localized[url] = saved_name
        return saved_name

    def _storage_name(self, url: str, content_type: str) -> str:
        parsed = urlparse(url)
        base_name = os.path.basename(unquote(parsed.path or "")) or "image"
        stem, suffix = os.path.splitext(base_name)
        suffix = (suffix or "").lower()
        if suffix not in KNOWN_IMAGE_SUFFIXES:
            guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip()) or ".jpg"
            suffix = ".jpg" if guessed == ".jpe" else guessed.lower()
        if suffix not in KNOWN_IMAGE_SUFFIXES:
            suffix = ".jpg"
        safe_stem = slugify(stem) or "image"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return f"store/products/imported/ddc/{safe_stem}-{digest}{suffix}"


def _is_merch_product(product: Product) -> bool:
    sku = (getattr(product, "sku", "") or "").strip().upper()
    slug = (getattr(product, "slug", "") or "").strip().lower()
    category = getattr(product, "category", None)
    category_slug = (getattr(category, "slug", "") or "").strip().lower()
    category_name = (getattr(category, "name", "") or "").strip().lower()
    tags = [str(t).strip().lower() for t in (getattr(product, "tags", None) or []) if str(t).strip()]

    if sku.startswith("PF-"):
        return True
    if slug.startswith("merch-"):
        return True
    if category_slug in MERCH_CATEGORY_SLUGS:
        return True
    if any(hint in category_name for hint in MERCH_CATEGORY_NAME_HINTS):
        return True
    if "merch" in tags or "apparel" in tags:
        return True
    return False


def _iter_ranked_group_image_urls(group: List[Dict[str, str]]) -> List[str]:
    """
    Shopify-like imports can contain multiple rows per handle.
    We rank images deterministically:
    - Sort by Image Position (lowest wins), tie-breaking by earliest occurrence.
    - Deduplicate URLs while preserving the best-positioned occurrence.
    """
    best_by_url: Dict[str, Tuple[int, int]] = {}
    for idx, row in enumerate(group):
        raw = (row.get("Image Src") or row.get("Variant Image") or "").strip()
        if not raw:
            continue
        pos_raw = (row.get("Image Position") or "").strip()
        try:
            pos = int(pos_raw) if pos_raw else 10**9
        except Exception:
            pos = 10**9
        key = (pos, idx)
        if raw not in best_by_url or key < best_by_url[raw]:
            best_by_url[raw] = key
    return [url for url, _key in sorted(best_by_url.items(), key=lambda kv: kv[1])]


def _pick_primary_image_url(
    group: List[Dict[str, str]],
    *,
    resolver: Optional[RemoteImageResolver] = None,
) -> str:
    urls = _iter_ranked_group_image_urls(group)
    if not urls:
        return ""
    if not resolver or not resolver.validate:
        return urls[0]
    for url in urls:
        if resolver.is_usable(url):
            return url
    return ""


def _pick_group_title(handle: str, group: List[Dict[str, str]]) -> str:
    for row in group:
        title = (row.get("Title") or row.get("title") or "").strip()
        if title:
            return title
    return handle


def _pick_group_field(group: List[Dict[str, str]], *field_names: str) -> str:
    for row in group:
        for field_name in field_names:
            value = (row.get(field_name) or row.get(field_name.lower()) or "").strip()
            if value:
                return value
    return ""


def _iter_candidate_skus(group: List[Dict[str, str]], *, limit: int = 50) -> List[str]:
    """
    Return unique SKU candidates from Shopify-like rows in stable order.
    We use these for fallback matching against Product.sku and ProductOption.sku.
    """
    out: List[str] = []
    seen = set()
    for row in group:
        sku = (row.get("SKU") or row.get("Variant SKU") or "").strip()
        if not sku or sku in seen:
            continue
        out.append(sku)
        seen.add(sku)
        if len(out) >= limit:
            break
    return out


def _iter_shopify_groups(rows: Iterable[Dict[str, str]]):
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        handle = (row.get("Handle") or row.get("handle") or "").strip()
        if not handle:
            handle = (row.get("Title") or row.get("title") or "").strip()
        if not handle:
            continue
        grouped[handle].append(row)
    return grouped.items()


def _normalize_match_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("eco diesel", "ecodiesel")
    text = text.replace("&", " and ")
    text = text.replace("w/", " with ")
    text = text.replace("+", " plus ")
    text = text.replace("turboback", "turbo back")
    text = re.sub(r"(\d)\.(\d)l\b", r"\1\2l", text)
    text = re.sub(r"(?<=\d)\"", " inch ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(\d)\s+(\d)l\b", r"\1\2l", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_match_token(token: str) -> str:
    token = token.strip().lower()
    if token in NAME_MATCH_PRESERVE_TOKENS:
        return token
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        token = token[:-1]
    return token


def _expand_compound_token(token: str) -> List[str]:
    if token.isdigit() and len(token) >= 8 and len(token) % 4 == 0:
        chunks = [token[idx:idx + 4] for idx in range(0, len(token), 4)]
        if all(chunk.isdigit() for chunk in chunks):
            return chunks
    model_parts = re.findall(r"[a-z]{1,3}\d{2,4}", token)
    if model_parts and "".join(model_parts) == token and len(model_parts) > 1:
        return model_parts
    return [token]


def _tokenize_match_text(value: str) -> List[str]:
    tokens: List[str] = []
    for raw in _normalize_match_text(value).split():
        for expanded in _expand_compound_token(raw):
            token = _normalize_match_token(expanded)
            if token:
                tokens.append(token)
    return tokens


def _extract_year_span(value: str) -> Optional[Tuple[int, int]]:
    starts: List[int] = []
    ends: List[int] = []
    for match in YEAR_RANGE_RE.finditer(value or ""):
        start = int(match.group(1))
        end = int(match.group(2))
        starts.append(min(start, end))
        ends.append(max(start, end))
    for match in YEAR_PLUS_RE.finditer(value or ""):
        starts.append(int(match.group(1)))
        ends.append(2100)
    if starts and ends:
        return min(starts), max(ends)
    years = [int(year) for year in YEAR_RE.findall(value or "")]
    if not years:
        return None
    return min(years), max(years)


@dataclass(frozen=True)
class NameMatchProfile:
    fingerprint: str
    tokens: FrozenSet[str]
    core_tokens: FrozenSet[str]
    families: FrozenSet[str]
    engines: FrozenSet[str]
    phrases: FrozenSet[str]
    year_span: Optional[Tuple[int, int]]


def _build_name_match_profile(*parts: str) -> NameMatchProfile:
    raw = " ".join(part for part in parts if part)
    token_list = _tokenize_match_text(raw)
    tokens = frozenset(token_list)

    families = frozenset(
        family
        for family, aliases in NAME_MATCH_FAMILY_ALIASES.items()
        if tokens & aliases
    )
    family_alias_tokens = frozenset(alias for aliases in NAME_MATCH_FAMILY_ALIASES.values() for alias in aliases)

    engines = frozenset(
        token
        for token in tokens
        if re.fullmatch(r"\d{2}l", token) or token in NAME_MATCH_ENGINE_CODE_TOKENS
    )
    phrases = frozenset(
        phrase
        for phrase, phrase_tokens in NAME_MATCH_PHRASES.items()
        if phrase_tokens <= tokens
    )
    core_tokens = frozenset(
        token
        for token in tokens
        if token not in NAME_MATCH_STOPWORDS
        and token not in NAME_MATCH_VENDOR_TOKENS
        and token not in family_alias_tokens
        and not YEAR_RE.fullmatch(token)
    )
    fingerprint = " ".join(sorted(core_tokens))
    return NameMatchProfile(
        fingerprint=fingerprint,
        tokens=tokens,
        core_tokens=core_tokens,
        families=families,
        engines=engines,
        phrases=phrases,
        year_span=_extract_year_span(raw),
    )


@dataclass(frozen=True)
class CsvImageCandidate:
    handle: str
    handle_slug: str
    title: str
    vendor: str
    product_type: str
    years_text: str
    image_url: str
    skus: Tuple[str, ...]
    profile: NameMatchProfile
    family: str
    kind: str
    group: str


@dataclass(frozen=True)
class NameMatchResult:
    candidate: CsvImageCandidate
    score: float
    runner_up_score: float

    @property
    def margin(self) -> float:
        return self.score - self.runner_up_score


@dataclass
class PlannedUpdate:
    product: Product
    image_url: str
    source: str
    reference: str


@dataclass
class ImportStats:
    updated: int = 0
    unchanged: int = 0
    matched_exact: int = 0
    matched_name: int = 0
    matched_broad: int = 0
    skipped_merch: int = 0
    skipped_missing: int = 0
    skipped_no_image: int = 0
    skipped_invalid_image: int = 0
    skipped_low_confidence: int = 0
    skipped_download_failed: int = 0


def _candidate_match_text(candidate: CsvImageCandidate) -> str:
    return " ".join(
        part
        for part in (
            candidate.title,
            candidate.handle,
            candidate.product_type,
            candidate.years_text,
            candidate.vendor,
            " ".join(candidate.skus),
        )
        if part
    )


def _build_product_match_profile(product: Product) -> NameMatchProfile:
    category = getattr(product, "category", None)
    category_name = (getattr(category, "name", "") or "").strip()
    category_slug = (getattr(category, "slug", "") or "").replace("-", " ").strip()
    return _build_name_match_profile(
        getattr(product, "name", "") or "",
        getattr(product, "slug", "").replace("-", " "),
        category_name,
        category_slug,
    )


def _product_match_specificity(product: Product) -> int:
    profile = _build_product_match_profile(product)
    text = f"{getattr(product, 'name', '')} {getattr(product, 'slug', '').replace('-', ' ')}"
    family = _detect_broad_family(text)
    kind = _detect_broad_kind(text)
    score = len(profile.core_tokens)
    score += len(profile.phrases) * 3
    score += len(profile.engines) * 2
    if profile.year_span:
        score += 2
    if family != "generic":
        score += 2
    if kind != "generic":
        score += 1
    return score


def _year_spans_overlap(
    left: Optional[Tuple[int, int]],
    right: Optional[Tuple[int, int]],
) -> bool:
    if not left or not right:
        return True
    return left[0] <= right[1] and right[0] <= left[1]


def _score_name_match(product_profile: NameMatchProfile, candidate_profile: NameMatchProfile) -> Optional[float]:
    if (
        product_profile.families
        and candidate_profile.families
        and product_profile.families.isdisjoint(candidate_profile.families)
    ):
        return None
    if (
        product_profile.engines
        and candidate_profile.engines
        and product_profile.engines.isdisjoint(candidate_profile.engines)
    ):
        return None
    if not _year_spans_overlap(product_profile.year_span, candidate_profile.year_span):
        return None
    if (
        product_profile.phrases
        and candidate_profile.phrases
        and product_profile.phrases.isdisjoint(candidate_profile.phrases)
    ):
        return None

    shared_core = product_profile.core_tokens & candidate_profile.core_tokens
    shared_phrase = product_profile.phrases & candidate_profile.phrases
    if not shared_core and not shared_phrase:
        return None

    product_core = product_profile.core_tokens or product_profile.tokens
    candidate_core = candidate_profile.core_tokens or candidate_profile.tokens
    union = product_core | candidate_core
    core_ratio = (len(shared_core) / len(union)) if union else 0.0
    fingerprint_ratio = SequenceMatcher(
        None,
        product_profile.fingerprint,
        candidate_profile.fingerprint,
    ).ratio()

    score = (core_ratio * 0.55) + (fingerprint_ratio * 0.20)
    if product_profile.families and candidate_profile.families:
        score += 0.10 * len(product_profile.families & candidate_profile.families)
    if product_profile.engines and candidate_profile.engines:
        score += 0.10 * len(product_profile.engines & candidate_profile.engines)
    if product_profile.year_span and candidate_profile.year_span and _year_spans_overlap(
        product_profile.year_span,
        candidate_profile.year_span,
    ):
        score += 0.08
    if product_profile.phrases and candidate_profile.phrases:
        score += 0.18 * len(shared_phrase)
    return score


def _find_best_name_match(
    product: Product,
    candidates: List[CsvImageCandidate],
) -> Optional[NameMatchResult]:
    profile = _build_product_match_profile(product)
    scored: List[Tuple[float, CsvImageCandidate]] = []
    for candidate in candidates:
        score = _score_name_match(profile, candidate.profile)
        if score is None:
            continue
        scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_candidate = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    return NameMatchResult(
        candidate=best_candidate,
        score=best_score,
        runner_up_score=runner_up_score,
    )


def _detect_broad_family(text: str) -> str:
    normalized = _normalize_match_text(text)
    found: List[str] = []
    if "powerstroke" in normalized or re.search(r"\bford\b", normalized):
        found.append("powerstroke")
    if (
        "duramax" in normalized
        or re.search(r"\bgm\b", normalized)
        or re.search(r"\bgmc\b", normalized)
        or re.search(r"\bchevy\b", normalized)
        or re.search(r"\bchevrolet\b", normalized)
    ):
        found.append("duramax")
    if "ecodiesel" in normalized or "jeep" in normalized or "gladiator" in normalized:
        found.append("ecodiesel")
    if "cummins" in normalized or "dodge" in normalized or re.search(r"\bram\b", normalized):
        found.append("cummins")
    if "nissan" in normalized or "titan" in normalized:
        found.append("nissan")
    unique = sorted(set(found))
    if len(unique) != 1:
        return "generic"
    family = unique[0]
    if family == "nissan":
        return "cummins" if "cummins" in normalized else "generic"
    return family


def _detect_broad_kind(text: str) -> str:
    normalized = _normalize_match_text(text)
    tokens = set(_tokenize_match_text(text))
    if "transmission tune" in normalized:
        return "transmission_tune"
    if "support pack" in normalized:
        return "support_pack"
    if (
        "tune file" in normalized
        or "tune files" in normalized
        or "stock file" in normalized
        or "live upgrade" in normalized
        or "vin license" in normalized
        or "credits" in normalized
        or "flashscan" in normalized
        or "auto agent" in normalized
        or "efi live" in normalized
        or "mpvi4" in normalized
        or "mm3" in normalized
        or "commander" in normalized
        or re.search(r"\bsct\b", normalized)
    ):
        return "tuning"
    if (
        "harness" in normalized
        or "unlock cable" in normalized
        or "splitter" in normalized
        or re.search(r"\becm\b", normalized)
        or "plug kit" in normalized
        or "injector plug" in normalized
    ):
        return "electrical"
    if "switch" in normalized:
        return "switch"
    if ("cat" in tokens and "dpf" in tokens) or "dpf race pipe" in normalized:
        return "cat_dpf"
    if (
        "downpipe back exhaust" in normalized
        or "flexpipe back exhaust" in normalized
        or "dpf back exhaust" in normalized
        or "exhaust system single" in normalized
        or "cat back exhaust" in normalized
        or "cat back race pipe" in normalized
    ):
        return "downpipe_exhaust"
    if "turbo back" in normalized:
        return "turbo_exhaust"
    if "egr" in tokens:
        return "egr"
    if "pcv" in tokens or "ccv" in tokens:
        return "pcv"
    if (
        "y bridge" in normalized
        or "ybridge" in normalized
        or "max flow bridge" in normalized
        or "cold side tube" in normalized
    ):
        return "bridge"
    if "intercooler" in normalized:
        return "intercooler"
    if "intake" in normalized or "filter" in normalized or "resonator" in normalized:
        return "intake"
    if "muffler" in normalized:
        return "muffler"
    if "traction bars" in normalized:
        return "chassis"
    if "pipe" in tokens or "pipes" in tokens:
        return "pipe"
    return "generic"


def _find_candidate_by_tokens(
    candidates: List[CsvImageCandidate],
    required_tokens: Tuple[str, ...],
    *,
    family: str | None = None,
) -> Optional[CsvImageCandidate]:
    required = frozenset(_tokenize_match_text(" ".join(required_tokens)))
    if not required:
        return None
    for candidate in candidates:
        if family and candidate.family != family:
            continue
        if required <= candidate.profile.tokens:
            return candidate
    return None


def _kind_group(kind: str) -> str:
    if kind in {"cat_dpf", "downpipe_exhaust", "turbo_exhaust", "muffler", "pipe"}:
        return "exhaust"
    if kind in {"bridge", "egr", "intake", "intercooler", "pcv"}:
        return "airflow"
    if kind in {"electrical", "support_pack", "switch", "transmission_tune", "tuning"}:
        return "electronic"
    return kind or "generic"


def _choose_broad_fallback_candidate(
    product: Product,
    candidates: List[CsvImageCandidate],
) -> Tuple[Optional[CsvImageCandidate], str]:
    text = f"{product.name} {getattr(product, 'slug', '').replace('-', ' ')}"
    family = _detect_broad_family(text)
    kind = _detect_broad_kind(text)
    year_span = _extract_year_span(text)
    start_year = year_span[0] if year_span else None
    normalized = _normalize_match_text(text)

    def pick(*tokens: str, family_name: str | None = None) -> Optional[CsvImageCandidate]:
        return _find_candidate_by_tokens(candidates, tuple(tokens), family=family_name)

    universal_tuning = pick("universal", "mm3", "cts2", "pod", "adapter")
    cummins_tuning = pick("cummins", "ecm", "swap", "unlock")
    duramax_harness_lm2 = pick("duramax", "lm2", "can", "bus", "plug", "kit")
    duramax_harness_l5p = pick("duramax", "l5p", "can", "bus", "plug", "kit")
    powerstroke_tuning_old = pick("powerstroke", "throttle", "valve", "delete")
    powerstroke_tuning_new = pick("2020", "powerstroke", "throttle", "valve", "delete")
    powerstroke_ccv = pick("powerstroke", "ccv", "delete")
    cummins_ccv = pick("cummins", "ccv", "delete")
    ecodiesel_egr_old = pick("jeep", "ecodiesel", "egr", "delete")
    ecodiesel_egr_new = pick("2020", "jeep", "ram", "ecodiesel", "egr", "delete")
    duramax_y_bridge = pick("duramax", "y", "bridge")
    duramax_pcv_old = pick("duramax", "pcv", "ccv", "breather", "reroute")
    duramax_pcv_lml = pick("duramax", "ccv", "pcv", "route")
    duramax_intercooler = pick("duramax", "intercooler", "piping", "kit")
    cummins_intercooler = pick("cummins", "intercooler", "piping", "kit")
    powerstroke_exhaust = pick("powerstroke", "downpipe", "back", "exhaust")
    powerstroke_catdpf_old = pick("powerstroke", "cat", "dpf", "delete")
    powerstroke_catdpf_new = pick("2020", "powerstroke", "cat", "dpf")
    duramax_exhaust_old = pick("duramax", "downpipe", "back", "exhaust", family_name="duramax")
    duramax_exhaust_new = pick("2017", "duramax", "downpipe", "back", "exhaust")
    duramax_catdpf = pick("duramax", "cat", "dpf", "race", "pipe")
    cummins_exhaust_old = pick("cummins", "turboback", "exhaust", "system")
    cummins_exhaust_mid = pick("cummins", "downpipe", "back", "exhaust", "system")
    cummins_exhaust_new = pick("cummins", "flexpipe", "back", "exhaust", "system")
    cummins_catdpf_old = pick("2013", "cummins", "cat", "dpf", "delete")
    cummins_catdpf_new = pick("2019", "cummins", "cat", "dpf", "delete")
    universal_muffler = pick("duramax", "turboback", "muffler")
    duramax_egr_lly = pick("duramax", "egr", "delete", "pipe")
    duramax_egr_lml = pick("duramax", "egr", "upgrade", "kit")
    powerstroke_egr_old = pick("powerstroke", "egr", "block", "off")
    powerstroke_egr_new = pick("2020", "powerstroke", "egr", "block", "off")
    cummins_egr = pick("cummins", "egr", "cooler", "delete")
    duramax_intake_old = pick("duramax", "intake", "resonator", "plug")
    duramax_intake_l5p = pick("duramax", "intake", "horn", "pcv")
    cummins_filter = pick("air", "intake", "filter")
    powerstroke_valance = pick("powerstroke", "front", "valance")

    candidate: Optional[CsvImageCandidate] = None

    if kind in {"transmission_tune", "support_pack", "tuning"}:
        if "mm3" in normalized:
            candidate = universal_tuning
        elif family == "duramax":
            candidate = duramax_harness_lm2 if any(token in normalized for token in ("lm2", "lz0", "30l")) else duramax_harness_l5p
        elif family == "cummins":
            candidate = cummins_tuning or universal_tuning
        elif family == "powerstroke":
            candidate = universal_tuning or powerstroke_tuning_new or powerstroke_tuning_old
        elif family == "ecodiesel":
            candidate = universal_tuning or ecodiesel_egr_new or ecodiesel_egr_old
        else:
            candidate = universal_tuning
    elif kind in {"electrical", "switch"}:
        if family == "duramax":
            candidate = duramax_harness_lm2 if any(token in normalized for token in ("lm2", "lz0", "30l")) else duramax_harness_l5p
        elif family == "cummins":
            candidate = cummins_tuning or universal_tuning
        elif family == "powerstroke":
            candidate = universal_tuning or powerstroke_tuning_new or powerstroke_tuning_old
        else:
            candidate = universal_tuning
    elif kind == "cat_dpf":
        if family == "powerstroke":
            candidate = powerstroke_catdpf_new if start_year and start_year >= 2020 else powerstroke_catdpf_old
        elif family == "duramax":
            candidate = duramax_catdpf
        elif family == "cummins":
            candidate = cummins_catdpf_new if start_year and start_year >= 2019 else cummins_catdpf_old
        elif family == "ecodiesel":
            candidate = ecodiesel_egr_new if start_year and start_year >= 2020 else ecodiesel_egr_old
        else:
            candidate = duramax_catdpf
    elif kind == "downpipe_exhaust":
        if family == "powerstroke":
            candidate = powerstroke_exhaust
        elif family == "duramax":
            candidate = duramax_exhaust_old if start_year and start_year <= 2010 else duramax_exhaust_new
        elif family == "cummins":
            if start_year and start_year >= 2019:
                candidate = cummins_exhaust_new
            elif start_year and start_year >= 2010:
                candidate = cummins_exhaust_mid
            else:
                candidate = cummins_exhaust_old or cummins_exhaust_mid
        elif family == "ecodiesel":
            candidate = ecodiesel_egr_new if start_year and start_year >= 2020 else ecodiesel_egr_old
        else:
            candidate = universal_muffler
    elif kind == "turbo_exhaust":
        if family == "cummins":
            candidate = cummins_exhaust_old or cummins_exhaust_mid
        elif family == "duramax":
            candidate = universal_muffler or duramax_exhaust_new
        elif family == "powerstroke":
            candidate = powerstroke_exhaust
        else:
            candidate = universal_muffler
    elif kind == "egr":
        if family == "cummins":
            candidate = cummins_egr
        elif family == "duramax":
            candidate = duramax_egr_lly if start_year and start_year <= 2005 else duramax_egr_lml
        elif family == "powerstroke":
            candidate = powerstroke_egr_new if start_year and start_year >= 2020 else powerstroke_egr_old
        elif family == "ecodiesel":
            candidate = ecodiesel_egr_new if start_year and start_year >= 2020 else ecodiesel_egr_old
        else:
            candidate = cummins_egr
    elif kind == "pcv":
        if family == "duramax":
            candidate = duramax_pcv_old if start_year and start_year <= 2010 else duramax_pcv_lml
        elif family == "powerstroke":
            candidate = powerstroke_ccv
        elif family == "cummins":
            candidate = cummins_ccv
        else:
            candidate = duramax_pcv_old
    elif kind == "bridge":
        if family == "duramax":
            candidate = duramax_y_bridge
        else:
            candidate = cummins_intercooler
    elif kind == "intercooler":
        if family == "duramax":
            candidate = duramax_intercooler
        elif family == "cummins":
            candidate = cummins_intercooler
        elif family == "powerstroke":
            candidate = powerstroke_tuning_new if start_year and start_year >= 2020 else powerstroke_tuning_old
        else:
            candidate = cummins_intercooler
    elif kind == "intake":
        if family == "duramax":
            candidate = duramax_intake_old if start_year and start_year <= 2010 else duramax_intake_l5p
        elif family == "cummins":
            candidate = cummins_filter
        elif family == "powerstroke":
            candidate = powerstroke_tuning_new if start_year and start_year >= 2020 else powerstroke_tuning_old
        else:
            candidate = cummins_filter
    elif kind == "muffler":
        candidate = universal_muffler
    elif kind == "pipe":
        if family == "cummins":
            candidate = cummins_catdpf_new if "dpf" in normalized else cummins_intercooler
        elif family == "duramax":
            candidate = duramax_catdpf if "dpf" in normalized else (duramax_intercooler if start_year and start_year >= 2011 else duramax_intake_old)
        elif family == "powerstroke":
            candidate = powerstroke_exhaust
        else:
            candidate = cummins_intercooler
    elif kind == "chassis":
        candidate = powerstroke_valance or universal_tuning
    else:
        if family == "duramax":
            candidate = duramax_harness_l5p
        elif family == "cummins":
            candidate = cummins_tuning or universal_tuning
        elif family == "powerstroke":
            candidate = universal_tuning
        else:
            candidate = universal_tuning

    return candidate, f"{family}/{kind}"


def _score_diverse_fallback_candidate(
    product_profile: NameMatchProfile,
    *,
    product_family: str,
    product_kind: str,
    product_group: str,
    candidate: CsvImageCandidate,
) -> Optional[float]:
    if product_family != "generic" and candidate.family not in {product_family, "generic"}:
        return None
    if (
        product_profile.engines
        and candidate.profile.engines
        and product_profile.engines.isdisjoint(candidate.profile.engines)
    ):
        return None

    shared_core = product_profile.core_tokens & candidate.profile.core_tokens
    shared_phrase = product_profile.phrases & candidate.profile.phrases
    shared_engine = product_profile.engines & candidate.profile.engines
    union = product_profile.core_tokens | candidate.profile.core_tokens
    core_ratio = (len(shared_core) / len(union)) if union else 0.0
    fingerprint_ratio = SequenceMatcher(
        None,
        product_profile.fingerprint,
        candidate.profile.fingerprint,
    ).ratio()

    score = (core_ratio * 1.8) + (fingerprint_ratio * 0.45)
    score += len(shared_core) * 0.18
    score += len(shared_phrase) * 0.60
    score += len(shared_engine) * 0.40

    if product_family != "generic":
        if candidate.family == product_family:
            score += 1.15
        elif candidate.family == "generic":
            score -= 0.35

    if product_kind != "generic":
        if candidate.kind == product_kind:
            score += 1.25
        elif candidate.group == product_group:
            score += 0.55
        elif candidate.kind != "generic":
            score -= 0.75
    elif product_group != "generic":
        if candidate.group == product_group:
            score += 0.35
        elif candidate.group != "generic":
            score -= 0.25

    if product_profile.year_span and candidate.profile.year_span:
        if _year_spans_overlap(product_profile.year_span, candidate.profile.year_span):
            score += 0.45
        else:
            score -= 0.45

    if product_profile.phrases and candidate.profile.phrases and not shared_phrase and product_kind == candidate.kind:
        score -= 0.20

    if not shared_core and not shared_phrase and candidate.kind != product_kind and candidate.group != product_group:
        return None

    return score


def _choose_loose_fallback_candidate(
    product: Product,
    candidates: List[CsvImageCandidate],
) -> Tuple[Optional[CsvImageCandidate], str]:
    return _choose_diverse_fallback_candidate(product, candidates, image_usage=Counter())


def _choose_diverse_fallback_candidate(
    product: Product,
    candidates: List[CsvImageCandidate],
    *,
    image_usage: Counter[str],
) -> Tuple[Optional[CsvImageCandidate], str]:
    text = f"{product.name} {getattr(product, 'slug', '').replace('-', ' ')}"
    product_profile = _build_product_match_profile(product)
    product_family = _detect_broad_family(text)
    product_kind = _detect_broad_kind(text)
    product_group = _kind_group(product_kind)

    best: Optional[Tuple[float, float, CsvImageCandidate]] = None
    best_reference = ""
    fallback_best: Optional[Tuple[float, CsvImageCandidate]] = None
    fallback_reference = ""

    for candidate in candidates:
        score = _score_diverse_fallback_candidate(
            product_profile,
            product_family=product_family,
            product_kind=product_kind,
            product_group=product_group,
            candidate=candidate,
        )
        if score is None:
            continue

        usage = int(image_usage.get(candidate.image_url, 0))
        diversified_score = score - (usage * 0.85)
        reference = f"diverse:{candidate.family}/{candidate.kind}"
        if fallback_best is None or score > fallback_best[0]:
            fallback_best = (score, candidate)
            fallback_reference = reference
        if best is None or diversified_score > best[0] or (
            diversified_score == best[0] and score > best[1]
        ):
            best = (diversified_score, score, candidate)
            best_reference = reference

    if best and best[1] > 0.0:
        return best[2], best_reference
    if fallback_best and fallback_best[0] > 0.0:
        return fallback_best[1], fallback_reference
    return None, ""


def _build_csv_candidates(rows: Iterable[Dict[str, str]], stats: ImportStats) -> List[CsvImageCandidate]:
    return _build_csv_candidates_with_options(rows, stats, resolver=None)


def _build_csv_candidates_with_options(
    rows: Iterable[Dict[str, str]],
    stats: ImportStats,
    *,
    resolver: Optional[RemoteImageResolver],
) -> List[CsvImageCandidate]:
    candidates: List[CsvImageCandidate] = []
    for handle, group in _iter_shopify_groups(rows):
        ranked_urls = _iter_ranked_group_image_urls(group)
        if not ranked_urls:
            stats.skipped_no_image += 1
            continue
        image_url = _pick_primary_image_url(group, resolver=resolver)
        if not image_url:
            stats.skipped_invalid_image += 1
            continue
        title = _pick_group_title(handle, group)
        vendor = _pick_group_field(group, "Vendor")
        product_type = _pick_group_field(group, "Type")
        years_text = _pick_group_field(group, "Years")
        skus = tuple(_iter_candidate_skus(group))
        match_text = " ".join(
            part for part in (title, handle, product_type, years_text, vendor, " ".join(skus)) if part
        )
        candidate_kind = _detect_broad_kind(match_text)
        candidate = CsvImageCandidate(
            handle=handle,
            handle_slug=slugify(handle),
            title=title,
            vendor=vendor,
            product_type=product_type,
            years_text=years_text,
            image_url=image_url,
            skus=skus,
            profile=_build_name_match_profile(match_text),
            family=_detect_broad_family(match_text),
            kind=candidate_kind,
            group=_kind_group(candidate_kind),
        )
        candidates.append(candidate)
    return candidates


def _decrement_match_stat(stats: ImportStats, source: str) -> None:
    if source == "exact" and stats.matched_exact > 0:
        stats.matched_exact -= 1
    elif source == "name" and stats.matched_name > 0:
        stats.matched_name -= 1
    elif source == "broad" and stats.matched_broad > 0:
        stats.matched_broad -= 1


def _build_product_lookup_maps(products: List[Product]):
    products_by_id: Dict[int, Product] = {product.id: product for product in products}
    products_by_slug: Dict[str, Product] = {
        product.slug: product
        for product in products
        if getattr(product, "slug", "")
    }
    products_by_sku_cf: Dict[str, Product] = {}
    for product in products:
        sku = (getattr(product, "sku", "") or "").strip()
        if sku:
            products_by_sku_cf[sku.casefold()] = product

    option_products_by_sku_cf: Dict[str, Product] = {}
    for sku, product_id in (
        ProductOption.objects.exclude(sku__isnull=True)
        .exclude(sku="")
        .values_list("sku", "product_id")
    ):
        if not sku:
            continue
        product = products_by_id.get(int(product_id))
        if product:
            option_products_by_sku_cf[str(sku).strip().casefold()] = product

    return products_by_slug, products_by_sku_cf, option_products_by_sku_cf


def _find_product_exact_match(
    candidate: CsvImageCandidate,
    *,
    products_by_slug: Dict[str, Product],
    products_by_sku_cf: Dict[str, Product],
    option_products_by_sku_cf: Dict[str, Product],
) -> Tuple[Optional[Product], str]:
    product = products_by_slug.get(candidate.handle_slug)
    if product:
        return product, f"slug:{candidate.handle_slug}"

    product = (
        products_by_sku_cf.get(candidate.handle.casefold())
        or products_by_sku_cf.get(candidate.handle_slug.casefold())
    )
    if product:
        return product, f"sku:{candidate.handle}"

    for sku in candidate.skus:
        sku_slug = slugify(sku)
        if sku_slug:
            product = products_by_slug.get(sku_slug)
            if product:
                return product, f"slug:{sku_slug}"

    for sku in candidate.skus:
        product = products_by_sku_cf.get(sku.casefold())
        if product:
            return product, f"sku:{sku}"

    for sku in candidate.skus:
        product = option_products_by_sku_cf.get(sku.casefold())
        if product:
            return product, f"option_sku:{sku}"

    return None, ""


class Command(BaseCommand):
    help = (
        "Import product main images from a Shopify-like CSV (e.g. DDC load file). "
        "Updates existing products only and stores remote URLs directly in Product.main_image."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="",
            help="Path to a CSV file (inside the container). Use --stdin to stream data instead.",
        )
        parser.add_argument(
            "--stdin",
            action="store_true",
            help="Read CSV from stdin (recommended for Dokku runs).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse + match, but do not write to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional max number of products to update (0 = no limit).",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=25,
            help="Show up to N planned updates/misses in output (default: 25).",
        )
        parser.add_argument(
            "--only-current-image",
            default="",
            help="Restrict updates to products whose current Product.main_image exactly matches this value.",
        )
        parser.add_argument(
            "--only-current-prefix",
            default="",
            help="Restrict updates to products whose current Product.main_image starts with this prefix.",
        )
        parser.add_argument(
            "--match-by-name",
            action="store_true",
            help=(
                "After exact slug/SKU matching, try a conservative product-name match against the CSV Title/Handle. "
                "Recommended for placeholder cleanup where slugs differ."
            ),
        )
        parser.add_argument(
            "--name-min-score",
            type=float,
            default=0.68,
            help="Minimum score for --match-by-name (default: 0.68). Higher is safer.",
        )
        parser.add_argument(
            "--name-min-margin",
            type=float,
            default=0.08,
            help="Minimum gap between the best and second-best name match (default: 0.08).",
        )
        parser.add_argument(
            "--broad-fallback",
            action="store_true",
            help=(
                "After exact/name matching, assign a broader family/type-based image from the CSV. "
                "Use only when approximate visual coverage is preferred over exactness."
            ),
        )
        parser.add_argument(
            "--include-broken-current",
            action="store_true",
            help=(
                "Also target products whose current remote main_image URL is broken. "
                "Implies remote URL validation for the current image."
            ),
        )
        parser.add_argument(
            "--validate-remote-images",
            action="store_true",
            help=(
                "Validate candidate remote image URLs before assigning them. "
                "Broken or non-image URLs are skipped."
            ),
        )
        parser.add_argument(
            "--download-images",
            action="store_true",
            help=(
                "Download selected remote images into Django storage and save local paths instead of raw external URLs."
            ),
        )
        parser.add_argument(
            "--url-timeout",
            type=float,
            default=8.0,
            help="Timeout in seconds for remote image validation/download (default: 8.0).",
        )

    def handle(self, *args, **options):
        csv_path = (options.get("csv_path") or "").strip()
        use_stdin = bool(options.get("stdin"))
        dry_run = bool(options.get("dry_run"))
        limit = int(options.get("limit") or 0)
        show = int(options.get("show") or 0)
        only_current_image = (options.get("only_current_image") or "").strip()
        only_current_prefix = (options.get("only_current_prefix") or "").strip()
        match_by_name = bool(options.get("match_by_name"))
        name_min_score = float(options.get("name_min_score") or 0.0)
        name_min_margin = float(options.get("name_min_margin") or 0.0)
        broad_fallback = bool(options.get("broad_fallback"))
        include_broken_current = bool(options.get("include_broken_current"))
        validate_remote_images = bool(options.get("validate_remote_images"))
        download_images = bool(options.get("download_images"))
        url_timeout = float(options.get("url_timeout") or 0.0)

        if only_current_image and only_current_prefix:
            raise CommandError("Use only one of --only-current-image and --only-current-prefix.")

        if not use_stdin and not csv_path:
            raise CommandError("Provide --csv PATH or use --stdin.")

        raw = ""
        if use_stdin:
            raw = sys.stdin.read()
            if not raw.strip():
                raise CommandError("No CSV data on stdin.")
        else:
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                    raw = f.read()
            except FileNotFoundError as exc:
                raise CommandError(str(exc)) from exc
            if not raw.strip():
                raise CommandError(f"CSV file is empty: {csv_path}")

        reader = csv.DictReader(raw.splitlines(True))
        fieldnames = [str(name).strip() for name in (reader.fieldnames or [])]
        if "Handle" not in fieldnames and "Title" not in fieldnames:
            raise CommandError("CSV missing Handle/Title columns (Shopify-like format expected).")
        if "Image Src" not in fieldnames and "Variant Image" not in fieldnames:
            raise CommandError("CSV missing Image Src/Variant Image column.")

        stats = ImportStats()
        missing: List[Tuple[str, str, str]] = []
        low_confidence: List[Tuple[Product, NameMatchResult]] = []
        planned_updates: List[PlannedUpdate] = []
        planned_image_usage: Counter[str] = Counter()
        handled_product_ids = set()
        resolver = RemoteImageResolver(
            timeout=url_timeout,
            validate=(validate_remote_images or include_broken_current or download_images),
            localize=download_images,
        )

        candidates = _build_csv_candidates_with_options(reader, stats, resolver=resolver)

        all_products = list(Product.objects.select_related("category").all())
        has_product_filter = bool(only_current_image or only_current_prefix or include_broken_current)
        if has_product_filter:
            products: List[Product] = []
            for product in all_products:
                current = str(getattr(product, "main_image", "") or "").strip()
                matches = False
                if only_current_image and current == only_current_image:
                    matches = True
                if only_current_prefix and current.startswith(only_current_prefix):
                    matches = True
                if include_broken_current and _is_remote_image_value(current) and not resolver.is_usable(current):
                    matches = True
                if matches:
                    products.append(product)
        else:
            products = all_products

        products_by_slug, products_by_sku_cf, option_products_by_sku_cf = _build_product_lookup_maps(products)

        for candidate in candidates:
            if limit and len(planned_updates) >= limit:
                break

            product, reference = _find_product_exact_match(
                candidate,
                products_by_slug=products_by_slug,
                products_by_sku_cf=products_by_sku_cf,
                option_products_by_sku_cf=option_products_by_sku_cf,
            )
            if not product:
                sku_sample = candidate.skus[0] if candidate.skus else ""
                missing.append((candidate.handle, candidate.handle_slug, sku_sample))
                continue
            if product.id in handled_product_ids:
                continue
            if _is_merch_product(product):
                stats.skipped_merch += 1
                handled_product_ids.add(product.id)
                continue

            handled_product_ids.add(product.id)
            current = str(getattr(product, "main_image", "") or "").strip()
            if current == candidate.image_url:
                stats.unchanged += 1
                stats.matched_exact += 1
                continue

            planned_updates.append(
                PlannedUpdate(
                    product=product,
                    image_url=candidate.image_url,
                    source="exact",
                    reference=reference or candidate.handle_slug,
                )
            )
            planned_image_usage[candidate.image_url] += 1
            stats.matched_exact += 1

        if match_by_name and (not limit or len(planned_updates) < limit):
            products_for_matching = sorted(products, key=_product_match_specificity, reverse=True)
            for product in products_for_matching:
                if limit and len(planned_updates) >= limit:
                    break
                if product.id in handled_product_ids:
                    continue
                if _is_merch_product(product):
                    stats.skipped_merch += 1
                    handled_product_ids.add(product.id)
                    continue

                result = _find_best_name_match(product, candidates)
                handled_product_ids.add(product.id)
                if result and result.score >= name_min_score and result.margin >= name_min_margin:
                    current = str(getattr(product, "main_image", "") or "").strip()
                    if current == result.candidate.image_url:
                        stats.unchanged += 1
                        stats.matched_name += 1
                        continue

                    planned_updates.append(
                        PlannedUpdate(
                            product=product,
                            image_url=result.candidate.image_url,
                            source="name",
                            reference=result.candidate.title or result.candidate.handle,
                        )
                    )
                    planned_image_usage[result.candidate.image_url] += 1
                    stats.matched_name += 1
                    continue

                if broad_fallback:
                    broad_candidate, broad_reference = _choose_diverse_fallback_candidate(
                        product,
                        candidates,
                        image_usage=planned_image_usage,
                    )
                    if not broad_candidate:
                        broad_candidate, broad_reference = _choose_broad_fallback_candidate(product, candidates)
                    if broad_candidate:
                        current = str(getattr(product, "main_image", "") or "").strip()
                        if current == broad_candidate.image_url:
                            stats.unchanged += 1
                            stats.matched_broad += 1
                            continue

                        planned_updates.append(
                            PlannedUpdate(
                                product=product,
                                image_url=broad_candidate.image_url,
                                source="broad",
                                reference=f"{broad_reference} -> {broad_candidate.title or broad_candidate.handle}",
                            )
                        )
                        planned_image_usage[broad_candidate.image_url] += 1
                        stats.matched_broad += 1
                        continue

                stats.skipped_low_confidence += 1
                if result:
                    low_confidence.append((product, result))
                continue

        stats.skipped_missing = len(missing)

        if download_images and planned_updates and not dry_run:
            localized_updates: List[PlannedUpdate] = []
            for item in planned_updates:
                try:
                    image_value = resolver.localize(item.image_url)
                except Exception:
                    stats.skipped_download_failed += 1
                    _decrement_match_stat(stats, item.source)
                    continue
                current = str(getattr(item.product, "main_image", "") or "").strip()
                if current == image_value:
                    stats.unchanged += 1
                    _decrement_match_stat(stats, item.source)
                    continue
                localized_updates.append(
                    PlannedUpdate(
                        product=item.product,
                        image_url=image_value,
                        source=item.source,
                        reference=item.reference,
                    )
                )
            planned_updates = localized_updates

        if show:
            self.stdout.write("")
            self.stdout.write("Planned updates (sample):")
            for item in planned_updates[:show]:
                category_slug = getattr(getattr(item.product, "category", None), "slug", "") or ""
                self.stdout.write(
                    f"- {item.product.slug} (sku={item.product.sku}, cat={category_slug}, via={item.source}) "
                    f"-> {item.image_url} [{item.reference}]"
                )
            if missing:
                self.stdout.write("")
                self.stdout.write("Exact-match misses (sample):")
                for handle, slug, sku in missing[:show]:
                    self.stdout.write(f"- handle={handle!r} slug={slug!r} sku={sku!r}")
            if low_confidence:
                self.stdout.write("")
                self.stdout.write("Low-confidence name matches (sample):")
                for product, result in low_confidence[:show]:
                    self.stdout.write(
                        f"- {product.slug} -> {result.candidate.handle!r} "
                        f"(score={result.score:.3f}, margin={result.margin:.3f})"
                    )

        if dry_run:
            self.stdout.write("")
            self.stdout.write("Dry run: no database changes were made.")
            self._print_summary(stats, planned_updates)
            return

        if not planned_updates:
            self.stdout.write("No updates to apply.")
            self._print_summary(stats, planned_updates)
            return

        for item in planned_updates:
            item.product.main_image = item.image_url

        with transaction.atomic():
            Product.objects.bulk_update([item.product for item in planned_updates], ["main_image"])

        stats.updated = len(planned_updates)
        self.stdout.write("Applied updates.")
        self._print_summary(stats, planned_updates)

    def _print_summary(self, stats: ImportStats, planned_updates: List[PlannedUpdate]):
        self.stdout.write("")
        self.stdout.write("Summary:")
        self.stdout.write(f"- will_update/updated: {len(planned_updates)}")
        self.stdout.write(f"- unchanged: {stats.unchanged}")
        self.stdout.write(f"- matched_exact: {stats.matched_exact}")
        self.stdout.write(f"- matched_name: {stats.matched_name}")
        self.stdout.write(f"- matched_broad: {stats.matched_broad}")
        self.stdout.write(f"- skipped_merch: {stats.skipped_merch}")
        self.stdout.write(f"- skipped_no_image: {stats.skipped_no_image}")
        self.stdout.write(f"- skipped_invalid_image: {stats.skipped_invalid_image}")
        self.stdout.write(f"- skipped_missing_product: {stats.skipped_missing}")
        self.stdout.write(f"- skipped_low_confidence: {stats.skipped_low_confidence}")
        self.stdout.write(f"- skipped_download_failed: {stats.skipped_download_failed}")
