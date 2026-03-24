import {
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  useTransition,
} from "react";

const PAGE_CONFIG = {
  store: {
    eyebrow: "Built for fitment-driven browsing",
    resultsLabel: "Matching parts",
    drawerLabel: "Product quick view",
    emptyTitle: "No parts match this combination",
    emptyBody:
      "Try clearing a fitment field, broadening the search, or switching categories.",
  },
  merch: {
    eyebrow: "Drop-ready apparel and accessories",
    resultsLabel: "Matching merch",
    drawerLabel: "Merch quick view",
    emptyTitle: "No merch matches this view",
    emptyBody:
      "Try a different category, remove the price filter, or broaden the search.",
  },
};

function getJsonFromLocation(listingUrl) {
  const url = new URL(listingUrl, window.location.origin);
  const params = new URLSearchParams(window.location.search);
  params.set("format", "json");
  url.search = params.toString();
  return url.toString();
}

function getProductSlugFromLocation() {
  return new URLSearchParams(window.location.search).get("product") || "";
}

function patchLocation(patch, { replace = false } = {}) {
  const url = new URL(window.location.href);
  Object.entries(patch).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      url.searchParams.delete(key);
      return;
    }
    url.searchParams.set(key, value);
  });
  const nextUrl = `${url.pathname}${url.search ? `?${url.searchParams.toString()}` : ""}${url.hash}`;
  window.history[replace ? "replaceState" : "pushState"]({}, "", nextUrl);
}

function readCookie(name) {
  const prefix = `${name}=`;
  const parts = document.cookie.split(";").map((part) => part.trim());
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length));
    }
  }
  return "";
}

function updateCartBadge(cart) {
  if (!cart) return;
  const { itemCount = 0 } = cart;
  document.querySelectorAll(".bgm-cart-fab").forEach((fab) => {
    let countEl = fab.querySelector(".bgm-cart-fab__count");
    if (itemCount > 0) {
      if (!countEl) {
        countEl = document.createElement("span");
        countEl.className = "bgm-cart-fab__count";
        countEl.setAttribute("aria-live", "polite");
        countEl.setAttribute("aria-atomic", "true");
        const icon = fab.querySelector(".bgm-cart-fab__icon");
        if (icon) {
          icon.appendChild(countEl);
        }
      }
      countEl.textContent = String(itemCount);
    } else if (countEl) {
      countEl.remove();
    }
    const label = itemCount === 1 ? "1 item" : `${itemCount} items`;
    fab.setAttribute(
      "aria-label",
      itemCount > 0 ? `View cart, ${label}` : "View cart"
    );
    fab.setAttribute(
      "title",
      itemCount > 0 ? `View cart (${label})` : "View cart"
    );
  });
}

function buildSummary(state, config) {
  const totalResults = state?.catalog?.pagination?.totalResults || 0;
  const chipCount = state?.filters?.activeChips?.length || 0;
  const noun = config.resultsLabel || "results";
  if (!totalResults) {
    return `0 ${noun.toLowerCase()}`;
  }
  if (chipCount) {
    return `${totalResults} ${noun.toLowerCase()} with ${chipCount} active filter${chipCount === 1 ? "" : "s"}`;
  }
  return `${totalResults} ${noun.toLowerCase()}`;
}

function buildFilterDraft(mode, state, searchValue = "") {
  const selected = state?.filters?.selected || {};
  return {
    q: searchValue || state?.filters?.search || "",
    sort: state?.filters?.sort || "featured",
    category: selected.category || "",
    make: selected.make || "",
    model: selected.model || "",
    year: selected.year || "",
    price: selected.price || "",
  };
}

function plainText(value) {
  const source = String(value || "");
  if (!source) return "";
  if (typeof DOMParser === "undefined") {
    return source.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  }
  const parsed = new DOMParser().parseFromString(source, "text/html");
  return (parsed.body?.textContent || "").replace(/\s+/g, " ").trim();
}

function categoryValue(category) {
  return String(category?.id || category?.key || category?.slug || "");
}

function buildGalleryImages(detail) {
  const images = [];
  const seen = new Set();
  const sourceImages = [
    ...(Array.isArray(detail?.gallery) ? detail.gallery : []),
    detail?.product?.image?.src
      ? {
          src: detail.product.image.src,
          alt: detail.product.image.alt || detail.product?.name || "Product image",
        }
      : null,
  ].filter(Boolean);

  sourceImages.forEach((image) => {
    const src = String(image?.src || "");
    if (!src || seen.has(src)) return;
    seen.add(src);
    images.push({
      src,
      alt: image.alt || detail?.product?.name || "Product image",
    });
  });

  return images;
}

function priceForDetail(detail, selectedOptionId) {
  if (!detail?.product?.price) return { primary: "", secondary: "", old: "", hint: "" };
  if (!selectedOptionId) {
    return {
      primary: detail.product.price.label,
      secondary: detail.product.price.dealerLabel,
      old: detail.product.price.oldLabel,
      hint: detail.product.price.hint,
    };
  }
  const selectedOption = (detail.options || []).find(
    (option) => !option.isSeparator && String(option.id) === String(selectedOptionId)
  );
  if (!selectedOption) {
    return {
      primary: detail.product.price.label,
      secondary: detail.product.price.dealerLabel,
      old: detail.product.price.oldLabel,
      hint: detail.product.price.hint,
    };
  }
  return {
    primary: selectedOption.priceLabel,
    secondary: selectedOption.dealerPriceLabel,
    old: "",
    hint: "",
  };
}

