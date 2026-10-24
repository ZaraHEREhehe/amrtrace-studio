// turns a case's label flags (D-22) into what the dossier shows, kept free of the DOM so it can be tested

// the short badge text for a case, or null when interpretation changed no label
export function labelsChangedBadge(count) {
  if (!Number.isInteger(count) || count <= 0) {
    return null;
  }
  return count === 1
    ? "1 label changed by interpretation"
    : `${count} labels changed by interpretation`;
}


// one display row per result, saying whose label stands and where our numbers came from
export function interpretationRows(flags) {
  return (flags ?? []).map((flag) => {
    const derived = flag.label_source === "derived";
    return {
      evidence: flag.ast_evidence_id,
      host: flag.host_group ?? "not recorded",
      labLabel: flag.submitted_label ?? "—",
      shownLabel: derived ? flag.derived_label : flag.submitted_label ?? "—",
      origin: derived ? "Derived from breakpoint" : "Submitted by lab (kept)",
      changed: derived ? (flag.label_changed ? "Yes" : "No") : "—",
      breakpoint: derived ? flag.source ?? "unknown source" : "—",
      species: derived ? flag.breakpoint_species ?? "—" : "—",
      table: derived ? flag.table_version ?? "—" : "—",
    };
  });
}
