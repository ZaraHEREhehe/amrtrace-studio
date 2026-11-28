// collapsible sidebar: icons only when collapsed, and the choice is remembered
const KEY = "amrtrace.sidebar.collapsed";
const shell = document.querySelector(".app-shell");
const toggles = document.querySelectorAll(".sidebar-toggle");

function remembered() {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function remember(collapsed) {
  try {
    window.localStorage.setItem(KEY, collapsed ? "1" : "0");
  } catch {
    // the sidebar still works without saving the choice
  }
}

function apply(collapsed) {
  shell.classList.toggle("sidebar-collapsed", collapsed);

  for (const toggle of toggles) {
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    toggle.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  }
}

if (shell && toggles.length) {
  // each item shows its name as a tooltip when only the icon is visible
  for (const item of document.querySelectorAll(".nav-button")) {
    const label = item.querySelector(".nav-label");

    if (label) {
      item.title = label.textContent.trim();
    }
  }

  apply(remembered());

  for (const toggle of toggles) {
    toggle.addEventListener("click", () => {
      const collapsed = !shell.classList.contains("sidebar-collapsed");
      apply(collapsed);
      remember(collapsed);
    });
  }
}
