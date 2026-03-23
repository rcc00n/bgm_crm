from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from store.models import Product

from .types import ProductMatch, SourceProduct

NAME_STOPWORDS = {
    "a",
    "adapter",
    "and",
    "customs",
    "ddc",
    "diesel",
    "dirty",
    "for",
    "kit",
    "only",
    "or",
    "the",
    "universal",
    "with",
}
LEADING_NAME_PREFIX_TOKENS = frozenset({"chaos", "custom", "dieselr", "gdp", "tuning"})
RELAXED_EXACT_PREFIX_TOKENS = frozenset({"efilive", "ezlynk"})
FAMILY_ALIASES = {
    "cummins": frozenset({"cummins", "dodge", "ram"}),
    "duramax": frozenset({"duramax", "gm", "gmc", "chevy", "chevrolet"}),
    "ecodiesel": frozenset({"ecodiesel", "jeep", "gladiator"}),
    "powerstroke": frozenset({"powerstroke", "ford"}),
    "titan": frozenset({"nissan", "titan"}),
}
ENGINE_TOKENS = frozenset({"lb7", "lbz", "lly", "lmm", "lml", "lm2", "l5p", "lz0", "6.0l", "6.4l", "6.6l", "6.7l"})
PLATFORM_TOKENS = frozenset(
    {
        "autoagent3",
        "commander",
        "cts2",
        "efilive",
        "ezlynk",
        "flashscan",
        "mm3",
        "mpvi3",
        "mpvi4",
        "rtd4",
        "sct",
    }
)
TRANSMISSION_TOKENS = frozenset({"68rfe", "aisin", "t87a", "t93", "tcm", "transmission", "transtune"})
PACKAGE_TOKENS = frozenset({"4week", "doubletune", "fullsupport", "lifetime", "singletune", "sotf", "stockfile"})
EXHAUST_VARIANT_TOKENS = frozenset(
    {
        "cabchassis",
        "downpipeback",
        "nomuffler",
        "scr",
        "stockmuffler",
        "stocktailpipe",
        "turboback",
        "urea",
        "withmuffler",
    }
)
VENDOR_TOKENS = frozenset({"chaos", "dieselr", "gdp"})
TEXT_REPLACEMENTS = (
    ("auto agent 3", "autoagent3"),
    ("cab and chassis", "cabchassis"),
    ("cab & chassis", "cabchassis"),
    ("double tune", "doubletune"),
    ("downpipe back", "downpipeback"),
    ("eco diesel", "ecodiesel"),
    ("efi live", "efilive"),
    ("ez lynk", "ezlynk"),
    ("full support", "fullsupport"),
    ("lifetime support", "lifetime"),
    ("no muffler", "nomuffler"),
    ("without muffler", "nomuffler"),
    ("4 week", "4week"),
    ("single tune", "singletune"),
    ("stock file", "stockfile"),
    ("stock muffler", "stockmuffler"),
    ("stock tailpipe", "stocktailpipe"),
    ("support pack", "supportpack"),
    ("trans tune", "transtune"),
    ("turbo back", "turboback"),
    ("with muffler", "withmuffler"),
)
YEAR_RANGE_RE = re.compile(r"\b(19\d{2}|20\d{2})(?:\.\d+)?\s*[-/]\s*(19\d{2}|20\d{2})(?:\.\d+)?\b")
YEAR_PLUS_RE = re.compile(r"\b(19\d{2}|20\d{2})(?:\.\d+)?\s*\+\b")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
PLACEHOLDER_NAME_RE = re.compile(r"^product-\d+(?:-\d+)?$", re.IGNORECASE)
MIN_NAME_SCORE = 0.92
MIN_NAME_MARGIN = 0.05


