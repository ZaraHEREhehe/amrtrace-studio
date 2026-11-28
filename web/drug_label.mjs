// the long co-trimoxazole name is written as TMP wherever it is displayed
const SHORT_NAMES = { "trimethoprim-sulfamethoxazole": "TMP" };

// only the display text changes; filters and links keep using the stored name
export function drugLabel(name) {
  if (typeof name !== "string") {
    return name;
  }

  return SHORT_NAMES[name.toLowerCase()] ?? name;
}
