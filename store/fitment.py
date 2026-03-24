from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from django.db import transaction

from .models import CarMake, CarModel

UNIVERSAL_COMPATIBILITY_NOTE = (
    "Universal fit unless otherwise stated in the product title. "
    "Confirm final compatibility for your build before purchase."
)
COMMERCIAL_COMPATIBILITY_NOTE = (
    "Commercial / Class 8 application. Consumer truck and SUV fitment filters do not apply."
)
AUTO_GENERATED_COMPATIBILITY_NOTES = {
    UNIVERSAL_COMPATIBILITY_NOTE,
    COMMERCIAL_COMPATIBILITY_NOTE,
}


@dataclass(frozen=True)
class VehicleCatalogEntry:
    make: str
    model: str
    year_from: int | None = None
    year_to: int | None = None


@dataclass(frozen=True)
class FitmentSpec:
    make: str
    model: str
    year_from: int | None = None
    year_to: int | None = None


@dataclass(frozen=True)
class FitmentInference:
    kind: str
    specs: tuple[FitmentSpec, ...]
    note: str
    category_name: str | None = None

    @property
    def is_universal(self) -> bool:
        return self.kind == "universal"

    @property
    def is_consumer_specific(self) -> bool:
        return self.kind == "specific"

    @property
    def is_commercial(self) -> bool:
        return self.kind == "commercial"


CONSUMER_VEHICLE_CATALOG: tuple[VehicleCatalogEntry, ...] = (
    VehicleCatalogEntry("Ford", "F-150", 1997, None),
    VehicleCatalogEntry("Ford", "F-250", 1994, None),
    VehicleCatalogEntry("Ford", "F-350", 1994, None),
    VehicleCatalogEntry("Ford", "F-450", 2008, None),
    VehicleCatalogEntry("Ford", "F-550", 2008, None),
    VehicleCatalogEntry("Ford", "Ranger", 2019, None),
    VehicleCatalogEntry("Ford", "Maverick", 2022, None),
    VehicleCatalogEntry("Ford", "Bronco", 2021, None),
    VehicleCatalogEntry("Ford", "Expedition", 1997, None),
    VehicleCatalogEntry("Ford", "Excursion", 2000, 2005),
    VehicleCatalogEntry("Chevy", "Silverado 1500", 1999, None),
    VehicleCatalogEntry("Chevy", "Silverado 2500HD", 2001, None),
    VehicleCatalogEntry("Chevy", "Silverado 3500HD", 2001, None),
    VehicleCatalogEntry("Chevy", "Colorado", 2004, None),
    VehicleCatalogEntry("Chevy", "Tahoe", 1995, None),
    VehicleCatalogEntry("Chevy", "Suburban", 1992, None),
    VehicleCatalogEntry("GMC", "Sierra 1500", 1999, None),
    VehicleCatalogEntry("GMC", "Sierra 2500HD", 2001, None),
    VehicleCatalogEntry("GMC", "Sierra 3500HD", 2001, None),
    VehicleCatalogEntry("GMC", "Canyon", 2004, None),
    VehicleCatalogEntry("GMC", "Yukon", 1992, None),
    VehicleCatalogEntry("GMC", "Yukon XL", 2000, None),
    VehicleCatalogEntry("Ram / Dodge", "1500", 1994, None),
    VehicleCatalogEntry("Ram / Dodge", "2500", 1989, None),
    VehicleCatalogEntry("Ram / Dodge", "3500", 1989, None),
    VehicleCatalogEntry("Ram / Dodge", "4500", 2008, None),
    VehicleCatalogEntry("Ram / Dodge", "5500", 2008, None),
    VehicleCatalogEntry("Toyota", "Tacoma", 1995, None),
    VehicleCatalogEntry("Toyota", "Tundra", 2000, None),
    VehicleCatalogEntry("Toyota", "4Runner", 1990, None),
    VehicleCatalogEntry("Toyota", "Sequoia", 2001, None),
    VehicleCatalogEntry("Toyota", "Land Cruiser", 1991, 2021),
    VehicleCatalogEntry("Jeep", "Gladiator", 2020, None),
    VehicleCatalogEntry("Jeep", "Wrangler", 2007, None),
    VehicleCatalogEntry("Jeep", "Grand Cherokee", 1993, None),
    VehicleCatalogEntry("Jeep", "Cherokee", 2014, 2023),
    VehicleCatalogEntry("Jeep", "Patriot", 2007, 2017),
    VehicleCatalogEntry("Nissan", "Titan", 2004, None),
    VehicleCatalogEntry("Nissan", "Titan XD", 2016, 2024),
    VehicleCatalogEntry("Nissan", "Armada", 2004, None),
)

