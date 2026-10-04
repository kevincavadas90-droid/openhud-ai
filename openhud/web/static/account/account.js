/* OpenHUD AI — shared client for the account pages. No framework, no build. */
(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function ensureCsrf() {
    let token = getCookie("openhud_csrf");
    if (!token) {
      try {
        const r = await fetch("/api/account/csrf", { credentials: "same-origin" });
        const d = await r.json();
        token = d.csrf || getCookie("openhud_csrf");
      } catch (_) {}
    }
    return token || "";
  }

  async function api(path, body) {
    const csrf = await ensureCsrf();
    const res = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(Object.assign({ csrf }, body || {})),
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const err = new Error((data && data.detail) || "Não foi possível concluir. Tente novamente.");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  async function get(path) {
    const res = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const err = new Error((data && data.detail) || "Não foi possível carregar.");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function fieldError(form, name, message) {
    const el = form.querySelector(`[data-error="${name}"]`);
    if (el) el.textContent = message || "";
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-error]").forEach((el) => (el.textContent = ""));
  }

  function notice(el, message, kind) {
    if (!el) return;
    el.className = "form-notice" + (kind ? " " + kind : "");
    el.textContent = message || "";
    el.hidden = !message;
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.label = button.textContent;
      button.textContent = label || "Aguarde…";
      button.disabled = true;
      button.classList.add("loading");
    } else {
      if (button.dataset.label) button.textContent = button.dataset.label;
      button.disabled = false;
      button.classList.remove("loading");
    }
  }

  async function whoami() {
    try {
      const r = await fetch("/api/account/me", { credentials: "same-origin" });
      return await r.json();
    } catch (_) {
      return { authenticated: false, accounts_enabled: false };
    }
  }

  window.OpenHUD = { $, api, get, fieldError, clearErrors, notice, setBusy, whoami, ensureCsrf };
})();
