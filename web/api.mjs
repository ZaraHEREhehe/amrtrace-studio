import { csrfToken, clearSession } from "./auth_client.mjs";

const API_ROOT = "/api";


export class ApiError extends Error {
  constructor(status, errorCode, message, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
    this.details = details;
  }
}


export async function requestJson(
  path,
  options = {},
  fetchImpl = globalThis.fetch,
) {
  const requestOptions = {
    method: options.method ?? "GET",
    headers: {
      Accept: "application/json",
      ...(options.headers ?? {}),
    },
  };

  if (!["GET", "HEAD", "OPTIONS"].includes(requestOptions.method.toUpperCase())) {
    const csrf = csrfToken();
    if (csrf) requestOptions.headers["X-CSRF-Token"] = csrf;
  }

  if (options.body !== undefined) {
    requestOptions.headers["Content-Type"] = "application/json";
    requestOptions.body = JSON.stringify(options.body);
  }

  let response;

  try {
    response = await fetchImpl(`${API_ROOT}${path}`, requestOptions);
  } catch (error) {
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the AMRTrace API",
      { cause: String(error) },
    );
  }

  const text = await response.text();
  let payload = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new ApiError(
        response.status,
        "invalid_response",
        "API returned invalid JSON",
        null,
      );
    }
  }

  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new ApiError(
      response.status,
      payload?.error_code ?? "http_error",
      payload?.message ?? `Request failed with status ${response.status}`,
      payload?.details ?? null,
    );
  }

  return payload;
}


export function listChanges(limit = 100, fetchImpl = globalThis.fetch) {
  const params = new URLSearchParams({ limit: String(limit) });

  return requestJson(
    `/changes?${params.toString()}`,
    {},
    fetchImpl,
  );
}


export function listChangeTypes(fetchImpl = globalThis.fetch) {
  return requestJson("/changes/types", {}, fetchImpl);
}


export function createChange(payload, fetchImpl = globalThis.fetch) {
  return requestJson(
    "/changes",
    {
      method: "POST",
      body: payload,
    },
    fetchImpl,
  );
}


export function getChange(changeId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/changes/${encodeURIComponent(changeId)}`,
    {},
    fetchImpl,
  );
}


export function getImpact(changeId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/changes/${encodeURIComponent(changeId)}/impact`,
    {},
    fetchImpl,
  );
}


export function getCaseDependencies(caseId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/dependencies`,
    {},
    fetchImpl,
  );
}

export function startReevaluation(
  changeId,
  payload,
  fetchImpl = globalThis.fetch,
) {
  return requestJson(
    `/changes/${encodeURIComponent(changeId)}/reevaluate`,
    {
      method: "POST",
      body: payload,
    },
    fetchImpl,
  );
}


export function getRun(runId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/runs/${encodeURIComponent(runId)}`,
    {},
    fetchImpl,
  );
}


export function getRunEquivalence(
  runId,
  fetchImpl = globalThis.fetch,
) {
  return requestJson(
    `/runs/${encodeURIComponent(runId)}/equivalence`,
    {},
    fetchImpl,
  );
}

export function getCase(caseId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}`,
    {},
    fetchImpl,
  );
}


export function getCaseHistory(
  caseId,
  fetchImpl = globalThis.fetch,
) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/history`,
    {},
    fetchImpl,
  );
}


export function getCaseReviewStatus(caseId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/review-status`,
    {},
    fetchImpl,
  );
}


export function listReviewQueue(path = "/review-queue?limit=25&offset=0", fetchImpl = globalThis.fetch) {
  return requestJson(path, {}, fetchImpl);
}


export function getCaseReviews(
  caseId,
  fetchImpl = globalThis.fetch,
) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/reviews`,
    {},
    fetchImpl,
  );
}


export function createReview(
  caseId,
  payload,
  fetchImpl = globalThis.fetch,
) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/review`,
    {
      method: "POST",
      body: payload,
    },
    fetchImpl,
  );
}


export function getCaseDiff(
  caseId,
  {
    beforeRelease = null,
    afterRelease = null,
  } = {},
  fetchImpl = globalThis.fetch,
) {
  const params = new URLSearchParams();

  if (beforeRelease) {
    params.set("before_release", beforeRelease);
  }

  if (afterRelease) {
    params.set("after_release", afterRelease);
  }

  const query = params.toString();

  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/diff` +
      (query ? `?${query}` : ""),
    {},
    fetchImpl,
  );
}