SPECIFIC_ONLY_VEHICLE_CATALOG: tuple[VehicleCatalogEntry, ...] = (
    VehicleCatalogEntry("Chevy", "C/K 2500", 1988, 2000),
    VehicleCatalogEntry("Chevy", "C/K 3500", 1988, 2000),
    VehicleCatalogEntry("GMC", "Sierra 2500", 1988, 2000),
    VehicleCatalogEntry("GMC", "Sierra 3500", 1988, 2000),
)

FITMENT_CATALOG = CONSUMER_VEHICLE_CATALOG + SPECIFIC_ONLY_VEHICLE_CATALOG
CATALOG_BY_KEY = {(entry.make, entry.model): entry for entry in FITMENT_CATALOG}
ALL_CONSUMER_SPECS = tuple(
    FitmentSpec(
        make=entry.make,
        model=entry.model,
        year_from=entry.year_from,
        year_to=entry.year_to,
    )
    for entry in CONSUMER_VEHICLE_CATALOG
)
ALL_CONSUMER_SPEC_KEYS = {(spec.make, spec.model, spec.year_from, spec.year_to) for spec in ALL_CONSUMER_SPECS}

MODEL_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "ford_all": (
        ("Ford", "F-150"),
        ("Ford", "F-250"),
        ("Ford", "F-350"),
        ("Ford", "F-450"),
        ("Ford", "F-550"),
        ("Ford", "Ranger"),
        ("Ford", "Maverick"),
        ("Ford", "Bronco"),
        ("Ford", "Expedition"),
        ("Ford", "Excursion"),
    ),
    "ford_hd_all": (
        ("Ford", "F-250"),
        ("Ford", "F-350"),
        ("Ford", "F-450"),
        ("Ford", "F-550"),
    ),
    "ford_hd_pickups": (
        ("Ford", "F-250"),
        ("Ford", "F-350"),
    ),
    "ford_hd_chassis": (
        ("Ford", "F-350"),
        ("Ford", "F-450"),
        ("Ford", "F-550"),
    ),
    "gm_all": (
        ("Chevy", "Silverado 1500"),
        ("Chevy", "Silverado 2500HD"),
        ("Chevy", "Silverado 3500HD"),
        ("Chevy", "Colorado"),
        ("Chevy", "Tahoe"),
        ("Chevy", "Suburban"),
        ("GMC", "Sierra 1500"),
        ("GMC", "Sierra 2500HD"),
        ("GMC", "Sierra 3500HD"),
        ("GMC", "Canyon"),
        ("GMC", "Yukon"),
        ("GMC", "Yukon XL"),
    ),
    "gm_hd_all": (
        ("Chevy", "Silverado 2500HD"),
        ("Chevy", "Silverado 3500HD"),
        ("GMC", "Sierra 2500HD"),
        ("GMC", "Sierra 3500HD"),
    ),
    "gm_hd_legacy": (
        ("Chevy", "C/K 2500"),
        ("Chevy", "C/K 3500"),
        ("GMC", "Sierra 2500"),
        ("GMC", "Sierra 3500"),
    ),
    "gm_1500_all": (
        ("Chevy", "Silverado 1500"),
        ("GMC", "Sierra 1500"),
    ),
    "gm_midsize_all": (
        ("Chevy", "Colorado"),
        ("GMC", "Canyon"),
    ),
    "ram_all": (
        ("Ram / Dodge", "1500"),
        ("Ram / Dodge", "2500"),
        ("Ram / Dodge", "3500"),
        ("Ram / Dodge", "4500"),
        ("Ram / Dodge", "5500"),
    ),
    "ram_hd_pickups": (
        ("Ram / Dodge", "2500"),
        ("Ram / Dodge", "3500"),
    ),
    "ram_hd_all": (
        ("Ram / Dodge", "2500"),
        ("Ram / Dodge", "3500"),
        ("Ram / Dodge", "4500"),
        ("Ram / Dodge", "5500"),
    ),
    "toyota_all": (
        ("Toyota", "Tacoma"),
        ("Toyota", "Tundra"),
        ("Toyota", "4Runner"),
        ("Toyota", "Sequoia"),
        ("Toyota", "Land Cruiser"),
    ),
    "jeep_all": (
        ("Jeep", "Gladiator"),
        ("Jeep", "Wrangler"),
        ("Jeep", "Grand Cherokee"),
        ("Jeep", "Cherokee"),
        ("Jeep", "Patriot"),
    ),
    "jeep_ecodiesel": (
        ("Jeep", "Gladiator"),
        ("Jeep", "Wrangler"),
        ("Jeep", "Grand Cherokee"),
    ),
    "nissan_all": (
        ("Nissan", "Titan"),
        ("Nissan", "Titan XD"),
        ("Nissan", "Armada"),
    ),
}

