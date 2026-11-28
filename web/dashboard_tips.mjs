// small helpers for the dashboard charts

// long drug names get their usual short form in the narrow chart labels
export function shortDrugName(name) {
  return name === "trimethoprim-sulfamethoxazole" ? "TMP" : name;
}

// a hover card with a title and label/value lines
export function hoverTip(title, lines) {
  const tip = document.createElement("div");
  tip.className = "chart-tip";
  tip.setAttribute("role", "tooltip");

  const heading = document.createElement("strong");
  heading.textContent = title;
  tip.append(heading);

  for (const [label, value] of lines) {
    const line = document.createElement("div");
    const name = document.createElement("span");
    const amount = document.createElement("span");
    name.textContent = label;
    amount.textContent = value;
    line.append(name, amount);
    tip.append(line);
  }

  return tip;
}
