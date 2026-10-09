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
