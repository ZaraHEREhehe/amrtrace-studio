// case dossier tabs: shows one section at a time so the page starts with the answer, not the whole record
const tabs = Array.from(document.querySelectorAll("[data-dossier-tab]"));
const panels = new Map(
  Array.from(document.querySelectorAll("[data-dossier-panel]")).map((p) => [p.dataset.dossierPanel, p]),
);

function show(name, focus) {
  for (const tab of tabs) {
    const on = tab.dataset.dossierTab === name;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    if (on && focus) tab.focus();
  }
  for (const [key, panel] of panels) panel.hidden = key !== name;
}

for (const tab of tabs) {
  tab.addEventListener("click", () => show(tab.dataset.dossierTab));
  tab.addEventListener("keydown", (e) => {
    const i = tabs.indexOf(tab);
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (step) { e.preventDefault(); show(tabs[(i + step + tabs.length) % tabs.length].dataset.dossierTab, true); }
  });
}

// opening a different case brings the reader back to the overview
document.getElementById("dossier-form")?.addEventListener("submit", () => show("overview"));
show("overview");
