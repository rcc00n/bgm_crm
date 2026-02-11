(function () {
  function onReady(cb) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", cb, { once: true });
    } else {
      cb();
    }
  }

  function trackManualOverride(input) {
    if (!input) {
      return;
    }
    input.addEventListener("input", () => {
      if (input.dataset.autofill === "true") {
        if (input.value !== input.dataset.autofillValue) {
          delete input.dataset.autofill;
          delete input.dataset.autofillValue;
        }
      }
    });
  }

  function shouldOverwrite(input) {
    if (!input) {
      return false;
    }
    const current = (input.value || "").trim();
    if (!current) {
      return true;
    }
    return (
      input.dataset.autofill === "true" &&
      current === (input.dataset.autofillValue || "")
    );
  }

  function applyValue(input, value) {
    if (!input || !value) {
      return;
    }
    const normalized = value.trim();
    input.value = normalized;
    input.dataset.autofill = "true";
    input.dataset.autofillValue = normalized;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  onReady(() => {
    const clientField = document.getElementById("id_client");
    if (!clientField) {
      return;
    }

    const nameInput = document.getElementById("id_contact_name");
    const emailInput = document.getElementById("id_contact_email");
    const phoneInput = document.getElementById("id_contact_phone");
    [nameInput, emailInput, phoneInput].forEach(trackManualOverride);

    const cache = new Map();
    let lastRequestKey = null;

    function buildUrl(id) {
      return `/admin/api/clients/${encodeURIComponent(id)}/contact/`;
    }

    function fetchContact(clientId) {
      if (cache.has(clientId)) {
        return Promise.resolve(cache.get(clientId));
      }
      return fetch(buildUrl(clientId), { credentials: "same-origin" })
        .then((resp) => {
          if (!resp.ok) {
            throw new Error(`Failed to load contact for #${clientId}`);
          }
          return resp.json();
        })
        .then((data) => {
          cache.set(clientId, data);
          return data;
        })
        .catch((err) => {
          console.error(err);
          return null;
        });
    }

    function hydrate(clientId) {
      const normalized = (clientId || "").toString().trim();
      if (!normalized) {
        return;
      }
      lastRequestKey = normalized;
      fetchContact(normalized).then((payload) => {
        if (!payload || lastRequestKey !== normalized) {
          return;
        }
        const mapping = [
          { key: "name", input: nameInput },
          { key: "email", input: emailInput },
          { key: "phone", input: phoneInput },
        ];
        mapping.forEach(({ key, input }) => {
          const value = (payload[key] || "").trim();
          if (!value || !input) {
            return;
          }
          if (shouldOverwrite(input)) {
            applyValue(input, value);
          } else if (!input.dataset.autofill) {
            const current = (input.value || "").trim();
            if (current === value) {
              input.dataset.autofill = "true";
              input.dataset.autofillValue = value;
            }
          }
        });
      });
    }

    clientField.addEventListener("change", () => {
      hydrate(clientField.value);
    });

    if (clientField.value) {
      hydrate(clientField.value);
    }
  });
})();