@dataclass(frozen=True)
class NameProfile:
    exact_name_key: str
    relaxed_exact_name_key: str
    fingerprint: str
    tokens: frozenset[str]
    core_tokens: frozenset[str]
    families: frozenset[str]
    engines: frozenset[str]
    platform_tokens: frozenset[str]
    transmission_tokens: frozenset[str]
    package_tokens: frozenset[str]
    exhaust_variant_tokens: frozenset[str]
    vendor_tokens: frozenset[str]
    year_span: tuple[int, int] | None


@dataclass(frozen=True)
class SourceCandidate:
    source: SourceProduct
    profile: NameProfile


def normalize_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def normalize_compact_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def build_sku_index(source_products: list[SourceProduct]) -> dict[str, tuple[SourceProduct, ...]]:
    grouped: dict[str, list[SourceProduct]] = defaultdict(list)
    for item in source_products:
        key = normalize_code(item.sku)
        if key:
            grouped[key].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def build_compact_sku_index(source_products: list[SourceProduct]) -> dict[str, tuple[SourceProduct, ...]]:
    grouped: dict[str, list[SourceProduct]] = defaultdict(list)
    for item in source_products:
        key = normalize_compact_code(item.sku)
        if key:
            grouped[key].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def build_name_index(
    source_products: list[SourceProduct],
) -> tuple[
    list[SourceCandidate],
    dict[str, tuple[SourceCandidate, ...]],
    dict[str, tuple[SourceCandidate, ...]],
]:
    candidates: list[SourceCandidate] = []
    token_index: dict[str, list[SourceCandidate]] = defaultdict(list)
    exact_name_index: dict[str, list[SourceCandidate]] = defaultdict(list)
    for item in source_products:
        profile = build_name_profile(
            item.product_name,
            item.variant_name if item.variant_name != "Default Title" else "",
            item.supplier_name,
            item.sku,
            item.supplier_category,
            " ".join(item.tags),
        )
        candidate = SourceCandidate(source=item, profile=profile)
        candidates.append(candidate)
        for token in profile.core_tokens:
            token_index[token].append(candidate)
        for key in {profile.exact_name_key, profile.relaxed_exact_name_key}:
            if key:
                exact_name_index[key].append(candidate)
    return (
        candidates,
        {key: tuple(value) for key, value in token_index.items()},
        {key: tuple(value) for key, value in exact_name_index.items()},
    )


