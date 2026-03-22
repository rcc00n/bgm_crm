from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from store.models import Product

from .types import ProductMatch, SourceProduct

NAME_STOPWORDS = {
    "a",
    "and",
    "for",
    "fass",
    "fuel",
    "series",
    "system",
    "systems",
    "the",
    "with",
}


def normalize_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token and token not in NAME_STOPWORDS]
    return " ".join(tokens)


def build_part_number_index(source_products: list[SourceProduct]) -> dict[str, SourceProduct]:
    index: dict[str, SourceProduct] = {}
    for item in source_products:
        key = normalize_code(item.part_number)
        if key and key not in index:
            index[key] = item
    return index


def match_catalog_product(
    product: Product,
    *,
    source_by_part_number: dict[str, SourceProduct],
    source_products: list[SourceProduct],
    allow_name_match: bool = False,
) -> ProductMatch:
    sku_key = normalize_code(product.sku)
    if sku_key and sku_key in source_by_part_number:
        return ProductMatch(
            confidence="high",
            reason="exact_sku",
            source=source_by_part_number[sku_key],
        )

    if not allow_name_match:
        return ProductMatch(confidence="low", reason="no_exact_sku")

    product_name = normalize_name(product.name)
    if not product_name:
        return ProductMatch(confidence="low", reason="blank_product_name")

    scored: list[tuple[float, SourceProduct]] = []
    for candidate in source_products:
        candidate_name = normalize_name(candidate.name)
        if not candidate_name:
            continue
        ratio = SequenceMatcher(None, product_name, candidate_name).ratio()
        if product_name == candidate_name:
            ratio = 1.0
        if ratio >= 0.92:
            scored.append((ratio, candidate))

    if not scored:
        return ProductMatch(confidence="low", reason="no_name_match")

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_source = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.98 and (best_score - runner_up) >= 0.02:
        return ProductMatch(
            confidence="medium",
            reason="normalized_name",
            source=best_source,
        )
    return ProductMatch(
        confidence="medium",
        reason="ambiguous_name_match",
        source=best_source,
        alternatives=tuple(item[1] for item in scored[:3]),
    )