function LoadingCards() {
  return (
    <div className="storefront-grid">
      {Array.from({ length: 8 }).map((_, index) => (
        <div className="storefront-card storefront-card--skeleton" key={index}>
          <div className="storefront-card__media storefront-skeleton" />
          <div className="storefront-card__body">
            <div className="storefront-skeleton storefront-skeleton--short" />
            <div className="storefront-skeleton storefront-skeleton--medium" />
            <div className="storefront-skeleton storefront-skeleton--tiny" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ title, body, onReset, resetLabel }) {
  return (
    <section className="storefront-empty">
      <p className="storefront-empty__eyebrow">Nothing in this pass</p>
      <h3>{title}</h3>
      <p>{body}</p>
      <button className="storefront-button storefront-button--ghost" type="button" onClick={onReset}>
        {resetLabel}
      </button>
    </section>
  );
}

function Chips({ chips, onRemove, onReset, resetLabel }) {
  if (!chips?.length) return null;
  return (
    <div className="storefront-chips">
      {chips.map((chip) => (
        <button
          className="storefront-chip"
          key={`${chip.key}-${chip.value}`}
          type="button"
          onClick={() => onRemove(chip)}
        >
          <span>{chip.label}</span>
          <span aria-hidden="true">×</span>
        </button>
      ))}
      <button
        className="storefront-chip storefront-chip--clear"
        type="button"
        onClick={onReset}
      >
        {resetLabel}
      </button>
    </div>
  );
}

function Pagination({ pagination, onChange }) {
  if (!pagination || pagination.totalPages <= 1) return null;
  return (
    <div className="storefront-pagination">
      <div className="storefront-pagination__meta">
        Page {pagination.page} of {pagination.totalPages}
      </div>
      <div className="storefront-pagination__controls">
        <button
          className="storefront-button storefront-button--ghost"
          type="button"
          onClick={() => onChange(pagination.page - 1)}
          disabled={!pagination.hasPrevious}
        >
          Previous
        </button>
        <button
          className="storefront-button storefront-button--ghost"
          type="button"
          onClick={() => onChange(pagination.page + 1)}
          disabled={!pagination.hasNext}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function CategoryBrowser({ categories, selectedCategory, onSelect, onClear }) {
  const [showAll, setShowAll] = useState(false);
  const [isDesktopCarousel, setIsDesktopCarousel] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(min-width: 901px)").matches
      : true
  );
  const [carouselState, setCarouselState] = useState({
    enabled: false,
    canPrev: false,
    canNext: false,
  });
  const featuredRailRef = useRef(null);
  const autoplayPauseUntilRef = useRef(0);
  const selectedKey = String(selectedCategory || "");
  const orderedCategories = selectedKey
    ? [
        ...categories.filter((category) => categoryValue(category) === selectedKey),
        ...categories.filter((category) => categoryValue(category) !== selectedKey),
      ]
    : categories;
  const featuredLimit = orderedCategories.length > 8 ? 6 : orderedCategories.length;
  const featuredCategories = isDesktopCarousel
    ? orderedCategories
    : orderedCategories.slice(0, featuredLimit);
  const featuredSignature = featuredCategories.map((category) => categoryValue(category)).join("|");
  const overflowCategories = orderedCategories.slice(featuredLimit);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 901px)");
    const syncViewport = () => setIsDesktopCarousel(mediaQuery.matches);
    syncViewport();
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener("change", syncViewport);
      return () => mediaQuery.removeEventListener("change", syncViewport);
    }
    mediaQuery.addListener(syncViewport);
    return () => mediaQuery.removeListener(syncViewport);
  }, []);

  useEffect(() => {
    const rail = featuredRailRef.current;
    if (!rail || !isDesktopCarousel) {
      setCarouselState({
        enabled: false,
        canPrev: false,
        canNext: false,
      });
      return undefined;
    }

    const syncCarouselState = () => {
      const maxScroll = Math.max(rail.scrollWidth - rail.clientWidth, 0);
      const enabled = maxScroll > 12;
      setCarouselState({
        enabled,
        canPrev: enabled && rail.scrollLeft > 8,
        canNext: enabled && rail.scrollLeft < maxScroll - 8,
      });
    };
    let frameId = 0;
    const scheduleSync = () => {
      window.cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(syncCarouselState);
    };
    const resizeObserver =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(scheduleSync) : null;

    scheduleSync();
    rail.addEventListener("scroll", scheduleSync, { passive: true });
    window.addEventListener("resize", scheduleSync);
    resizeObserver?.observe(rail);
    Array.from(rail.children).forEach((child) => resizeObserver?.observe(child));
    document.fonts?.ready?.then(scheduleSync).catch(() => {});

    return () => {
      window.cancelAnimationFrame(frameId);
      rail.removeEventListener("scroll", scheduleSync);
      window.removeEventListener("resize", scheduleSync);
      resizeObserver?.disconnect();
    };
  }, [featuredSignature, isDesktopCarousel]);

  useEffect(() => {
    if (!isDesktopCarousel || !carouselState.enabled) return undefined;
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mediaQuery.matches) return undefined;

    const timer = window.setInterval(() => {
      if (Date.now() < autoplayPauseUntilRef.current) return;
      const rail = featuredRailRef.current;
      if (!rail) return;
      const firstCard = rail.querySelector(".storefront-categoryCard");
      const step = firstCard
        ? firstCard.getBoundingClientRect().width + 14
        : Math.max(rail.clientWidth * 0.72, 220);
      const maxScroll = Math.max(rail.scrollWidth - rail.clientWidth, 0);
      const nextLeft =
        rail.scrollLeft >= maxScroll - step * 0.35 ? 0 : rail.scrollLeft + step;
      rail.scrollTo({
        left: nextLeft,
        behavior: "smooth",
      });
    }, 3400);

    return () => window.clearInterval(timer);
  }, [carouselState.enabled, isDesktopCarousel]);

  function handleCategorySelect(categoryKey, options = {}) {
    onSelect(categoryKey);
    if (options.collapseOverflow) {
      setShowAll(false);
    }
  }

  function pauseCarousel(duration = 12000) {
    autoplayPauseUntilRef.current = Date.now() + duration;
  }

  function nudgeCarousel(direction) {
    const rail = featuredRailRef.current;
    if (!rail) return;
    const firstCard = rail.querySelector(".storefront-categoryCard");
    const step = firstCard
      ? firstCard.getBoundingClientRect().width + 14
      : Math.max(rail.clientWidth * 0.72, 220);
    pauseCarousel();
    rail.scrollBy({
      left: direction * step,
      behavior: "smooth",
    });
  }

  return (
    <section className={`storefront-categoryBrowser ${showAll ? "is-expanded" : ""}`}>
      <div className="storefront-categoryBrowser__featuredWrap">
        {isDesktopCarousel && carouselState.enabled ? (
          <button
            className="storefront-categoryBrowser__nav storefront-categoryBrowser__nav--prev"
            type="button"
            aria-label="Previous categories"
            onClick={() => nudgeCarousel(-1)}
          >
            <span aria-hidden="true">‹</span>
          </button>
        ) : null}

        <div
          className="storefront-categoryBrowser__featured"
          ref={featuredRailRef}
          onWheel={() => pauseCarousel()}
          onMouseEnter={() => pauseCarousel()}
          onTouchStart={() => pauseCarousel()}
        >
          {featuredCategories.map((category) => {
            const key = categoryValue(category);
            const isSelected = selectedKey === key;
            return (
              <button
                className={`storefront-categoryCard ${isSelected ? "is-selected" : ""}`}
                type="button"
                key={key}
                onClick={() => handleCategorySelect(key)}
              >
                {category.imageUrl ? <img src={category.imageUrl} alt={category.label} /> : null}
                <span>{category.label}</span>
                <small>{category.productCount || 0} items</small>
              </button>
            );
          })}
        </div>

        {isDesktopCarousel && carouselState.enabled ? (
          <button
            className="storefront-categoryBrowser__nav storefront-categoryBrowser__nav--next"
            type="button"
            aria-label="Next categories"
            onClick={() => nudgeCarousel(1)}
          >
            <span aria-hidden="true">›</span>
          </button>
        ) : null}
      </div>

      {overflowCategories.length ? (
        <>
          <div className="storefront-categoryBrowser__footer">
            <div className="storefront-categoryBrowser__meta">
              <span className="storefront-categoryBrowser__eyebrow">Full category map</span>
              <strong>{overflowCategories.length} more categories ready</strong>
            </div>

            <div className="storefront-categoryBrowser__actions">
              {selectedKey ? (
                <button
                  className="storefront-button storefront-button--ghost storefront-button--inline"
                  type="button"
                  onClick={onClear}
                >
                  All categories
                </button>
              ) : null}
              <button
                className={`storefront-button storefront-button--categoryToggle ${
                  showAll ? "is-open" : ""
                }`}
                type="button"
                aria-expanded={showAll}
                onClick={() => setShowAll((current) => !current)}
              >
                <span>{showAll ? "Show featured categories" : "Browse all categories"}</span>
                <strong>{categories.length}</strong>
              </button>
            </div>
          </div>

          <div className={`storefront-categoryBrowser__overflow ${showAll ? "is-open" : ""}`}>
            <div className="storefront-categoryBrowser__pillGrid">
              {overflowCategories.map((category) => {
                const key = categoryValue(category);
                const isSelected = selectedKey === key;
                return (
                  <button
                    className={`storefront-categoryPill ${isSelected ? "is-selected" : ""}`}
                    type="button"
                    key={key}
                    title={category.label}
                    onClick={() =>
                      handleCategorySelect(key, {
                        collapseOverflow: true,
                      })
                    }
                  >
                    <span className="storefront-categoryPill__label">{category.label}</span>
                    <span className="storefront-categoryPill__rule" aria-hidden="true" />
                    <small className="storefront-categoryPill__count">
                      {category.productCount || 0}
                    </small>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function ProductCard({ mode, product, onOpen }) {
  const handlePrimaryAction = () => {
    if (product.quickView && product.slug) {
      onOpen(product);
      return;
    }
    if (product.detailUrl) {
      window.location.href = product.detailUrl;
    }
  };
  const summaryText = plainText(
    product.shortDescription ||
      product.description ||
      "Open the product to inspect the purchase flow."
  );

  return (
    <article className="storefront-card">
      <button
        className="storefront-card__hit"
        type="button"
        onClick={handlePrimaryAction}
        aria-label={`Open ${product.name}`}
      />
      <div className="storefront-card__mediaWrap">
        {product.image?.src ? (
          <img
            className="storefront-card__media"
            src={product.image.src}
            alt={product.image.alt || product.name}
            loading="lazy"
          />
        ) : (
          <div className="storefront-card__media storefront-card__media--fallback" />
        )}
        <div className="storefront-card__badges">
          {(product.badges || []).slice(0, 2).map((badge) => (
            <span
              className={`storefront-badge storefront-badge--${badge.tone || "neutral"}`}
              key={`${product.id}-${badge.label}`}
            >
              {badge.label}
            </span>
          ))}
        </div>
      </div>
      <div className="storefront-card__body">
        <div className="storefront-card__meta">
          <span>{product.category?.label || (mode === "store" ? "Products" : "Merch")}</span>
          {mode === "store" && product.compatibility?.length ? (
            <span>{product.compatibility.length} fitments shown</span>
          ) : null}
        </div>
        <h3>{product.name}</h3>
        <p>{summaryText}</p>
        {mode === "merch" && product.colorSwatches?.length ? (
          <div className="storefront-swatches">
            {product.colorSwatches.slice(0, 5).map((swatch, index) => (
              <span
                key={`${product.id}-${index}`}
                className="storefront-swatches__dot"
                title={swatch.label || ""}
                style={{ "--swatch": swatch.hex || "#8c8c8c" }}
              />
            ))}
          </div>
        ) : null}
        {mode === "store" && product.compatibility?.length ? (
          <ul className="storefront-fitmentList">
            {product.compatibility.slice(0, 2).map((item) => (
              <li key={item.key || item.label}>{item.label}</li>
            ))}
          </ul>
        ) : null}
        <div className="storefront-card__footer">
          <div className="storefront-card__price">
            <strong>{product.price?.label || ""}</strong>
            {product.price?.dealerLabel ? (
              <span>Dealer {product.price.dealerLabel}</span>
            ) : null}
          </div>
          <span className="storefront-button storefront-button--inline" aria-hidden="true">
            {product.actionLabel}
          </span>
        </div>
      </div>
    </article>
  );
}

function FilterPanel({
  mode,
  state,
  filtersOpen,
  setFiltersOpen,
  isMobileViewport,
  onPatch,
  searchInput,
  setSearchInput,
}) {
  const available = state.filters?.available || {};
  const selected = state.filters?.selected || {};
  const [draft, setDraft] = useState(() =>
    buildFilterDraft(mode, state, searchInput)
  );
  const activeMake = isMobileViewport ? draft.make : selected.make || "";
  const modelOptions = (available.models || []).filter(
    (model) => activeMake && String(model.makeId) === String(activeMake)
  );
  const modelDisabled = mode === "store" && !activeMake;

  useEffect(() => {
    if (!isMobileViewport || !filtersOpen) return;
    setDraft(buildFilterDraft(mode, state, searchInput));
  }, [
    filtersOpen,
    isMobileViewport,
    mode,
    searchInput,
    selected.category,
    selected.make,
    selected.model,
    selected.price,
    selected.year,
    state.filters?.search,
    state.filters?.sort,
  ]);

  function updateDraft(patch) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function applyMobileDraft() {
    const nextSearch = draft.q || "";
    setSearchInput(nextSearch);
    onPatch({
      q: nextSearch,
      sort: draft.sort || "featured",
      category: draft.category || "",
      make: draft.make || "",
      model: draft.model || "",
      year: draft.year || "",
      price: draft.price || "",
      page: "",
      product: "",
    });
  }

  function resetMobileDraft() {
    setDraft({
      q: "",
      sort: "featured",
      category: "",
      make: "",
      model: "",
      year: "",
      price: "",
    });
  }

  return (
    <>
      <button
        className="storefront-mobileFilter"
        type="button"
        onClick={() => setFiltersOpen(true)}
      >
        Filters
      </button>
      <aside className={`storefront-filters ${filtersOpen ? "is-open" : ""}`}>
        <div className="storefront-filters__header">
          <div>
            <p className="storefront-filters__eyebrow">Browse smarter</p>
            <h3>{mode === "store" ? "Fitment filters" : "Merch filters"}</h3>
          </div>
          <button
            className="storefront-filters__close"
            type="button"
            aria-label="Close filters"
            onClick={() => setFiltersOpen(false)}
          >
            <span className="storefront-filters__closeText">Close</span>
            <span className="storefront-filters__closeIcon" aria-hidden="true">
              ×
            </span>
          </button>
        </div>

        <div className="storefront-filters__body">
          <label className="storefront-field">
            <span>Search</span>
            <input
              type="search"
              value={isMobileViewport ? draft.q : searchInput}
              onChange={(event) =>
                isMobileViewport
                  ? updateDraft({ q: event.target.value })
                  : setSearchInput(event.target.value)
              }
              placeholder={mode === "store" ? "Search parts, brands, SKUs" : "Search merch"}
            />
          </label>

          <label className="storefront-field">
            <span>Sort</span>
            <select
              value={isMobileViewport ? draft.sort : state.filters?.sort || "featured"}
              onChange={(event) =>
                isMobileViewport
                  ? updateDraft({ sort: event.target.value })
                  : onPatch({ sort: event.target.value, page: "", product: "" })
              }
            >
              {(state.filters?.sortOptions || []).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="storefront-field">
            <span>Category</span>
            <select
              value={isMobileViewport ? draft.category : selected.category || ""}
              onChange={(event) =>
                isMobileViewport
                  ? updateDraft({ category: event.target.value })
                  : onPatch({
                      category: event.target.value,
                      page: "",
                      product: "",
                    })
              }
            >
              <option value="">All categories</option>
              {(available.categories || []).map((category) => (
                <option
                  key={category.id || category.key || category.slug}
                  value={category.id || category.key || category.slug}
                >
                  {category.label}
                </option>
              ))}
            </select>
          </label>

          {mode === "store" ? (
            <>
              <label className="storefront-field">
                <span>Make</span>
                <select
                  value={isMobileViewport ? draft.make : selected.make || ""}
                  onChange={(event) =>
                    isMobileViewport
                      ? updateDraft({
                          make: event.target.value,
                          model: "",
                        })
                      : onPatch({
                          make: event.target.value,
                          model: "",
                          page: "",
                          product: "",
                        })
                  }
                >
                  <option value="">Any make</option>
                  {(available.makes || []).map((make) => (
                    <option key={make.id} value={make.id}>
                      {make.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="storefront-field">
                <span>Model</span>
                <select
                  disabled={modelDisabled}
                  value={isMobileViewport ? draft.model : selected.model || ""}
                  onChange={(event) =>
                    isMobileViewport
                      ? updateDraft({ model: event.target.value })
                      : onPatch({
                          model: event.target.value,
                          page: "",
                          product: "",
                      })
                  }
                >
                  <option value="">{activeMake ? "Any model" : "Select make first"}</option>
                  {modelOptions.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="storefront-field">
                <span>Year</span>
                <input
                  type="number"
                  value={isMobileViewport ? draft.year : selected.year || ""}
                  min={available.yearMin || 1950}
                  max={available.yearMax || 2100}
                  onChange={(event) =>
                    isMobileViewport
                      ? updateDraft({ year: event.target.value })
                      : onPatch({
                          year: event.target.value,
                          page: "",
                          product: "",
                        })
                  }
                  placeholder="Any year"
                />
              </label>
            </>
          ) : (
            <label className="storefront-field">
              <span>Price</span>
              <select
                value={isMobileViewport ? draft.price : selected.price || ""}
                onChange={(event) =>
                  isMobileViewport
                    ? updateDraft({ price: event.target.value })
                    : onPatch({
                        price: event.target.value,
                        page: "",
                        product: "",
                      })
                }
              >
                {(available.priceOptions || []).map((option) => (
                  <option key={option.value || "all"} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          <button
            className="storefront-button storefront-button--ghost storefront-filters__reset"
            type="button"
            onClick={() =>
              isMobileViewport
                ? resetMobileDraft()
                : onPatch({
                    q: "",
                    category: "",
                    make: "",
                    model: "",
                    year: "",
                    price: "",
                    page: "",
                    product: "",
                    sort: "featured",
                  })
            }
          >
            Reset all
          </button>
        </div>

        {isMobileViewport ? (
          <div className="storefront-filters__footer">
            <button
              className="storefront-button storefront-button--primary storefront-filters__apply"
              type="button"
              onClick={applyMobileDraft}
            >
              Apply filters
            </button>
          </div>
        ) : null}
      </aside>
      <button
        className={`storefront-filters__scrim ${filtersOpen ? "is-open" : ""}`}
        type="button"
        aria-label="Close filters"
        onClick={() => setFiltersOpen(false)}
      />
    </>
  );
}

function buildFormValues(fields = []) {
  const nextValues = {};
  fields.forEach((field) => {
    if (!field?.name || field.inputType === "file" || field.inputType === "hidden") {
      return;
    }
    if (field.value !== undefined && field.value !== null && String(field.value) !== "") {
      nextValues[field.name] = String(field.value);
      return;
    }
    if (field.inputType === "select" && field.options?.length) {
      nextValues[field.name] = String(field.options[0].value ?? "");
      return;
    }
    nextValues[field.name] = "";
  });
  return nextValues;
}

function bytesToText(bytes) {
  const amount = Number(bytes || 0);
  if (!amount) return "";
  if (amount < 1024) return `${amount} B`;
  if (amount < 1024 * 1024) return `${(amount / 1024).toFixed(1)} KB`;
  return `${(amount / (1024 * 1024)).toFixed(1)} MB`;
}

function firstPayloadError(payload, fallbackMessage) {
  if (payload?.nonFieldErrors?.length) {
    return payload.nonFieldErrors[0];
  }
  const firstFieldErrors = Object.values(payload?.errors || {}).find(
    (entries) => Array.isArray(entries) && entries.length
  );
  if (firstFieldErrors?.length) {
    return firstFieldErrors[0];
  }
  return payload?.message || fallbackMessage;
}

function StorefrontFormField({
  field,
  value,
  error,
  onChange,
  file,
  onFileChange,
  previewUrl,
  helperText,
}) {
  if (!field || field.inputType === "hidden") return null;

  const className = `storefront-formField ${field.fullWidth ? "storefront-formField--full" : ""} ${
    error ? "is-error" : ""
  }`.trim();

  let control = null;
  if (field.inputType === "textarea") {
    control = (
      <textarea
        rows={field.rows || 4}
        value={value || ""}
        placeholder={field.placeholder || ""}
        onChange={(event) => onChange(field.name, event.target.value)}
      />
    );
  } else if (field.inputType === "select") {
    control = (
      <select
        value={value || ""}
        onChange={(event) => onChange(field.name, event.target.value)}
      >
        {(field.options || []).map((option) => (
          <option key={`${field.name}-${option.value}`} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  } else if (field.inputType === "file") {
    control = (
      <>
        <input
          type="file"
          accept={field.accept || "image/*"}
          onChange={(event) => onFileChange(field.name, event.target.files?.[0] || null)}
        />
        {file ? (
          <div className="storefront-uploadPreview">
            {previewUrl ? <img src={previewUrl} alt="Reference preview" /> : null}
            <div className="storefront-uploadPreview__meta">
              <strong>{file.name || "Selected image"}</strong>
              <small>{bytesToText(file.size)}</small>
            </div>
          </div>
        ) : null}
      </>
    );
  } else {
    control = (
      <input
        type={field.inputType || "text"}
        value={value || ""}
        placeholder={field.placeholder || ""}
        autoComplete={field.autocomplete || undefined}
        onChange={(event) => onChange(field.name, event.target.value)}
      />
    );
  }

  return (
    <label className={className}>
      <span>
        {field.label}
        {field.required ? " *" : ""}
      </span>
      {control}
      {error ? <small className="storefront-formField__error">{error}</small> : null}
      {!error && helperText ? (
        <small className="storefront-formField__hint">{helperText}</small>
      ) : null}
    </label>
  );
}

function QuickViewDrawer({
  config,
  detail,
  detailStatus,
  productSlug,
  onClose,
  onOpenRelated,
  onCartUpdate,
  setToast,
  pageRenderedAt,
}) {
  const [selectedOptionId, setSelectedOptionId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [submitState, setSubmitState] = useState("idle");
  const [submitError, setSubmitError] = useState("");
  const [fitmentValues, setFitmentValues] = useState({});
  const [fitmentLeadSecurity, setFitmentLeadSecurity] = useState({});
  const [fitmentFile, setFitmentFile] = useState(null);
  const [fitmentPreviewUrl, setFitmentPreviewUrl] = useState("");
  const [fitmentStatus, setFitmentStatus] = useState("idle");
  const [fitmentErrors, setFitmentErrors] = useState({});
  const [fitmentFormError, setFitmentFormError] = useState("");
  const [fitmentSuccess, setFitmentSuccess] = useState("");
  const [reviewValues, setReviewValues] = useState({});
  const [reviewLeadSecurity, setReviewLeadSecurity] = useState({});
  const [reviewStatus, setReviewStatus] = useState("idle");
  const [reviewErrors, setReviewErrors] = useState({});
  const [reviewFormError, setReviewFormError] = useState("");
  const [reviewSuccess, setReviewSuccess] = useState("");
  const renderedAtRef = useRef(pageRenderedAt || Date.now());

  useEffect(() => {
    if (!detail) return;
    setSelectedOptionId(String(detail.purchase?.defaultOptionId || ""));
    setQuantity(1);
    setSubmitState("idle");
    setSubmitError("");
    setFitmentValues(buildFormValues(detail.fitmentRequest?.fields || []));
    setFitmentLeadSecurity(detail.fitmentRequest?.leadSecurity || {});
    setFitmentFile(null);
    setFitmentStatus("idle");
    setFitmentErrors({});
    setFitmentFormError("");
    setFitmentSuccess("");
    setReviewValues(buildFormValues(detail.reviews?.fields || []));
    setReviewLeadSecurity(detail.reviews?.leadSecurity || {});
    setReviewStatus("idle");
    setReviewErrors({});
    setReviewFormError("");
    setReviewSuccess("");
    setActiveImageIndex(0);
  }, [detail]);

  useEffect(() => {
    if (!fitmentFile) {
      setFitmentPreviewUrl("");
      return undefined;
    }
    const nextUrl = window.URL.createObjectURL(fitmentFile);
    setFitmentPreviewUrl(nextUrl);
    return () => window.URL.revokeObjectURL(nextUrl);
  }, [fitmentFile]);

  useEffect(() => {
    if (!productSlug) return undefined;
    const onEscape = (event) => {
      const activeTag = document.activeElement?.tagName || "";
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (
        (event.key === "ArrowLeft" || event.key === "ArrowRight") &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(activeTag)
      ) {
        setActiveImageIndex((current) => {
          const images = buildGalleryImages(detail);
          if (images.length <= 1) return current;
          const direction = event.key === "ArrowRight" ? 1 : -1;
          return (current + direction + images.length) % images.length;
        });
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [detail, onClose, productSlug]);

  useEffect(() => {
    const shouldLockScroll = Boolean(productSlug);
    document.body.classList.toggle("storefront-overlay-open", shouldLockScroll);
    return () => document.body.classList.remove("storefront-overlay-open");
  }, [productSlug]);

  if (!productSlug) return null;

  const price = priceForDetail(detail, selectedOptionId);
  const isLoading = detailStatus === "loading";
  const isError = detailStatus === "error";
  const selectableOptions = (detail?.options || []).filter((option) => !option.isSeparator);
  const hasDenseOptions =
    selectableOptions.length >= 7 ||
    new Set(selectableOptions.map((option) => Number(option.column || 1))).size > 1;
  const summaryDescription = plainText(detail?.product?.shortDescription || detail?.description);
  const detailDescription = plainText(detail?.description);
  const compatibilityNote = plainText(detail?.compatibility?.note);
  const galleryImages = buildGalleryImages(detail);
  const activeImage = galleryImages[activeImageIndex] || galleryImages[0] || null;

  function cycleImage(direction) {
    setActiveImageIndex((current) => {
      if (galleryImages.length <= 1) return current;
      return (current + direction + galleryImages.length) % galleryImages.length;
    });
  }

  async function submitCart({ buyNow = false }) {
    if (!detail?.purchase?.cartActionUrl) return;
    const formData = new FormData();
    formData.append("qty", String(Math.max(1, Number(quantity || 1))));
    if (selectedOptionId) {
      formData.append("option_id", selectedOptionId);
    }
    if (buyNow) {
      formData.append("buy_now", "1");
    }

    setSubmitState("submitting");
    setSubmitError("");
    try {
      const response = await fetch(detail.purchase.cartActionUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": readCookie("csrftoken"),
        },
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "Could not add this product to the cart.");
      }
      onCartUpdate(payload.cart);
      setToast(payload.message || "Added to cart.");
      if (payload.redirectUrl) {
        window.location.href = payload.redirectUrl;
        return;
      }
      setSubmitState("success");
    } catch (error) {
      setSubmitError(error.message || "Could not add this product to the cart.");
      setSubmitState("idle");
    }
  }

  async function submitFitmentRequest(event) {
    event.preventDefault();
    if (!detail?.fitmentRequest?.actionUrl) return;

    const formData = new FormData();
    formData.append("form_type", "custom_fitment");
    Object.entries(fitmentValues).forEach(([name, value]) => {
      formData.append(name, value || "");
    });
    if (fitmentFile) {
      formData.append("reference_image", fitmentFile);
    }
    formData.append(
      fitmentLeadSecurity?.honeypotName || "company",
      ""
    );
    formData.append(
      "form_token",
      fitmentLeadSecurity?.formToken || ""
    );
    formData.append(
      "form_rendered_at",
      String(renderedAtRef.current || Date.now())
    );

    setFitmentStatus("submitting");
    setFitmentErrors({});
    setFitmentFormError("");
    setFitmentSuccess("");

    try {
      const response = await fetch(detail.fitmentRequest.actionUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": readCookie("csrftoken"),
        },
        body: formData,
      });
      const payload = await response.json();
      if (payload.leadSecurity) {
        setFitmentLeadSecurity(payload.leadSecurity);
      }
      if (!response.ok || !payload.ok) {
        setFitmentErrors(payload.errors || {});
        setFitmentFormError(
          firstPayloadError(payload, "Could not send the fitment request.")
        );
        setFitmentStatus("idle");
        return;
      }
      const successMessage =
        payload.message || "We got your fitment request and will reply soon.";
      setFitmentSuccess(successMessage);
      setFitmentStatus("success");
      setFitmentValues(buildFormValues(detail.fitmentRequest?.fields || []));
      setFitmentFile(null);
      setToast(successMessage);
    } catch (error) {
      setFitmentFormError(
        error.message || "Could not send the fitment request."
      );
      setFitmentStatus("idle");
    }
  }

  async function submitReview(event) {
    event.preventDefault();
    if (!detail?.reviews?.actionUrl) return;

    const formData = new FormData();
    formData.append("form_type", "product_review");
    Object.entries(reviewValues).forEach(([name, value]) => {
      formData.append(name, value || "");
    });
    formData.append(reviewLeadSecurity?.honeypotName || "company", "");
    formData.append("form_token", reviewLeadSecurity?.formToken || "");
    formData.append(
      "form_rendered_at",
      String(renderedAtRef.current || Date.now())
    );

    setReviewStatus("submitting");
    setReviewErrors({});
    setReviewFormError("");
    setReviewSuccess("");

    try {
      const response = await fetch(detail.reviews.actionUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": readCookie("csrftoken"),
        },
        body: formData,
      });
      const payload = await response.json();
      if (payload.leadSecurity) {
        setReviewLeadSecurity(payload.leadSecurity);
      }
      if (!response.ok || !payload.ok) {
        setReviewErrors(payload.errors || {});
        setReviewFormError(
          firstPayloadError(payload, "Could not submit the review.")
        );
        setReviewStatus("idle");
        return;
      }
      const successMessage =
        payload.message ||
        detail.reviews?.successMessage ||
        "Thanks for the review. It's in the approval queue now.";
      setReviewSuccess(successMessage);
      setReviewStatus("success");
      setReviewValues(buildFormValues(detail.reviews?.fields || []));
      setToast(successMessage);
    } catch (error) {
      setReviewFormError(error.message || "Could not submit the review.");
      setReviewStatus("idle");
    }
  }

  return (
    <>
      <button
        className="storefront-drawer__scrim"
        type="button"
        aria-label="Close product details"
        onClick={onClose}
      />
      <aside
        className="storefront-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={config.drawerLabel}
      >
        <div className="storefront-drawer__header">
          <div>
            <p className="storefront-drawer__eyebrow">{config.drawerLabel}</p>
            <h2>{detail?.product?.name || "Loading product"}</h2>
          </div>
          <button
            className="storefront-drawer__close"
            type="button"
            aria-label="Close product details"
            onClick={onClose}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>

        {isLoading ? (
          <div className="storefront-drawer__loading">
            <div className="storefront-skeleton storefront-drawer__heroSkeleton" />
            <div className="storefront-skeleton storefront-skeleton--medium" />
            <div className="storefront-skeleton storefront-skeleton--short" />
          </div>
        ) : null}

        {isError ? (
          <div className="storefront-empty storefront-empty--compact">
            <h3>Product details are unavailable</h3>
            <p>Try the full product page instead.</p>
            <a
              className="storefront-button storefront-button--primary"
              href={`/store/p/${productSlug}/`}
            >
              Open full page
            </a>
          </div>
        ) : null}

        {!isLoading && !isError && detail ? (
          <div className="storefront-drawer__body">
            <div className="storefront-drawer__hero">
              <div className="storefront-drawer__gallery">
                <div className="storefront-drawer__mediaFrame">
                  {activeImage ? (
                    <img
                      className="storefront-drawer__heroImage"
                      src={activeImage.src}
                      alt={activeImage.alt || detail.product?.image?.alt || detail.product?.name}
                    />
                  ) : (
                    <div className="storefront-drawer__heroImage storefront-drawer__heroImage--fallback" />
                  )}
                  {galleryImages.length > 1 ? (
                    <>
                      <button
                        className="storefront-drawer__nav storefront-drawer__nav--prev"
                        type="button"
                        aria-label="Previous image"
                        onClick={() => cycleImage(-1)}
                      >
                        <span aria-hidden="true">‹</span>
                      </button>
                      <button
                        className="storefront-drawer__nav storefront-drawer__nav--next"
                        type="button"
                        aria-label="Next image"
                        onClick={() => cycleImage(1)}
                      >
                        <span aria-hidden="true">›</span>
                      </button>
                    </>
                  ) : null}
                </div>
                {galleryImages.length > 1 ? (
                  <div className="storefront-drawer__thumbs">
                    {galleryImages.map((image, index) => (
                      <button
                        key={image.src}
                        className={`storefront-drawer__thumb ${
                          activeImage?.src === image.src ? "is-active" : ""
                        }`}
                        type="button"
                        onClick={() => setActiveImageIndex(index)}
                      >
                        <img
                          src={image.src}
                          alt={image.alt || detail.product?.name}
                        />
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="storefront-drawer__summary">
                <div className="storefront-drawer__badges">
                  {(detail.product?.badges || []).map((badge) => (
                    <span
                      className={`storefront-badge storefront-badge--${
                        badge.tone || "neutral"
                      }`}
                      key={badge.label}
                    >
                      {badge.label}
                    </span>
                  ))}
                </div>
                <p className="storefront-drawer__kicker">
                  {detail.product?.category?.label || "Product"}
                </p>
                {summaryDescription ? (
                  <p className="storefront-drawer__description">
                    {summaryDescription}
                  </p>
                ) : null}
                <div className="storefront-drawer__price">
                  {price.hint ? <span>{price.hint}</span> : null}
                  <strong>{price.primary}</strong>
                  {price.old ? <em>{price.old}</em> : null}
                  {price.secondary ? <small>Dealer {price.secondary}</small> : null}
                </div>
                {detail.purchase?.inventoryNotice ? (
                  <p className="storefront-drawer__notice">
                    {detail.purchase.inventoryNotice}
                  </p>
                ) : null}
                {detail.purchase?.freeShippingHint ? (
                  <p className="storefront-drawer__notice">
                    Canada free shipping over {detail.purchase.freeShippingHint}.
                  </p>
                ) : null}

                {(detail.options || []).length ? (
                  <div
                    className={`storefront-drawer__options ${
                      hasDenseOptions ? "is-dense" : ""
                    }`}
                  >
                    {[1, 2].map((column) => {
                      const columnOptions = (detail.options || []).filter(
                        (option) => Number(option.column || 1) === column
                      );
                      if (!columnOptions.length) return null;
                      const heading =
                        column === 1
                          ? detail.optionLabels?.column1 || "Options"
                          : detail.optionLabels?.column2 || "More options";
                      return (
                        <div
                          className="storefront-drawer__optionColumn"
                          key={column}
                        >
                          <h3>{heading}</h3>
                          <div className="storefront-optionList">
                            {columnOptions.map((option) =>
                              option.isSeparator ? (
                                <div
                                  className="storefront-optionList__separator"
                                  key={`sep-${option.id}`}
                                >
                                  {option.name}
                                </div>
                              ) : (
                                <label className="storefront-option" key={option.id}>
                                  <input
                                    type="radio"
                                    name="product-option"
                                    value={option.id}
                                    checked={
                                      String(selectedOptionId) === String(option.id)
                                    }
                                    onChange={() =>
                                      setSelectedOptionId(String(option.id))
                                    }
                                  />
                                  <span className="storefront-option__copy">
                                    <strong>{option.name}</strong>
                                    {option.description ? (
                                      <small>{option.description}</small>
                                    ) : null}
                                  </span>
                                  <span className="storefront-option__price">
                                    {option.priceLabel}
                                    {option.dealerPriceLabel ? (
                                      <small>Dealer {option.dealerPriceLabel}</small>
                                    ) : null}
                                  </span>
                                </label>
                              )
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}

                {detail.purchase?.contactMode ? (
                  <div className="storefront-drawer__actions">
                    <a
                      className="storefront-button storefront-button--primary"
                      href={detail.purchase.contactUrl}
                    >
                      Contact us
                    </a>
                  </div>
                ) : (
                  <>
                    <div className="storefront-drawer__purchaseRow">
                      <label className="storefront-field storefront-field--compact">
                        <span>Qty</span>
                        <input
                          type="number"
                          min="1"
                          max={detail.purchase?.qtyMax || undefined}
                          value={quantity}
                          onChange={(event) =>
                            setQuantity(Math.max(1, Number(event.target.value || 1)))
                          }
                        />
                      </label>
                    </div>
                    {submitError ? (
                      <p className="storefront-drawer__error">{submitError}</p>
                    ) : null}
                    <div className="storefront-drawer__actions">
                      <button
                        className="storefront-button storefront-button--primary"
                        type="button"
                        disabled={
                          submitState === "submitting" ||
                          !detail.purchase?.canAddToCart
                        }
                        onClick={() => submitCart({ buyNow: false })}
                      >
                        {submitState === "submitting" ? "Adding..." : "Add to cart"}
                      </button>
                      <button
                        className="storefront-button storefront-button--ghost"
                        type="button"
                        disabled={
                          submitState === "submitting" ||
                          !detail.purchase?.canAddToCart
                        }
                        onClick={() => submitCart({ buyNow: true })}
                      >
                        Buy now
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="storefront-drawer__details">
              {detailDescription ? (
                <section className="storefront-detailSection">
                  <h3>Description</h3>
                  <p>{detailDescription}</p>
                </section>
              ) : null}

              {detail.compatibility?.note || detail.compatibility?.items?.length ? (
                <section className="storefront-detailSection">
                  <h3>Compatibility</h3>
                  {compatibilityNote ? <p>{compatibilityNote}</p> : null}
                  {detail.compatibility.items?.length ? (
                    <ul className="storefront-detailList">
                      {detail.compatibility.items.map((item) => (
                        <li key={item.key || item.label}>{item.label}</li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              ) : null}

              {detail.specs?.length ? (
                <section className="storefront-detailSection">
                  <h3>Specifications</h3>
                  <dl className="storefront-specs">
                    {detail.specs.map((spec) => (
                      <div className="storefront-specs__row" key={spec.label}>
                        <dt>{spec.label}</dt>
                        <dd>{spec.value}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ) : null}

              {detail.relatedProducts?.length ? (
                <section className="storefront-detailSection">
                  <h3>Works well with</h3>
                  <div className="storefront-related">
                    {detail.relatedProducts.map((product) => (
                      <button
                        className="storefront-related__card"
                        key={product.id}
                        type="button"
                        onClick={() => onOpenRelated(product)}
                      >
                        {product.image?.src ? (
                          <img
                            src={product.image.src}
                            alt={product.image.alt || product.name}
                          />
                        ) : (
                          <div className="storefront-related__fallback" />
                        )}
                        <span>{product.name}</span>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}

              {detail.fitmentRequest?.enabled ? (
                <section className="storefront-detailSection storefront-detailSection--accent">
                  <p className="storefront-empty__eyebrow">
                    {detail.fitmentRequest.eyebrow}
                  </p>
                  <h3>{detail.fitmentRequest.title}</h3>
                  <p>{detail.fitmentRequest.intro}</p>
                  {fitmentSuccess ? (
                    <div className="storefront-formAlert storefront-formAlert--success">
                      {fitmentSuccess}
                    </div>
                  ) : null}
                  {fitmentFormError ? (
                    <div className="storefront-formAlert storefront-formAlert--error">
                      {fitmentFormError}
                    </div>
                  ) : null}
                  <form className="storefront-formGrid" onSubmit={submitFitmentRequest}>
                    {(detail.fitmentRequest.fields || []).map((field) => (
                      <StorefrontFormField
                        key={field.name}
                        field={field}
                        value={fitmentValues[field.name] || ""}
                        error={fitmentErrors[field.name]?.[0] || ""}
                        onChange={(name, value) => {
                          setFitmentValues((current) => ({ ...current, [name]: value }));
                          setFitmentErrors((current) => ({ ...current, [name]: [] }));
                        }}
                        file={field.inputType === "file" ? fitmentFile : null}
                        onFileChange={(_, file) => {
                          setFitmentFile(file);
                          setFitmentErrors((current) => ({
                            ...current,
                            reference_image: [],
                          }));
                        }}
                        previewUrl={field.inputType === "file" ? fitmentPreviewUrl : ""}
                        helperText={
                          field.inputType === "file"
                            ? "JPG, PNG, or WEBP recommended."
                            : ""
                        }
                      />
                    ))}
                    <div className="storefront-formActions storefront-formField--full">
                      <button
                        className="storefront-button storefront-button--primary"
                        type="submit"
                        disabled={fitmentStatus === "submitting"}
                      >
                        {fitmentStatus === "submitting"
                          ? "Submitting..."
                          : detail.fitmentRequest.submitLabel}
                      </button>
                      <p>{detail.fitmentRequest.footnote}</p>
                    </div>
                  </form>
                </section>
              ) : null}

              {detail.reviews?.enabled ? (
                <section className="storefront-detailSection">
                  <h3>Reviews</h3>
                  <p>
                    {detail.reviews?.stats?.count
                      ? `Average ${Number(
                          detail.reviews.stats.average || 0
                        ).toFixed(1)}/5 from ${detail.reviews.stats.count} review${
                          detail.reviews.stats.count === 1 ? "" : "s"
                        }.`
                      : "No reviews yet. Be the first to leave one."}
                  </p>
                  {detail.reviews?.items?.length ? (
                    <div className="storefront-reviewList">
                      {detail.reviews.items.map((review) => (
                        <article className="storefront-reviewCard" key={review.id}>
                          <div className="storefront-reviewCard__stars">
                            {review.stars}
                          </div>
                          {review.title ? (
                            <h4 className="storefront-reviewCard__title">
                              {review.title}
                            </h4>
                          ) : null}
                          <p className="storefront-reviewCard__body">{review.body}</p>
                          <div className="storefront-reviewCard__author">
                            {review.reviewerName}
                            {review.reviewerTitle
                              ? ` - ${review.reviewerTitle}`
                              : ""}
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : null}
                  {reviewSuccess ? (
                    <div className="storefront-formAlert storefront-formAlert--success">
                      {reviewSuccess}
                    </div>
                  ) : null}
                  {reviewFormError ? (
                    <div className="storefront-formAlert storefront-formAlert--error">
                      {reviewFormError}
                    </div>
                  ) : null}
                  <form className="storefront-formGrid" onSubmit={submitReview}>
                    {(detail.reviews.fields || []).map((field) => (
                      <StorefrontFormField
                        key={field.name}
                        field={field}
                        value={reviewValues[field.name] || ""}
                        error={reviewErrors[field.name]?.[0] || ""}
                        onChange={(name, value) => {
                          setReviewValues((current) => ({ ...current, [name]: value }));
                          setReviewErrors((current) => ({ ...current, [name]: [] }));
                        }}
                      />
                    ))}
                    <div className="storefront-formActions storefront-formField--full">
                      <button
                        className="storefront-button storefront-button--primary"
                        type="submit"
                        disabled={reviewStatus === "submitting"}
                      >
                        {reviewStatus === "submitting"
                          ? "Submitting..."
                          : detail.reviews.submitLabel}
                      </button>
                    </div>
                  </form>
                </section>
              ) : null}
            </div>
          </div>
        ) : null}
      </aside>
    </>
  );
}

export default function App({ bootstrap }) {
  const mode = bootstrap.mode || "store";
  const config = PAGE_CONFIG[mode] || PAGE_CONFIG.store;
  const pageRenderedAtRef = useRef(Date.now());
  const resultsRef = useRef(null);
  const [state, setState] = useState(bootstrap.initialState || {});
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [isMobileViewport, setIsMobileViewport] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(max-width: 900px)").matches
      : false
  );
  const [searchInput, setSearchInput] = useState(
    bootstrap.initialState?.filters?.search || ""
  );
  const deferredSearch = useDeferredValue(searchInput);
  const [listingStatus, setListingStatus] = useState("ready");
  const [listingError, setListingError] = useState("");
  const [activeProductSlug, setActiveProductSlug] = useState(
    getProductSlugFromLocation()
  );
  const [detail, setDetail] = useState(null);
  const [detailStatus, setDetailStatus] = useState(activeProductSlug ? "loading" : "idle");
  const [toast, setToast] = useState("");
  const [cart, setCart] = useState(bootstrap.cart || {});
  const [isPending, startTransition] = useTransition();
  const listingAbortRef = useRef(null);
  const detailAbortRef = useRef(null);
  const listingLoaderRef = useRef(null);

  function loadListingFromLocation() {
    if (listingAbortRef.current) {
      listingAbortRef.current.abort();
    }
    const controller = new AbortController();
    listingAbortRef.current = controller;
    setListingStatus("loading");
    setListingError("");

    fetch(getJsonFromLocation(bootstrap.endpoints.listing), {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Could not refresh the storefront.");
        }
        return response.json();
      })
      .then((payload) => {
        startTransition(() => {
          setState(payload);
          setSearchInput(payload.filters?.search || "");
        });
        setListingStatus("ready");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setListingStatus("error");
        setListingError(error.message || "Could not refresh the storefront.");
      });
  }

  listingLoaderRef.current = loadListingFromLocation;

  function scrollToResultsTop({ behavior = "smooth" } = {}) {
    const target = resultsRef.current;
    if (!target) return;
    const topbar = document.querySelector(".bgm-topbar, .site-header");
    const topbarHeight =
      topbar?.getBoundingClientRect().height ||
      Number.parseFloat(
        getComputedStyle(document.body).getPropertyValue("--bgm-topbar-height")
      ) ||
      0;
    const nextTop =
      target.getBoundingClientRect().top + window.scrollY - topbarHeight - 12;
    window.scrollTo({
      top: Math.max(0, nextTop),
      behavior,
    });
  }

  function applyPatch(patch, options = {}) {
    patchLocation(patch, options);
    setFiltersOpen(false);
    setActiveProductSlug(getProductSlugFromLocation());
    if (options.scrollToResults) {
      scrollToResultsTop({ behavior: options.scrollBehavior || "smooth" });
    }
    if (options.load === false) return;
    listingLoaderRef.current?.();
  }

  function openProduct(product) {
    if (!product?.slug) {
      if (product?.detailUrl) {
        window.location.href = product.detailUrl;
      }
      return;
    }
    setFiltersOpen(false);
    patchLocation({ product: product.slug });
    setActiveProductSlug(product.slug);
  }

  function closeProduct() {
    patchLocation({ product: "" });
    setActiveProductSlug("");
    setDetail(null);
    setDetailStatus("idle");
  }

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 900px)");
    const syncViewport = () => setIsMobileViewport(mediaQuery.matches);
    syncViewport();
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener("change", syncViewport);
      return () => mediaQuery.removeEventListener("change", syncViewport);
    }
    mediaQuery.addListener(syncViewport);
    return () => mediaQuery.removeListener(syncViewport);
  }, []);

  useEffect(() => {
    const syncShellMetrics = () => {
      const topbar = document.querySelector(".bgm-topbar, .site-header");
      const topOffset = topbar?.getBoundingClientRect().bottom || 72;
      const viewportHeight = window.visualViewport?.height || window.innerHeight;
      document.documentElement.style.setProperty(
        "--storefront-mobile-top-offset",
        `${Math.ceil(topOffset + 8)}px`
      );
      document.documentElement.style.setProperty(
        "--storefront-mobile-viewport-height",
        `${Math.ceil(viewportHeight)}px`
      );
    };

    syncShellMetrics();
    window.addEventListener("resize", syncShellMetrics);
    window.addEventListener("orientationchange", syncShellMetrics);
    window.visualViewport?.addEventListener("resize", syncShellMetrics);
    window.visualViewport?.addEventListener("scroll", syncShellMetrics);

    return () => {
      window.removeEventListener("resize", syncShellMetrics);
      window.removeEventListener("orientationchange", syncShellMetrics);
      window.visualViewport?.removeEventListener("resize", syncShellMetrics);
      window.visualViewport?.removeEventListener("scroll", syncShellMetrics);
    };
  }, []);

  useEffect(() => {
    const onPopState = () => {
      setActiveProductSlug(getProductSlugFromLocation());
      listingLoaderRef.current?.();
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (isMobileViewport) return undefined;
    if (deferredSearch === (state.filters?.search || "")) return undefined;
    const timer = window.setTimeout(() => {
      applyPatch(
        {
          q: deferredSearch,
          page: "",
          product: "",
        },
        { replace: true }
      );
    }, 220);
    return () => window.clearTimeout(timer);
  }, [deferredSearch, isMobileViewport, state.filters?.search]);

  useEffect(() => {
    if (!activeProductSlug) {
      setDetail(null);
      setDetailStatus("idle");
      return undefined;
    }

    if (detailAbortRef.current) {
      detailAbortRef.current.abort();
    }
    const controller = new AbortController();
    detailAbortRef.current = controller;
    setDetailStatus("loading");

    fetch(`/store/p/${activeProductSlug}/?format=json`, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Product details are unavailable.");
        }
        return response.json();
      })
      .then((payload) => {
        setDetail(payload);
        setDetailStatus("ready");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setDetailStatus("error");
        setDetail(null);
        setToast(error.message || "Product details are unavailable.");
      });

    return () => controller.abort();
  }, [activeProductSlug]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    updateCartBadge(cart);
  }, [cart]);

  useEffect(() => {
    const shouldLockScroll = Boolean(activeProductSlug) || filtersOpen;
    document.body.classList.toggle("storefront-overlay-open", shouldLockScroll);
    return () => document.body.classList.remove("storefront-overlay-open");
  }, [activeProductSlug, filtersOpen]);

  const categories = state.filters?.available?.categories || [];
  const summary = buildSummary(state, config);
  const emptyResultsLabel =
    bootstrap.page?.labels?.emptyResults || config.emptyBody;
  const heroLead = plainText(bootstrap.page?.lead || "");

  return (
    <div className={`storefront-app storefront-app--${mode}`}>
      <section className="storefront-hero">
        <div className="storefront-hero__content">
          <div className="storefront-hero__copy">
            <p className="storefront-hero__eyebrow">
              {bootstrap.page?.kicker || config.eyebrow}
            </p>
            <h1>{bootstrap.page?.title || "Storefront"}</h1>
            {heroLead ? <p>{heroLead}</p> : null}
            <div className="storefront-hero__actions">
              {bootstrap.page?.primaryCta?.href ? (
                <a className="storefront-button storefront-button--primary" href={bootstrap.page.primaryCta.href}>
                  {bootstrap.page.primaryCta.label}
                </a>
              ) : null}
              {bootstrap.page?.secondaryCta?.href ? (
                <a className="storefront-button storefront-button--ghost" href={bootstrap.page.secondaryCta.href}>
                  {bootstrap.page.secondaryCta.label}
                </a>
              ) : null}
            </div>
          </div>

          <div className="storefront-hero__visual">
            {bootstrap.page?.heroMedia?.src ? (
              <img
                src={bootstrap.page.heroMedia.src}
                alt={bootstrap.page.heroMedia.alt || bootstrap.page.title || "Storefront"}
              />
            ) : (
              <div className="storefront-hero__fallback" />
            )}
          </div>
        </div>
      </section>

      <section className="storefront-shell">
        <div className="storefront-shell__top">
          <div className="storefront-shell__intro">
            <p className="storefront-shell__eyebrow">
              {bootstrap.page?.labels?.browseTitle || "Browse"}
            </p>
            <h2>{bootstrap.page?.labels?.browseDescription || config.resultsLabel}</h2>
          </div>

          <div className="storefront-toolbar">
            <div>
              <strong>{state.catalog?.pagination?.totalResults || 0}</strong>
              <span>{config.resultsLabel}</span>
            </div>
            <div>
              <strong>{state.filters?.activeChips?.length || 0}</strong>
              <span>Active filters</span>
            </div>
          </div>
        </div>

        {categories.length ? (
          <CategoryBrowser
            categories={categories}
            selectedCategory={state.filters?.selected?.category}
            onSelect={(category) =>
              applyPatch({
                category,
                page: "",
                product: "",
              })
            }
            onClear={() =>
              applyPatch({
                category: "",
                page: "",
                product: "",
              })
            }
          />
        ) : null}

        <div className="storefront-layout">
          <FilterPanel
            mode={mode}
            state={state}
            filtersOpen={filtersOpen}
            setFiltersOpen={setFiltersOpen}
            isMobileViewport={isMobileViewport}
            onPatch={applyPatch}
            searchInput={searchInput}
            setSearchInput={setSearchInput}
          />

          <div className="storefront-results">
            <div ref={resultsRef} />
            <div className="storefront-results__header">
              <div>
                <p className="storefront-results__eyebrow">{config.resultsLabel}</p>
                <h3>{summary}</h3>
              </div>
              <button
                className="storefront-button storefront-button--ghost storefront-results__reset"
                type="button"
                onClick={() =>
                  applyPatch({
                    q: "",
                    category: "",
                    make: "",
                    model: "",
                    year: "",
                    price: "",
                    page: "",
                    product: "",
                    sort: "featured",
                  })
                }
              >
                {bootstrap.page?.labels?.clearFilters || "Clear filters"}
              </button>
            </div>

            <Chips
              chips={state.filters?.activeChips || []}
              resetLabel={bootstrap.page?.labels?.clearFilters || "Clear filters"}
              onReset={() =>
                applyPatch({
                  q: "",
                  category: "",
                  make: "",
                  model: "",
                  year: "",
                  price: "",
                  page: "",
                  product: "",
                  sort: "featured",
                })
              }
              onRemove={(chip) => {
                const nextPatch = {
                  [chip.key]: "",
                  page: "",
                  product: "",
                };
                if (chip.key === "make") {
                  nextPatch.model = "";
                }
                applyPatch(nextPatch);
              }}
            />

            {listingStatus === "error" ? (
              <section className="storefront-empty">
                <p className="storefront-empty__eyebrow">Catalog refresh failed</p>
                <h3>{listingError || "Could not refresh the storefront."}</h3>
                <button
                  className="storefront-button storefront-button--primary"
                  type="button"
                  onClick={() => loadListingFromLocation()}
                >
                  Retry
                </button>
              </section>
            ) : null}

            {(listingStatus === "loading" || isPending) && !state.catalog?.products?.length ? (
              <LoadingCards />
            ) : null}

            {!state.catalog?.products?.length &&
            listingStatus !== "loading" &&
            listingStatus !== "error" ? (
              <EmptyState
                title={config.emptyTitle}
                body={emptyResultsLabel}
                resetLabel={bootstrap.page?.labels?.clearFilters || "Clear filters"}
                onReset={() =>
                  applyPatch({
                    q: "",
                    category: "",
                    make: "",
                    model: "",
                    year: "",
                    price: "",
                    page: "",
                    product: "",
                    sort: "featured",
                  })
                }
              />
            ) : null}

            {state.catalog?.products?.length ? (
              <>
                <div
                  className={`storefront-grid ${
                    state.catalog.products.length === 1
                      ? "storefront-grid--single"
                      : ""
                  }`}
                >
                  {state.catalog.products.map((product) => (
                    <ProductCard
                      key={`${product.mode}-${product.id}`}
                      mode={mode}
                      product={product}
                      onOpen={openProduct}
                    />
                  ))}
                </div>

                <Pagination
                  pagination={state.catalog.pagination}
                  onChange={(page) =>
                    applyPatch({
                      page: String(page),
                      product: "",
                    }, {
                      scrollToResults: true,
                    })
                  }
                />
              </>
            ) : null}
          </div>
        </div>
      </section>

      <QuickViewDrawer
        config={config}
        detail={detail}
        detailStatus={detailStatus}
        productSlug={activeProductSlug}
        onClose={closeProduct}
        onOpenRelated={openProduct}
        onCartUpdate={(nextCart) => setCart(nextCart || {})}
        setToast={setToast}
        pageRenderedAt={pageRenderedAtRef.current}
      />

      {toast ? <div className="storefront-toast">{toast}</div> : null}
    </div>
  );
}