def match_catalog_product(
    product: Product,
    *,
    source_by_sku: dict[str, tuple[SourceProduct, ...]],
    source_by_compact_sku: dict[str, tuple[SourceProduct, ...]],
    source_candidates: list[SourceCandidate],
    token_index: dict[str, tuple[SourceCandidate, ...]],
    exact_name_index: dict[str, tuple[SourceCandidate, ...]],
    allow_name_match: bool = False,
    allow_embedded_code_match: bool = False,
) -> ProductMatch:
    sku_key = normalize_code(product.sku)
    exact = source_by_sku.get(sku_key) or ()
    if len(exact) == 1:
        return ProductMatch(confidence="high", reason="exact_sku", source=exact[0])
    if len(exact) > 1:
        return ProductMatch(
            confidence="medium",
            reason="ambiguous_exact_sku",
            source=exact[0],
            alternatives=exact[:3],
        )

    compact_key = normalize_compact_code(product.sku)
    compact = source_by_compact_sku.get(compact_key) or ()
    if compact_key and len(compact) == 1:
        return ProductMatch(confidence="high", reason="exact_compact_sku", source=compact[0])
    if compact_key and len(compact) > 1:
        return ProductMatch(
            confidence="medium",
            reason="ambiguous_compact_sku",
            source=compact[0],
            alternatives=compact[:3],
        )

    if allow_embedded_code_match and source_by_compact_sku:
        embedded_match = _match_by_embedded_sku(
            product,
            source_by_compact_sku=source_by_compact_sku,
        )
        if embedded_match is not None:
            return embedded_match

    if not allow_name_match:
        return ProductMatch(confidence="low", reason="no_exact_sku")

    profile = build_name_profile(
        product.name,
        product.sku,
        getattr(product, "slug", "") or "",
        getattr(product.category, "name", "") or "",
        getattr(product.category, "slug", "").replace("-", " "),
    )
    if not profile.core_tokens or PLACEHOLDER_NAME_RE.match((product.name or "").strip()):
        return ProductMatch(confidence="low", reason="blank_or_placeholder_name")

    exact_name_candidates = tuple(exact_name_index.get(profile.exact_name_key) or ())
    exact_name_match = _match_by_exact_name(profile, exact_name_candidates)
    if exact_name_match is not None:
        return exact_name_match
    if profile.relaxed_exact_name_key and profile.relaxed_exact_name_key != profile.exact_name_key:
        relaxed_candidates = tuple(exact_name_index.get(profile.relaxed_exact_name_key) or ())
        relaxed_match = _match_by_exact_name(profile, relaxed_candidates)
        if relaxed_match is not None:
            return relaxed_match

    candidates = _candidate_pool(profile, source_candidates=source_candidates, token_index=token_index)
    if not candidates:
        return ProductMatch(confidence="low", reason="no_name_candidates")

    scored: list[tuple[float, SourceCandidate]] = []
    for candidate in candidates:
        score = _score_name_match(profile, candidate.profile)
        if score is None:
            continue
        scored.append((score, candidate))
    if not scored:
        return ProductMatch(confidence="low", reason="no_name_match")

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_candidate = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= MIN_NAME_SCORE and (best_score - runner_up_score) >= MIN_NAME_MARGIN:
        return ProductMatch(
            confidence="medium",
            reason="normalized_name",
            source=best_candidate.source,
        )
    return ProductMatch(
        confidence="medium",
        reason="ambiguous_name_match",
        source=best_candidate.source,
        alternatives=tuple(item[1].source for item in scored[:3]),
    )


def _match_by_embedded_sku(
    product: Product,
    *,
    source_by_compact_sku: dict[str, tuple[SourceProduct, ...]],
) -> ProductMatch | None:
    name_key = normalize_compact_code(product.name)
    sku_key = normalize_compact_code(product.sku)
    if not name_key:
        return None

    matches: list[tuple[str, tuple[SourceProduct, ...]]] = []
    for compact_key, candidates in source_by_compact_sku.items():
        if len(compact_key) < 8:
            continue
        if compact_key == sku_key:
            continue
        if compact_key in name_key:
            matches.append((compact_key, candidates))

    if not matches:
        return None

    matches.sort(key=lambda item: len(item[0]), reverse=True)
    longest_key, longest_candidates = matches[0]
    remaining_keys = [key for key, _candidates in matches[1:]]

    if len(longest_candidates) == 1 and (not remaining_keys or all(key in longest_key for key in remaining_keys)):
        return ProductMatch(
            confidence="high",
            reason="embedded_source_sku",
            source=longest_candidates[0],
        )

    alternatives: list[SourceProduct] = []
    seen = set()
    for _key, candidates in matches:
        for candidate in candidates:
            identity = (candidate.product_id, candidate.variant_id, candidate.sku)
            if identity in seen:
                continue
            seen.add(identity)
            alternatives.append(candidate)
            if len(alternatives) >= 3:
                break
        if len(alternatives) >= 3:
            break
    return ProductMatch(
        confidence="medium",
        reason="ambiguous_embedded_source_sku",
        source=alternatives[0] if alternatives else longest_candidates[0],
        alternatives=tuple(alternatives),
    )


