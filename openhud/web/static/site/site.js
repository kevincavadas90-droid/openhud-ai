/* OpenHUD AI — shared behaviour for the public site. */
(function () {
  "use strict";
  const nav = document.getElementById("nav");
  const toggle = document.getElementById("nav-toggle");
  if (toggle && nav) {
    toggle.addEventListener("click", () => nav.classList.toggle("open"));
  }
  // Version in the footer (single source: /version).
  fetch("/version")
    .then((r) => r.json())
    .then((d) => {
      const el = document.getElementById("foot-version");
      if (el) el.textContent = d.version;
    })
    .catch(() => {});
})();
