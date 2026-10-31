/**
 * Shared HTTP client for the TechNova portal.
 * Adds the API base URL, JSON/FormData headers and bearer token, then normalizes API errors.
 */
export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  "https://technova-5h0g.onrender.com"
).replace(/\/$/, "");

/**
 * Send a request to the TechNova API.
 *
 * @param {string} path API path beginning with "/".
 * @param {string} token Current session token; omit it for public endpoints.
 * @param {RequestInit} opts Fetch options such as method, body and extra headers.
 * @returns {Promise<any>} Parsed JSON response.
 * @throws {Error} When the API returns a non-success HTTP status.
 */
export async function api(path, token, opts = {}) {
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  const response = await fetch(\`\${API_BASE}/api\${path}\`, {
    ...opts,
    headers: {
      ...(!isForm ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...(opts.headers || {}),
    },
  });

  let data = {};
  try {
    data = await response.json();
  } catch {
    // Some successful endpoints (for example downloads) may not return JSON.
  }

  if (!response.ok) {
    throw new Error(
      data.detail || data.message || \`Request failed: \${response.status}\`
    );
  }
  return data;
}