def build_name_profile(*parts: str) -> NameProfile:
    raw = " ".join(part for part in parts if part)
    primary_name = str(parts[0] or "") if parts else ""
    tokens = tuple(_tokenize(raw))
    token_set = frozenset(tokens)
    family_alias_tokens = frozenset(alias for aliases in FAMILY_ALIASES.values() for alias in aliases)
    families = frozenset(
        family
        for family, aliases in FAMILY_ALIASES.items()
        if token_set & aliases
    )
    engines = frozenset(token for token in token_set if token in ENGINE_TOKENS or re.fullmatch(r"\d\.\dl", token))
    core_tokens = frozenset(
        token
        for token in token_set
        if token not in NAME_STOPWORDS
        and token not in family_alias_tokens
        and not YEAR_RE.fullmatch(token)
        and len(token) >= 3
    )
    fingerprint = " ".join(sorted(core_tokens))
    return NameProfile(
        exact_name_key=_exact_name_key(primary_name),
        relaxed_exact_name_key=_relaxed_exact_name_key(primary_name),
        fingerprint=fingerprint,
        tokens=token_set,
        core_tokens=core_tokens,
        families=families,
        engines=engines,
        platform_tokens=frozenset(token for token in token_set if token in PLATFORM_TOKENS),
        transmission_tokens=frozenset(token for token in token_set if token in TRANSMISSION_TOKENS),
        package_tokens=frozenset(token for token in token_set if token in PACKAGE_TOKENS),
        exhaust_variant_tokens=frozenset(token for token in token_set if token in EXHAUST_VARIANT_TOKENS),
        vendor_tokens=frozenset(token for token in token_set if token in VENDOR_TOKENS),
        year_span=_extract_year_span(raw),
    )


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ")
    for source, target in TEXT_REPLACEMENTS:
        text = text.replace(source, target)
    text = re.sub(r"(\d)\.(\d)l\b", r"\1.\2l", text)
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(value: str) -> list[str]:
    return [token for token in _normalize_text(value).split() if token]


def _extract_year_span(value: str) -> tuple[int, int] | None:
    starts: list[int] = []
    ends: list[int] = []
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


def _candidate_pool(
    profile: NameProfile,
    *,
    source_candidates: list[SourceCandidate],
    token_index: dict[str, tuple[SourceCandidate, ...]],
) -> list[SourceCandidate]:
    ranked_tokens = sorted(
        profile.core_tokens,
        key=lambda token: (len(token_index.get(token) or ()), token),
    )
    selected = [token for token in ranked_tokens if token in token_index][:5]
    if not selected:
        return source_candidates
    pool: list[SourceCandidate] = []
    seen = set()
    for token in selected:
        for candidate in token_index.get(token) or ():
            key = candidate.source.variant_id or candidate.source.product_id
            if key in seen:
                continue
            seen.add(key)
            pool.append(candidate)
    return pool


def _exact_name_key(value: str) -> str:
    tokens = _tokenize(value)
    return _strip_leading_tokens(tokens, LEADING_NAME_PREFIX_TOKENS)


def _relaxed_exact_name_key(value: str) -> str:
    tokens = _tokenize(value)
    key = _strip_leading_tokens(tokens, LEADING_NAME_PREFIX_TOKENS)
    if not key:
        return ""
    relaxed_tokens = key.split()
    return _strip_leading_tokens(relaxed_tokens, RELAXED_EXACT_PREFIX_TOKENS)


def _strip_leading_tokens(tokens: list[str], allowed: frozenset[str]) -> str:
    parts = list(tokens)
    while parts and parts[0] in allowed:
        parts.pop(0)
    return " ".join(parts)