// Review Copilot (I-19): generated text about why a case changed, never evidence
export function getCaseCopilot(caseId, fetchImpl = globalThis.fetch) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/copilot`,
    {},
    fetchImpl,
  );
}


export function writeCaseCopilot(
  caseId,
  mode = "templates",
  fetchImpl = globalThis.fetch,
) {
  return requestJson(
    `/cases/${encodeURIComponent(caseId)}/copilot`,
    { method: "POST", body: { mode } },
    fetchImpl,
  );
}


export function listPublishedReleases(fetchImpl = globalThis.fetch) {
  return requestJson("/releases", {}, fetchImpl);
}

export async function getVerifiedExportJson(
  releaseId,
  expectedDigest,
  fetchImpl = globalThis.fetch,
  cryptoImpl = globalThis.crypto?.subtle,
) {
  if (typeof releaseId !== "string" || !releaseId.trim()) {
    throw new TypeError("A release ID is required");
  }

  if (!/^[0-9a-f]{64}$/i.test(expectedDigest ?? "")) {
    throw new TypeError("A valid snapshot hash is required");
  }

  if (!cryptoImpl || typeof cryptoImpl.digest !== "function") {
    throw new ApiError(
      0,
      "crypto_unavailable",
      "SHA-256 verification is unavailable in this browser",
    );
  }

  let response;

  try {
    response = await fetchImpl(exportUrl(releaseId, "json"), {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    throw new ApiError(
      0,
      "network_error",
      "Could not download the AMRTrace export",
      { cause: String(error) },
    );
  }

  if (!response.ok) {
    const body = await response.text();
    let payload = null;

    try {
      payload = JSON.parse(body);
    } catch {
      // HTTP errors do not always contain structured JSON.
    }

    throw new ApiError(
      response.status,
      payload?.error_code ?? "http_error",
      payload?.message ?? `Request failed with status ${response.status}`,
      payload?.details ?? null,
    );
  }

  // Preserve the response bytes. Never parse and reserialize the JSON.
  const buffer = await response.arrayBuffer();
  const hashBuffer = await cryptoImpl.digest("SHA-256", buffer);

  const calculatedDigest = Array.from(
    new Uint8Array(hashBuffer),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");

  const serverDigest = response.headers
    ?.get("X-AMRTrace-Snapshot-SHA256")
    ?.trim()
    .toLowerCase();

  if (
    !/^[0-9a-f]{64}$/.test(serverDigest ?? "") ||
    calculatedDigest !== serverDigest ||
    calculatedDigest !== expectedDigest.toLowerCase()
  ) {
    throw new ApiError(
      response.status,
      "snapshot_hash_mismatch",
      "Export verification failed: JSON bytes do not match the snapshot SHA-256",
    );
  }

  return new Uint8Array(buffer);
}

export function snapshotHashFileText(digest) {
  if (typeof digest !== "string" || !/^[0-9a-f]{64}$/i.test(digest)) {
    throw new TypeError("A valid snapshot hash is required");
  }
  return `${digest.toLowerCase()}\n`;
}

export async function getSnapshotHash(
  releaseId,
  fetchImpl = globalThis.fetch,
) {
  if (typeof releaseId !== "string" || !releaseId.trim()) {
    throw new TypeError("A release ID is required");
  }

  let response;

  try {
    response = await fetchImpl(exportUrl(releaseId, "sha256"), {
      method: "GET",
      headers: { Accept: "text/plain" },
    });
  } catch (error) {
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the AMRTrace API",
      { cause: String(error) },
    );
  }

  if (!response.ok) {
    const body = await response.text();
    let payload = null;

    try {
      payload = JSON.parse(body);
    } catch {
      // An HTTP failure may not contain JSON.
    }

    throw new ApiError(
      response.status,
      payload?.error_code ?? "http_error",
      payload?.message ?? `Request failed with status ${response.status}`,
      payload?.details ?? null,
    );
  }

  const digest = (await response.text()).trim().toLowerCase();

  if (!/^[0-9a-f]{64}$/.test(digest)) {
    throw new ApiError(
      response.status,
      "invalid_response",
      "API returned an invalid SHA-256 hash",
    );
  }

  return digest;
}

export function exportUrl(releaseId, format = "json") {
  if (!["json", "sha256"].includes(format)) {
    throw new TypeError(
      `Unsupported export format: ${format}`,
    );
  }

  const params = new URLSearchParams({
    as_of_release: releaseId,
    format,
  });

  return `${API_ROOT}/export?${params.toString()}`;
}


// turns a short case id, or an accession and drug, into the one full case id it names
export function resolveCase(query, fetchImpl = globalThis.fetch) {
  const params = new URLSearchParams({ q: query });

  return requestJson(
    `/cases/resolve?${params.toString()}`,
    {},
    fetchImpl,
  );
}


// cases whose id or accession starts with what was typed, for the suggestions under the case box
export function searchCases(query, limit = 10, fetchImpl = globalThis.fetch) {
  const params = new URLSearchParams({ q: query, limit: String(limit) });

  return requestJson(
    `/cases?${params.toString()}`,
    {},
    fetchImpl,
  );
}


// stored runs, newest first, optionally only those of one change
export function listRuns(changeId = null, limit = 50, fetchImpl = globalThis.fetch) {
  const params = new URLSearchParams({ limit: String(limit) });

  if (changeId) {
    params.set("change_id", changeId);
  }

  return requestJson(
    `/runs?${params.toString()}`,
    {},
    fetchImpl,
  );
}


// the dashboard numbers, all from the latest published states
export function getSummary(fetchImpl = globalThis.fetch) {
  return requestJson("/summary", {}, fetchImpl);
}


// one page of the case list, filtered by text, drug and current state
export function listCases(filters = {}, fetchImpl = globalThis.fetch) {
  const params = new URLSearchParams({
    limit: String(filters.limit ?? 50),
    offset: String(filters.offset ?? 0),
  });

  for (const key of ["q", "drug", "state"]) {
    if (filters[key]) {
      params.set(key, filters[key]);
    }
  }

  return requestJson(`/cases?${params.toString()}`, {}, fetchImpl);
}
