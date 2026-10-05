/* OpenHUD AI — shared behaviour for the public site. */
(function () {
  "use strict";
  const nav = document.getElementById("nav");
  const toggle = document.getElementById("nav-toggle");
  if (toggle && nav) {
    const header = nav.closest("header.site");
    toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (header) header.classList.toggle("menu-open", open);
    });
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
