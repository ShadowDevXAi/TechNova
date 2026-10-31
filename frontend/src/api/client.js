/**
 * Shared HTTP client for the TechNova portal.
 *
 * Responsibilities:
 * - Build the backend URL consistently for every screen.
 * - Attach bearer authentication and the correct JSON/FormData headers.
 * - Apply a request timeout and support caller-provided AbortSignals.
 * - Parse JSON/text responses and preserve HTTP status in ApiError.
 *
 * Do not add automatic retries here: task creation, votes and submissions are
 * non-idempotent and must not be repeated silently.
 */
export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  "https://technova-5h0g.onrender.com"
).replace(/\/$/, "");

/** A normalized API failure with status and request context for UI handling. */
export class ApiError extends Error {
  constructor(message, { status = 0, path = "", payload = null, requestId = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
    this.payload = payload;
    this.requestId = requestId;
  }
}

/**
 * Send a request to the TechNova API.
 *
 * @param {string} path API path beginning with "/".
 * @param {string} token Current session token; use an empty string for public endpoints.
 * @param {RequestInit & { timeoutMs?: number }} opts Fetch options plus an optional timeout.
 * @returns {Promise<any>} Parsed JSON response, or null for an empty response.
 * @throws {ApiError} For HTTP, network and timeout errors.
 */
export async function api(path, token, opts = {}) {
  const {
    timeoutMs = 45000,
    signal: externalSignal,
    ...fetchOptions
  } = opts;
  const isForm =
    typeof FormData !== "undefined" && fetchOptions.body instanceof FormData;
  const controller = new AbortController();

  let externalAbortHandler;
  if (externalSignal) {
    externalAbortHandler = () => controller.abort(externalSignal.reason);
    if (externalSignal.aborted) {
      externalAbortHandler();
    } else {
      externalSignal.addEventListener("abort", externalAbortHandler, { once: true });
    }
  }

  const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const endpoint = API_BASE + "/api" + path;

  try {
    const response = await fetch(endpoint, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(fetchOptions.body !== undefined && !isForm
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...(fetchOptions.headers || {}),
      },
    });

    const raw = response.status === 204 ? "" : await response.text();
    let payload = null;
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        payload = { detail: raw };
      }
    }

    if (!response.ok) {
      const message =
        payload?.detail ||
        payload?.message ||
        "Request failed with HTTP " + response.status;
      throw new ApiError(message, {
        status: response.status,
        path,
        payload,
        requestId: response.headers.get("X-Request-ID") || payload?.request_id || "",
      });
    }

    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;

    if (error?.name === "AbortError") {
      const cancelled = externalSignal?.aborted;
      throw new ApiError(
        cancelled
          ? "Request was cancelled."
          : "The server took too long to respond. Please retry.",
        { status: cancelled ? 0 : 408, path }
      );
    }

    if (error instanceof TypeError) {
      throw new ApiError(
        "Cannot connect to the TechNova server. Check the backend deployment and try again.",
        { status: 0, path }
      );
    }

    throw new ApiError(error?.message || "Unexpected network error.", {
      status: 0,
      path,
    });
  } finally {
    clearTimeout(timeout);
    if (externalSignal && externalAbortHandler) {
      externalSignal.removeEventListener("abort", externalAbortHandler);
    }
  }
}