MAKE_MENTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "Ford": re.compile(r"\b(ford|powerstroke|f[- ]?150|f[- ]?250|f[- ]?350|f[- ]?450|f[- ]?550|ranger|maverick|bronco|expedition|excursion)\b", re.I),
    "GM": re.compile(r"\b(gm|gmc|chevy|chevrolet|silverado|sierra|colorado|canyon|tahoe|suburban|yukon|duramax|lm2|l5p|lml|lmm|lb7|lly|lbz|lwn|lz0|dmax)\b", re.I),
    "Ram / Dodge": re.compile(r"\b(ram|dodge|cummins|68rfe|ecodiesel|eco diesel)\b", re.I),
    "Toyota": re.compile(r"\b(toyota|tacoma|tundra|4runner|sequoia|land cruiser|landcruiser)\b", re.I),
    "Jeep": re.compile(r"\b(jeep|gladiator|wrangler|grand cherokee|cherokee|patriot)\b", re.I),
    "Nissan": re.compile(r"\b(nissan|titan xd|titan|armada)\b", re.I),
}

COMMERCIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclass\s*8\b", re.I),
    re.compile(r"\bdetroit\s+dd15\b", re.I),
    re.compile(r"\bcaterpillar\b", re.I),
    re.compile(r"\b(?:cat|caterpillar)\s*(?:3406e|c10|c11|c12|c13|c15|c16|c18)\b", re.I),
    re.compile(r"\bversatile\b", re.I),
)

CODE_PATTERN_GROUPS: tuple[tuple[re.Pattern[str], tuple[tuple[str, str], ...], int | None, int | None], ...] = (
    (re.compile(r"\bdifsfrd1001\b", re.I), MODEL_GROUPS["ford_hd_all"], 2017, 2023),
    (re.compile(r"\bdifsl5p1001\b", re.I), MODEL_GROUPS["gm_hd_all"], 2017, 2019),
    (re.compile(r"\bdifsl5p2001\b", re.I), MODEL_GROUPS["gm_hd_all"], 2020, 2024),
    (re.compile(r"\bdifsram1001\b", re.I), MODEL_GROUPS["ram_hd_pickups"], 2010, 2018),
    (re.compile(r"\bdifsram2001\b", re.I), MODEL_GROUPS["ram_hd_pickups"], 2003, 2007),
    (re.compile(r"\bdifsram3001\b", re.I), MODEL_GROUPS["ram_hd_pickups"], 2007, 2009),
    (re.compile(r"\bdifsram4001\b", re.I), MODEL_GROUPS["ram_hd_pickups"], 2019, 2023),
    (re.compile(r"\bdifscat1001\b", re.I), tuple(), 0, 0),
    (re.compile(r"\bdmax[- ]?700[12]\b", re.I), MODEL_GROUPS["gm_hd_all"], None, None),
)

UNCATEGORIZED_CATEGORY_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bswitch\b", re.I), "Electrical Switches"),
    (
        re.compile(
            r"\b(9th injector|ccv|cp3|egr|grid heater|intake manifold|max intake|pcv|throttle valve)\b",
            re.I,
        ),
        "Motor Vehicle Engine Parts",
    ),
)


def _clean_text(*parts: str) -> str:
    text = " ".join(str(part or "") for part in parts if str(part or "").strip())
    text = text.replace("\xa0", " ")
    return " ".join(text.split())


def _normalize_year_token(raw_value: str | None) -> int | None:
    if not raw_value:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    if value < 100:
        value += 2000 if value <= 35 else 1900
    return value


