(function () {
    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function getCSRFToken() {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function postForm(url, payload) {
        return fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCSRFToken(),
            },
            body: new URLSearchParams(payload).toString(),
            credentials: "same-origin",
        }).then((resp) => resp.json());
    }

    function ensureToastHost() {
        let host = document.querySelector("[data-admin-toast-host]");
        if (!host) {
            host = document.createElement("div");
            host.className = "admin-toast-host";
            host.setAttribute("data-admin-toast-host", "");
            document.body.appendChild(host);
        }
        return host;
    }

    function showToast(message, opts) {
        const host = ensureToastHost();
        const toast = document.createElement("div");
        toast.className = "admin-toast";
        toast.innerHTML = `<span class="admin-toast__message"></span>`;
        toast.querySelector(".admin-toast__message").textContent = message;

        if (opts && opts.undo) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "admin-toast__undo";
            btn.textContent = "Undo";
            btn.addEventListener("click", function () {
                opts.undo();
                toast.remove();
            });
            toast.appendChild(btn);
        }

        host.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add("is-visible"));
        window.setTimeout(() => {
            toast.classList.remove("is-visible");
            window.setTimeout(() => toast.remove(), 180);
        }, 4200);
    }

    function renderSearchResults(groups, container) {
        if (!container) {
            return;
        }
        if (!groups || !groups.length) {
            container.innerHTML = `
                <div class="admin-search-suggest__empty">
                    <strong>No quick matches</strong>
                    <span>Press enter to open full search.</span>
                </div>
            `;
            container.classList.remove("hidden");
            return;
        }

        container.innerHTML = groups.map(group => {
            const items = (group.items || []).map(item => `
                <a class="admin-search-suggest__item" href="${escapeHtml(item.url)}">
                    <span class="admin-search-suggest__icon"><i class="${escapeHtml(item.icon || 'fas fa-circle')}" aria-hidden="true"></i></span>
                    <span class="admin-search-suggest__body">
                        <span class="admin-search-suggest__label">${escapeHtml(item.label)}</span>
                        <span class="admin-search-suggest__meta">${escapeHtml(item.category || group.title)}${item.note ? " · " + escapeHtml(item.note) : ""}</span>
                    </span>
                </a>
            `).join("");
            return `
                <div class="admin-search-suggest__group">
                    <div class="admin-search-suggest__title">${escapeHtml(group.title)}</div>
                    <div class="admin-search-suggest__items">${items}</div>
                </div>
            `;
        }).join("");
        container.classList.remove("hidden");
    }

    document.addEventListener("DOMContentLoaded", function () {
        const searchForm = document.querySelector(".admin-global-search");
        if (!searchForm) {
            return;
        }

        const input = searchForm.querySelector(".admin-global-search__input");
        const results = searchForm.querySelector("[data-search-results]");
        const favoriteBtn = searchForm.querySelector("[data-favorite-toggle]");
        const suggestUrl = searchForm.dataset.searchSuggestUrl || "";
        const favoriteUrl = searchForm.dataset.favoriteToggleUrl || "";
        const trackUrl = searchForm.dataset.trackUrl || "";
        const pagePayload = {
            url: searchForm.dataset.currentUrl || "",
            label: searchForm.dataset.currentLabel || "",
            icon: searchForm.dataset.currentIcon || "fas fa-star",
            category: searchForm.dataset.currentCategory || "Admin",
            note: searchForm.dataset.currentNote || "",
        };

        let searchTimer = null;

        function hideResults() {
            if (results) {
                results.classList.add("hidden");
            }
        }

        function syncFavoriteButton(favorited) {
            if (!favoriteBtn) {
                return;
            }
            favoriteBtn.classList.toggle("is-active", !!favorited);
            const icon = favoriteBtn.querySelector("i");
            if (icon) {
                icon.className = `${favorited ? "fas" : "far"} fa-star`;
            }
        }

        if (trackUrl && pagePayload.url && !pagePayload.url.includes("/admin/search/")) {
            postForm(trackUrl, pagePayload).catch(() => {});
        }

        if (favoriteBtn && favoriteUrl && pagePayload.url) {
            favoriteBtn.addEventListener("click", function () {
                postForm(favoriteUrl, Object.assign({ action: "toggle" }, pagePayload))
                    .then((data) => {
                        if (!data || !data.ok) {
                            return;
                        }
                        syncFavoriteButton(data.favorited);
                        showToast(data.message || "Favorites updated.", {
                            undo: data.undo_action ? function () {
                                postForm(favoriteUrl, Object.assign({ action: data.undo_action }, pagePayload))
                                    .then((undoData) => {
                                        if (undoData && undoData.ok) {
                                            syncFavoriteButton(undoData.favorited);
                                        }
                                    })
                                    .catch(() => {});
                            } : null
                        });
                    })
                    .catch(() => {});
            });
        }

        if (input && results && suggestUrl) {
            document.addEventListener("keydown", function (event) {
                const active = document.activeElement;
                const isTypingField = active && (
                    active.tagName === "INPUT" ||
                    active.tagName === "TEXTAREA" ||
                    active.isContentEditable
                );
                if ((event.key === "/" && !isTypingField) || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k")) {
                    event.preventDefault();
                    input.focus();
                    input.select();
                }
                if (event.key === "Escape") {
                    hideResults();
                }
            });

            input.addEventListener("input", function () {
                const query = input.value.trim();
                if (searchTimer) {
                    window.clearTimeout(searchTimer);
                }
                if (!query) {
                    hideResults();
                    return;
                }
                searchTimer = window.setTimeout(function () {
                    fetch(`${suggestUrl}?q=${encodeURIComponent(query)}`, {
                        headers: { "X-Requested-With": "XMLHttpRequest" },
                        credentials: "same-origin",
                    })
                        .then((resp) => resp.json())
                        .then((data) => renderSearchResults(data.groups || [], results))
                        .catch(() => hideResults());
                }, 140);
            });

            input.addEventListener("focus", function () {
                if (results && results.innerHTML.trim()) {
                    results.classList.remove("hidden");
                }
            });

            document.addEventListener("click", function (event) {
                if (!searchForm.contains(event.target)) {
                    hideResults();
                }
            });
        }
    });
})();
