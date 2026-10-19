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