def extract_year_window(text: str) -> tuple[int | None, int | None]:
    cleaned = _clean_text(text)
    ranges: list[tuple[int, int | None]] = []

    for match in re.finditer(
        r"((?:19|20)?\d{2}(?:\.\d)?)\s*(?:-|to)\s*((?:19|20)?\d{2}(?:\.\d)?)",
        cleaned,
        re.I,
    ):
        year_from = _normalize_year_token(match.group(1))
        year_to = _normalize_year_token(match.group(2))
        if year_from is not None and year_to is not None:
            ranges.append((year_from, year_to))

    for match in re.finditer(r"((?:19|20)?\d{2})\s*\+", cleaned):
        year_from = _normalize_year_token(match.group(1))
        if year_from is not None:
            ranges.append((year_from, None))

    if ranges:
        year_from = min(start for start, _ in ranges)
        bounded_years = [end for _, end in ranges if end is not None]
        year_to = max(bounded_years) if bounded_years else None
        return year_from, year_to

    single_years = [
        _normalize_year_token(match.group(1))
        for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)", cleaned)
    ]
    single_years = [year for year in single_years if year is not None]
    if not single_years:
        return None, None
    return min(single_years), max(single_years)


def _expand_group(group_name: str) -> set[tuple[str, str]]:
    return set(MODEL_GROUPS.get(group_name, ()))


def _add_group(target: set[tuple[str, str]], group_name: str) -> None:
    target.update(_expand_group(group_name))


