/* Shared behaviour for the public OpenHUD site. */
(function () {
  const nav = document.getElementById("nav");
  const toggle = document.getElementById("nav-toggle");
  if (toggle && nav) toggle.addEventListener("click", () => nav.classList.toggle("open"));

  fetch("/version")
    .then((r) => r.json())
    .then((d) => {
      const el = document.getElementById("foot-version");
      if (el) el.textContent = d.version;
    })
    .catch(() => {});
})();
