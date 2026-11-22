// Read-side release identity checks. No changes to publication or review state.
export function assertDossierIdentity(dossier, history, diff, dependencies, reviews) {
  const current = dossier?.current_state ?? null;
  const after = diff?.after ?? null;
  const states = Array.isArray(history) ? history : [];
  const published = states.filter((item) => item.release_status === "PUBLISHED");
  const latest = published.at(-1) ?? null;
  const stateId = current?.state_id ?? null;
  const stale = () => {
    throw new Error(
      "Published case history changed while this dossier was loading. Reload the dossier to see one consistent release.",
    );
  };

  if ((after?.state_id ?? null) !== stateId ||
      (latest?.state_id ?? null) !== stateId) stale();
  if (current && dependencies && dependencies.release_id !== current.release_id) stale();
  if ((reviews ?? []).some((review) => !states.some((state) => state.state_id === review.state_id))) stale();
  if (current) {
    const currentReviews = (reviews ?? []).filter((review) => review.state_id === stateId);
    const latestAction = currentReviews.at(-1)?.action ?? null;
    const actionStatus = {
      CONFIRM: "CONFIRMED",
      CORRECT: "CORRECTED",
      MARK_UNRESOLVED: "MARKED_UNRESOLVED",
    };
    if (latestAction && dossier.review_status !== actionStatus[latestAction]) stale();
    if (!latestAction &&
        ["CONFIRMED", "CORRECTED", "MARKED_UNRESOLVED"].includes(dossier.review_status)) stale();
  }
  return current?.release_id ?? null;
}


export function assertReleaseIdentity(requestedReleaseId, identity) {
  if (!identity || identity.release_id !== requestedReleaseId ||
      identity.status !== "PUBLISHED") {
    throw new Error(
      "The selected release changed or is not published. Reload the release list before exporting.",
    );
  }
  if (identity.report_id != null &&
      (!identity.selective_run_id || !identity.exhaustive_run_id)) {
    throw new Error(
      "This release has an incomplete comparison record. Inspect the release before exporting.",
    );
  }
  // I-27: a failed Admin audit of a selectively verified release is recorded against it and shown, but the release
  // stays published (history is never rewritten), so it can still be exported. Any other failed comparison refuses.
  const failedAudit = identity.comparison_kind === "AUDIT" && identity.verification_level === "SELECTIVE";
  if (identity.report_id != null && identity.comparison_passed !== true && !failedAudit) {
    throw new Error(
      "This release has a missing or failed comparison record. Inspect the release before exporting.",
    );
  }
  return identity;
}


// I-27: how a published release was verified, in words; a selectively verified release never reads as fully checked
export function verificationText(identity) {
  const level = identity?.verification_level ?? null;
  if (!identity?.change_id) return "Not a change release (baseline or full load)";
  if (level === "EXHAUSTIVE") return "Exhaustively verified (comparison passed before publishing)";
  if (level !== "SELECTIVE") return "Verification level not recorded (published before I-27)";
  if (identity.audit_passed === true) {
    return `Selectively verified · Admin audit passed (report #${identity.audit_report_id})`;
  }
  if (identity.audit_passed === false) {
    return `Selectively verified · Admin audit FAILED (report #${identity.audit_report_id}); see the review queue`;
  }
  return "Selectively verified · not audited";
}


// an Admin may audit a published, selectively verified release that has no audit yet (one per change)
export function canAudit(identity) {
  return identity?.status === "PUBLISHED" && identity?.verification_level === "SELECTIVE" &&
    identity?.audit_report_id == null;
}


export function comparisonText(identity) {
  if (identity?.report_id == null) return "No stored comparison";
  const kind = identity.comparison_kind === "AUDIT" ? "Audit" : "Gate";
  const result = identity.comparison_passed === true ? "PASS" : "FAILED";
  return `${kind} ${result} · report #${identity.report_id} · run ${identity.selective_run_id}`;
}