def _model_token_map(text: str) -> set[tuple[str, str]]:
    lower = text.lower()
    matches: set[tuple[str, str]] = set()

    # Ford
    if re.search(r"\bf[- ]?150\b", lower) or "powerstroke 3.0" in lower:
        matches.add(("Ford", "F-150"))
    if re.search(r"\bf[- ]?250\b", lower):
        matches.add(("Ford", "F-250"))
    if re.search(r"\bf[- ]?350\b", lower):
        matches.add(("Ford", "F-350"))
    if re.search(r"\bf[- ]?450\b", lower):
        matches.add(("Ford", "F-450"))
    if re.search(r"\bf[- ]?550\b", lower):
        matches.add(("Ford", "F-550"))
    for token, model in (
        ("ranger", "Ranger"),
        ("maverick", "Maverick"),
        ("bronco", "Bronco"),
        ("expedition", "Expedition"),
        ("excursion", "Excursion"),
    ):
        if token in lower:
            matches.add(("Ford", model))
    if "powerstroke" in lower or re.search(r"\bford\b", lower):
        if not any(make == "Ford" for make, _ in matches):
            if "3.0l" in lower:
                matches.add(("Ford", "F-150"))
            elif "cab & chassis" in lower or "c&c" in lower:
                _add_group(matches, "ford_hd_chassis")
            else:
                _add_group(matches, "ford_hd_all")

    # GM / Chevy / GMC
    if "colorado" in lower:
        matches.add(("Chevy", "Colorado"))
    if "canyon" in lower:
        matches.add(("GMC", "Canyon"))
    if "tahoe" in lower:
        matches.add(("Chevy", "Tahoe"))
    if "suburban" in lower:
        matches.add(("Chevy", "Suburban"))
    if "yukon xl" in lower:
        matches.add(("GMC", "Yukon XL"))
    elif "yukon" in lower:
        matches.add(("GMC", "Yukon"))
    if "silverado" in lower and "1500" in lower:
        matches.add(("Chevy", "Silverado 1500"))
    if "sierra" in lower and "1500" in lower:
        matches.add(("GMC", "Sierra 1500"))
    if "silverado" in lower and "2500" in lower:
        matches.add(("Chevy", "Silverado 2500HD"))
    if "silverado" in lower and "3500" in lower:
        matches.add(("Chevy", "Silverado 3500HD"))
    if "sierra" in lower and "2500" in lower:
        matches.add(("GMC", "Sierra 2500HD"))
    if "sierra" in lower and "3500" in lower:
        matches.add(("GMC", "Sierra 3500HD"))
    if "gm detroit" in lower or ("detroit" in lower and "gm" in lower):
        _add_group(matches, "gm_hd_all")
    if ("2.8l" in lower and ("duramax" in lower or "gm" in lower)) or "lwn" in lower:
        _add_group(matches, "gm_midsize_all")
    if ("3.0l" in lower and ("lm2" in lower or "lz0" in lower or re.search(r"\b(?:gm|chevy|gmc)\b", lower))) and "1500" in lower:
        _add_group(matches, "gm_1500_all")
    if "duramax" in lower or re.search(r"\b(gm|gmc|chevy|chevrolet|dmax)\b", lower):
        gm_hd_codes = ("lb7", "lly", "lbz", "lmm", "lml", "l5p")
        if any(code in lower for code in gm_hd_codes) or "6.6l" in lower or "2500" in lower or "3500" in lower:
            _add_group(matches, "gm_hd_all")

    # Ram / Dodge
    if "ram 1500" in lower or "dodge 1500" in lower or ("1500" in lower and "ecodiesel" in lower and not any(make == "Ram / Dodge" for make, _ in matches)):
        matches.add(("Ram / Dodge", "1500"))
    if "2500" in lower and ("ram" in lower or "dodge" in lower or "cummins" in lower):
        matches.add(("Ram / Dodge", "2500"))
    if "3500" in lower and ("ram" in lower or "dodge" in lower or "cummins" in lower):
        matches.add(("Ram / Dodge", "3500"))
    if "4500" in lower and ("ram" in lower or "dodge" in lower or "cummins" in lower):
        matches.add(("Ram / Dodge", "4500"))
    if "5500" in lower and ("ram" in lower or "dodge" in lower or "cummins" in lower):
        matches.add(("Ram / Dodge", "5500"))
    if "cummins" in lower or "68rfe" in lower or re.search(r"\b(ram|dodge)\b", lower):
        if not any(make == "Ram / Dodge" for make, _ in matches):
            if "1500" in lower or "ecodiesel" in lower or "eco diesel" in lower:
                matches.add(("Ram / Dodge", "1500"))
            else:
                _add_group(matches, "ram_hd_pickups")
                if "cab & chassis" in lower or "c&c" in lower or "4500" in lower or "5500" in lower:
                    _add_group(matches, "ram_hd_all")

    # Jeep
    for token, model in (
        ("gladiator", "Gladiator"),
        ("wrangler", "Wrangler"),
        ("grand cherokee", "Grand Cherokee"),
        (" cherokee", "Cherokee"),
        ("patriot", "Patriot"),
    ):
        if token in lower:
            matches.add(("Jeep", model))
    if "jeep" in lower and not any(make == "Jeep" for make, _ in matches):
        _add_group(matches, "jeep_ecodiesel")

    # Nissan
    if "titan xd" in lower:
        matches.add(("Nissan", "Titan XD"))
    elif "titan" in lower:
        if "5.0l" in lower or "cummins" in lower:
            matches.add(("Nissan", "Titan XD"))
        else:
            matches.add(("Nissan", "Titan"))
    if "armada" in lower:
        matches.add(("Nissan", "Armada"))
    if "nissan" in lower and not any(make == "Nissan" for make, _ in matches):
        if "5.0l" in lower or "cummins" in lower:
            matches.add(("Nissan", "Titan XD"))
        else:
            _add_group(matches, "nissan_all")

    # Toyota
    for token, model in (
        ("tacoma", "Tacoma"),
        ("tundra", "Tundra"),
        ("4runner", "4Runner"),
        ("sequoia", "Sequoia"),
        ("land cruiser", "Land Cruiser"),
        ("landcruiser", "Land Cruiser"),
    ):
        if token in lower:
            matches.add(("Toyota", model))

    return matches


def _mentioned_makes(text: str) -> set[str]:
    lower = text.lower()
    mentioned: set[str] = set()
    if MAKE_MENTION_PATTERNS["Ford"].search(lower):
        mentioned.add("Ford")
    if MAKE_MENTION_PATTERNS["GM"].search(lower):
        mentioned.update({"Chevy", "GMC"})
    if MAKE_MENTION_PATTERNS["Ram / Dodge"].search(lower):
        mentioned.add("Ram / Dodge")
    if MAKE_MENTION_PATTERNS["Toyota"].search(lower):
        mentioned.add("Toyota")
    if MAKE_MENTION_PATTERNS["Jeep"].search(lower):
        mentioned.add("Jeep")
    if MAKE_MENTION_PATTERNS["Nissan"].search(lower):
        mentioned.add("Nissan")
    return mentioned


