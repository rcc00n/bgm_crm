(function () {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }
  if (window.__bgmAnalyticsLoaded) {
    return;
  }
  window.__bgmAnalyticsLoaded = true;

  const dnt = navigator.doNotTrack || window.doNotTrack || navigator.msDoNotTrack;
  if (dnt === "1" || dnt === "yes") {
    return;
  }

  const scriptEl =
    document.currentScript ||
    document.querySelector("script[data-analytics-tracker=\"true\"]");
  const endpoint = scriptEl?.dataset?.endpoint || "/analytics/collect/";
  const sampleRate = Math.min(
    1,
    Math.max(0, parseFloat(scriptEl?.dataset?.sampleRate || "1"))
  );
  const flushInterval = parseInt(scriptEl?.dataset?.flushInterval || "15000", 10);

  if (!endpoint || Math.random() > sampleRate || typeof fetch !== "function") {
    return;
  }

  const now = () => (typeof performance !== "undefined" && performance.now ? performance.now() : Date.now());
  const pageInstanceId =
    (typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : "pv-" + Math.random().toString(36).slice(2) + Date.now().toString(36));

  const startedAt = new Date();
  let accumulated = 0;
  let lastVisibilityMark = document.visibilityState === "visible" ? now() : null;
  let lastReported = 0;
  let finalized = false;

  const captureVisibleTime = () => {
    if (lastVisibilityMark === null) {
      return;
    }
    const current = now();
    accumulated += Math.max(0, current - lastVisibilityMark);
    lastVisibilityMark = current;
  };

  const getCsrfToken = () => {
    const name = "csrftoken";
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (const cookie of cookies) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(name + "=")) {
        return decodeURIComponent(trimmed.substring(name.length + 1));
      }
    }
    return "";
  };

  const sendPayload = (duration, reason) => {
    const payload = {
      page_instance_id: pageInstanceId,
      duration_ms: Math.round(duration),
      started_at: startedAt.toISOString(),
      path: window.location.pathname,
      full_path: window.location.pathname + window.location.search,
      title: document.title || "",
      referrer: document.referrer || "",
      timezone_offset: -new Date().getTimezoneOffset(),
      viewport_width: Math.max(0, Math.round(window.innerWidth || 0)),
      viewport_height: Math.max(0, Math.round(window.innerHeight || 0)),
      reason: reason || "update",
    };

    const body = JSON.stringify(payload);
    const headers = {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    };

    if (
      typeof navigator.sendBeacon === "function" &&
      (reason === "hidden" || reason === "pagehide" || reason === "unload")
    ) {
      try {
        const blob = new Blob([body], { type: "application/json" });
        navigator.sendBeacon(endpoint, blob);
        return;
      } catch (err) {
        // fall through to fetch
      }
    }

    fetch(endpoint, {
      method: "POST",
      headers,
      body,
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {});
  };

  const flush = (reason, { force = false } = {}) => {
    if (finalized) {
      return;
    }
    captureVisibleTime();
    const duration = Math.round(accumulated);
    if (!force && duration - lastReported < 500) {
      return;
    }
    if (duration <= 0) {
      return;
    }
    lastReported = duration;
    sendPayload(duration, reason);
  };

  document.addEventListener(
    "visibilitychange",
    () => {
      if (document.visibilityState === "hidden") {
        captureVisibleTime();
        lastVisibilityMark = null;
        flush("hidden", { force: true });
      } else {
        lastVisibilityMark = now();
      }
    },
    true
  );

  window.addEventListener(
    "pagehide",
    () => {
      captureVisibleTime();
      flush("pagehide", { force: true });
      finalized = true;
    },
    true
  );

  window.addEventListener(
    "beforeunload",
    () => {
      captureVisibleTime();
      flush("unload", { force: true });
      finalized = true;
    },
    true
  );

  if (flushInterval > 0 && Number.isFinite(flushInterval)) {
    setInterval(() => flush("heartbeat"), Math.max(5000, flushInterval));
  }
})();
