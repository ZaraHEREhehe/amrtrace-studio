// turns stored JSON (explanations, scopes, contexts) into readable fields instead of one long string
import { drugLabel } from "./drug_label.mjs";

const MAX_DEPTH = 4;
const LONG_TEXT = 40;


const ACRONYMS = new Set(["id", "ast", "mic", "db", "dep"]);


export function humanizeKey(key) {
  const words = String(key)
    .replace(/[_-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => (ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word));
  const text = words.join(" ");
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}


// a string that holds a JSON object or list is opened up; any other string stays as it is
function openJsonText(value) {
  if (typeof value !== "string") {
    return value;
  }

  const text = value.trim();
  const looksLikeJson =
    (text.startsWith("{") && text.endsWith("}")) ||
    (text.startsWith("[") && text.endsWith("]"));

  if (!looksLikeJson) {
    return value;
  }

  try {
    return JSON.parse(text);
  } catch {
    return value;
  }
}


function isScalar(value) {
  return value === null || typeof value !== "object";
}


export function describeValue(input, depth = 0) {
  const value = openJsonText(input);

  if (value === null || value === undefined || value === "") {
    return { kind: "empty" };
  }

  if (typeof value === "boolean") {
    return { kind: "text", text: value ? "Yes" : "No" };
  }

  if (typeof value !== "object") {
    const text = drugLabel(String(value));
    return {
      kind: "text",
      text,
      identifier: text.length > LONG_TEXT && !/\s/.test(text),
    };
  }

  if (depth >= MAX_DEPTH) {
    return { kind: "code", text: JSON.stringify(value) };
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return { kind: "none" };
    }

    const items = value.map((item) => describeValue(item, depth + 1));
    return { kind: value.every(isScalar) ? "chips" : "list", items };
  }

  const entries = Object.entries(value);

  if (entries.length === 0) {
    return { kind: "none" };
  }

  return {
    kind: "fields",
    fields: entries.map(([key, item]) => ({
      label: humanizeKey(key),
      value: describeValue(item, depth + 1),
    })),
  };
}


// a short one-line form for table cells: "mic 1 · sign <="
export function summarizeInline(input) {
  const value = openJsonText(input);

  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    const model = describeValue(value);
    return model.kind === "text"
      ? [{ label: "", text: model.text }]
      : [{ label: "", text: Array.isArray(value) ? value.map(String).join(", ") : "—" }];
  }

  return Object.entries(value).map(([key, item]) => ({
    label: key.replace(/_/g, " "),
    text: isScalar(item)
      ? String(item ?? "—")
      : Array.isArray(item) && item.every(isScalar)
        ? item.join(", ") || "none"
        : JSON.stringify(item),
  }));
}


function node(doc, tag, className, text) {
  const element = doc.createElement(tag);

  if (className) {
    element.className = className;
  }

  if (text !== undefined) {
    element.textContent = text;
  }

  return element;
}


function middleShorten(text) {
  return text.length > 30 ? `${text.slice(0, 16)}…${text.slice(-8)}` : text;
}


export function renderModel(model, doc = document) {
  if (model.kind === "empty") {
    return node(doc, "span", "value-empty", "—");
  }

  if (model.kind === "none") {
    return node(doc, "span", "value-empty", "None");
  }

  if (model.kind === "code") {
    return node(doc, "code", "value-code", model.text);
  }

  if (model.kind === "text") {
    if (!model.identifier) {
      return node(doc, "span", "value-text", model.text);
    }

    const id = node(doc, "span", "value-id", middleShorten(model.text));
    id.title = model.text;
    return id;
  }

  if (model.kind === "chips") {
    const wrap = node(doc, "span", "value-chips");

    for (const item of model.items) {
      wrap.append(node(doc, "span", "value-chip", item.text ?? "—"));
    }

    return wrap;
  }

  if (model.kind === "list") {
    const list = node(doc, "ol", "value-list");

    for (const item of model.items) {
      const li = node(doc, "li");
      li.append(renderModel(item, doc));
      list.append(li);
    }

    return list;
  }

  const fields = node(doc, "dl", "value-fields");

  for (const field of model.fields) {
    fields.append(
      node(doc, "dt", "", field.label),
      (() => {
        const dd = node(doc, "dd");
        dd.append(renderModel(field.value, doc));
        return dd;
      })(),
    );
  }

  return fields;
}


export function renderValue(value, doc = document) {
  return renderModel(describeValue(value), doc);
}


export function renderInline(value, doc = document) {
  const wrap = node(doc, "span", "value-chips");

  for (const part of summarizeInline(value)) {
    const chip = node(doc, "span", "value-chip");

    if (part.label) {
      chip.append(node(doc, "span", "value-chip-key", part.label), doc.createTextNode(" "));
    }

    chip.append(doc.createTextNode(part.text));
    wrap.append(chip);
  }

  return wrap;
}