def _eco_diesel_fallback(text: str, year_from: int | None, year_to: int | None) -> set[tuple[str, str]]:
    lower = text.lower()
    if "ecodiesel" not in lower and "eco diesel" not in lower:
        return set()
    matches: set[tuple[str, str]] = set()
    if "1500" in lower:
        matches.add(("Ram / Dodge", "1500"))
    if year_from is None and year_to is None:
        matches.update({("Ram / Dodge", "1500"), ("Jeep", "Grand Cherokee")})
        return matches
    matches.add(("Ram / Dodge", "1500"))
    matches.add(("Jeep", "Grand Cherokee"))
    if (year_to or year_from or 0) >= 2020:
        matches.add(("Jeep", "Wrangler"))
        matches.add(("Jeep", "Gladiator"))
    return matches


def _all_models_for_make(make_name: str) -> set[tuple[str, str]]:
    if make_name == "Ford":
        return _expand_group("ford_all")
    if make_name in {"Chevy", "GMC"}:
        return {key for key in _expand_group("gm_all") if key[0] == make_name}
    if make_name == "Ram / Dodge":
        return _expand_group("ram_all")
    if make_name == "Toyota":
        return _expand_group("toyota_all")
    if make_name == "Jeep":
        return _expand_group("jeep_all")
    if make_name == "Nissan":
        return _expand_group("nissan_all")
    return set()


def _clamped_fitment_specs(
    model_keys: Iterable[tuple[str, str]],
    *,
    year_from: int | None,
    year_to: int | None,
) -> tuple[FitmentSpec, ...]:
    specs: list[FitmentSpec] = []
    seen: set[tuple[str, str, int | None, int | None]] = set()
    for make_name, model_name in model_keys:
        catalog_entry = CATALOG_BY_KEY.get((make_name, model_name))
        if catalog_entry is None:
            continue
        next_year_from = year_from if year_from is not None else catalog_entry.year_from
        next_year_to = year_to if year_to is not None else catalog_entry.year_to
        if catalog_entry.year_from is not None and next_year_from is not None:
            next_year_from = max(next_year_from, catalog_entry.year_from)
        if catalog_entry.year_to is not None:
            if next_year_to is None:
                next_year_to = catalog_entry.year_to
            else:
                next_year_to = min(next_year_to, catalog_entry.year_to)
        if next_year_from is not None and next_year_to is not None and next_year_from > next_year_to:
            continue
        key = (make_name, model_name, next_year_from, next_year_to)
        if key in seen:
            continue
        seen.add(key)
        specs.append(
            FitmentSpec(
                make=make_name,
                model=model_name,
                year_from=next_year_from,
                year_to=next_year_to,
            )
        )
    return tuple(specs)


def infer_fitment(
    *,
    name: str,
    sku: str = "",
    category_name: str = "",
) -> FitmentInference:
    source = _clean_text(name, sku)
    lower = source.lower()
    year_from, year_to = extract_year_window(name)

    for pattern in COMMERCIAL_PATTERNS:
        if pattern.search(source):
            return FitmentInference(
                kind="commercial",
                specs=tuple(),
                note=COMMERCIAL_COMPATIBILITY_NOTE,
            )

    if "universal" in lower or "all gdp intakes" in lower:
        return FitmentInference(
            kind="universal",
            specs=ALL_CONSUMER_SPECS,
            note=UNIVERSAL_COMPATIBILITY_NOTE,
        )

    if (
        year_from is not None
        and (year_to or year_from) <= 2000
        and "6.5l" in lower
        and ("gm" in lower or "detroit" in lower)
    ):
        return FitmentInference(
            kind="specific",
            specs=_clamped_fitment_specs(
                MODEL_GROUPS["gm_hd_legacy"],
                year_from=year_from,
                year_to=year_to,
            ),
            note="",
        )

    for pattern, group, override_from, override_to in CODE_PATTERN_GROUPS:
        if pattern.search(source):
            if not group:
                return FitmentInference(
                    kind="commercial",
                    specs=tuple(),
                    note=COMMERCIAL_COMPATIBILITY_NOTE,
                )
            return FitmentInference(
                kind="specific",
                specs=_clamped_fitment_specs(
                    group,
                    year_from=override_from,
                    year_to=override_to,
                ),
                note="",
            )

    model_keys = _model_token_map(source)

    if not model_keys:
        eco_diesel_matches = _eco_diesel_fallback(source, year_from, year_to)
        if eco_diesel_matches:
            model_keys.update(eco_diesel_matches)

    mentioned = _mentioned_makes(source)
    if mentioned:
        for make_name in mentioned:
            if not any(existing_make == make_name for existing_make, _ in model_keys):
                model_keys.update(_all_models_for_make(make_name))

    if model_keys:
        return FitmentInference(
            kind="specific",
            specs=_clamped_fitment_specs(model_keys, year_from=year_from, year_to=year_to),
            note="",
        )

    return FitmentInference(
        kind="universal",
        specs=ALL_CONSUMER_SPECS,
        note=UNIVERSAL_COMPATIBILITY_NOTE,
    )


