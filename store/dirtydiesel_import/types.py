from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceProduct:
    product_id: int
    variant_id: int
    sku: str
    product_name: str
    variant_name: str
    supplier_name: str
    supplier_category: str
    product_page_url: str
    image_urls: tuple[str, ...]
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductMatch:
    confidence: str
    reason: str
    source: SourceProduct | None = None
    alternatives: tuple[SourceProduct, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.to_dict() if self.source else None
        data["alternatives"] = [item.to_dict() for item in self.alternatives]
        return data


@dataclass
class ImportReport:
    summary: dict[str, int] = field(default_factory=dict)
    updated_products: list[dict[str, Any]] = field(default_factory=list)
    ambiguous_matches: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    debug_files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "updated_products": self.updated_products,
            "ambiguous_matches": self.ambiguous_matches,
            "failures": self.failures,
            "assumptions": self.assumptions,
            "debug_files": self.debug_files,
        }