def _match_by_exact_name(
    product_profile: NameProfile,
    candidates: tuple[SourceCandidate, ...],
) -> ProductMatch | None:
    if not candidates or not product_profile.exact_name_key:
        return None

    compatible = [candidate for candidate in candidates if _critical_groups_compatible(product_profile, candidate.profile)]
    if not compatible:
        return None
    vendor_preferred = [
        candidate for candidate in compatible
        if product_profile.vendor_tokens and (product_profile.vendor_tokens & candidate.profile.vendor_tokens)
    ]
    if vendor_preferred:
        compatible = vendor_preferred
    if len(compatible) == 1:
        return ProductMatch(confidence="high", reason="exact_name", source=compatible[0].source)

    product_ids = {candidate.source.product_id for candidate in compatible if candidate.source.product_id}
    product_urls = {candidate.source.product_page_url for candidate in compatible if candidate.source.product_page_url}
    primary_images = {
        candidate.source.image_urls[0]
        for candidate in compatible
        if candidate.source.image_urls
    }
    if len(product_ids) == 1 and product_ids:
        return ProductMatch(confidence="high", reason="exact_name_same_product", source=compatible[0].source)
    if len(product_urls) == 1 and product_urls:
        return ProductMatch(confidence="high", reason="exact_name_same_page", source=compatible[0].source)
    if len(primary_images) == 1 and primary_images:
        return ProductMatch(confidence="high", reason="exact_name_shared_primary_image", source=compatible[0].source)
    return ProductMatch(
        confidence="medium",
        reason="ambiguous_exact_name",
        source=compatible[0].source,
        alternatives=tuple(candidate.source for candidate in compatible[:3]),
    )


def _critical_groups_compatible(product_profile: NameProfile, candidate_profile: NameProfile) -> bool:
    grouped_tokens = (
        (product_profile.platform_tokens, candidate_profile.platform_tokens),
        (product_profile.transmission_tokens, candidate_profile.transmission_tokens),
        (product_profile.package_tokens, candidate_profile.package_tokens),
        (product_profile.exhaust_variant_tokens, candidate_profile.exhaust_variant_tokens),
    )
    for left, right in grouped_tokens:
        if left and right and left.isdisjoint(right):
            return False
    return True


def _score_name_match(product_profile: NameProfile, candidate_profile: NameProfile) -> float | None:
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
    if (
        product_profile.year_span
        and candidate_profile.year_span
        and not _year_spans_overlap(product_profile.year_span, candidate_profile.year_span)
    ):
        return None
    if not _critical_groups_compatible(product_profile, candidate_profile):
        return None

    shared_core = product_profile.core_tokens & candidate_profile.core_tokens
    if not shared_core:
        return None

    union = product_profile.core_tokens | candidate_profile.core_tokens
    core_ratio = len(shared_core) / len(union) if union else 0.0
    fingerprint_ratio = SequenceMatcher(
        None,
        product_profile.fingerprint,
        candidate_profile.fingerprint,
    ).ratio()

    score = (core_ratio * 0.68) + (fingerprint_ratio * 0.24)
    if product_profile.families and candidate_profile.families:
        score += 0.04 * len(product_profile.families & candidate_profile.families)
    if product_profile.engines and candidate_profile.engines:
        score += 0.02 * len(product_profile.engines & candidate_profile.engines)
    if (
        product_profile.year_span
        and candidate_profile.year_span
        and _year_spans_overlap(product_profile.year_span, candidate_profile.year_span)
    ):
        score += 0.06
    if product_profile.platform_tokens and candidate_profile.platform_tokens:
        score += 0.08 * len(product_profile.platform_tokens & candidate_profile.platform_tokens)
    if product_profile.transmission_tokens and candidate_profile.transmission_tokens:
        score += 0.05 * len(product_profile.transmission_tokens & candidate_profile.transmission_tokens)
    if product_profile.package_tokens and candidate_profile.package_tokens:
        score += 0.04 * len(product_profile.package_tokens & candidate_profile.package_tokens)
    if product_profile.exhaust_variant_tokens and candidate_profile.exhaust_variant_tokens:
        score += 0.04 * len(product_profile.exhaust_variant_tokens & candidate_profile.exhaust_variant_tokens)
    if product_profile.vendor_tokens and candidate_profile.vendor_tokens:
        score += 0.03 * len(product_profile.vendor_tokens & candidate_profile.vendor_tokens)
    return score


def _year_spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]