def suggested_category_name(*, current_category_name: str, product_name: str) -> str | None:
    if "uncategor" not in (current_category_name or "").strip().lower():
        return None
    cleaned_name = _clean_text(product_name)
    for pattern, category_name in UNCATEGORIZED_CATEGORY_RULES:
        if pattern.search(cleaned_name):
            return category_name
    return None


def _ensure_car_model(
    *,
    make_name: str,
    model_name: str,
    year_from: int | None,
    year_to: int | None,
) -> CarModel:
    make, _ = CarMake.objects.get_or_create(name=make_name)
    model, _ = CarModel.objects.get_or_create(
        make=make,
        name=model_name,
        year_from=year_from,
        year_to=year_to,
    )
    return model


def _rename_legacy_fitment_records() -> None:
    dodge_make = CarMake.objects.filter(name="Dodge").first()
    if dodge_make and not CarMake.objects.filter(name="Ram / Dodge").exists():
        dodge_make.name = "Ram / Dodge"
        dodge_make.save(update_fields=["name"])

    ram_make = CarMake.objects.filter(name="Ram / Dodge").first()
    if ram_make is None:
        return

    legacy_model_names = {
        "RAM 1500": "1500",
        "RAM 2500": "2500",
        "RAM 3500": "3500",
    }
    for legacy_name, canonical_name in legacy_model_names.items():
        for model in CarModel.objects.filter(make=ram_make, name=legacy_name):
            has_conflict = CarModel.objects.filter(
                make=ram_make,
                name=canonical_name,
                year_from=model.year_from,
                year_to=model.year_to,
            ).exclude(pk=model.pk).exists()
            if has_conflict:
                continue
            model.name = canonical_name
            model.save(update_fields=["name"])


def sync_consumer_vehicle_catalog(*, apply: bool) -> dict[str, int]:
    if not apply:
        return {
            "legacy_records_normalized": 0,
            "makes_created": len({entry.make for entry in CONSUMER_VEHICLE_CATALOG}),
            "models_created": len(CONSUMER_VEHICLE_CATALOG),
        }

    legacy_updates = 0
    if CarMake.objects.filter(name="Dodge").exists() or CarModel.objects.filter(name__startswith="RAM ").exists():
        _rename_legacy_fitment_records()
        legacy_updates = 1

    makes_created = 0
    models_created = 0
    for entry in CONSUMER_VEHICLE_CATALOG:
        make, make_created = CarMake.objects.get_or_create(name=entry.make)
        if make_created:
            makes_created += 1
        _, model_created = CarModel.objects.get_or_create(
            make=make,
            name=entry.model,
            year_from=entry.year_from,
            year_to=entry.year_to,
        )
        if model_created:
            models_created += 1

    return {
        "legacy_records_normalized": legacy_updates,
        "makes_created": makes_created,
        "models_created": models_created,
    }


def resolve_fitment_models(*, specs: Iterable[FitmentSpec]) -> list[CarModel]:
    resolved: list[CarModel] = []
    seen: set[tuple[str, str, int | None, int | None]] = set()
    for spec in specs:
        key = (spec.make, spec.model, spec.year_from, spec.year_to)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(
            _ensure_car_model(
                make_name=spec.make,
                model_name=spec.model,
                year_from=spec.year_from,
                year_to=spec.year_to,
            )
        )
    return resolved


@transaction.atomic
def ensure_fitment_models_for_specs(*, specs: Iterable[FitmentSpec]) -> list[CarModel]:
    return resolve_fitment_models(specs=specs)
