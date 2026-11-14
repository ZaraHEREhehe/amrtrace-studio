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
      (!identity.selective_run_id || !identity.exhaustive_run_id ||
       identity.comparison_passed !== true)) {
    throw new Error(
      "This release has a missing or failed comparison record. Inspect the release before exporting.",
    );
  }
  return identity;
}

