// Thin wrapper around fetch() for the Flask JSON API. Session-cookie auth,
// same-origin in production (served from /app/ by Flask itself) and proxied
// in dev (see vite.config.js), so no tokens or CORS handling needed here.

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = "GET", json, formData } = {}) {
  const opts = { method, credentials: "include", headers: {} };
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (formData !== undefined) {
    opts.body = formData; // browser sets multipart boundary itself
  }
  const res = await fetch(path, opts);
  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON response (e.g. the "frontend not built" 404 plain-text page)
  }
  if (!res.ok || (data && data.ok === false)) {
    const message = (data && data.error) || `Request failed (${res.status})`;
    throw new ApiError(message, res.status, data && data.detail);
  }
  return data;
}

export const api = {
  me: () => request("/api/me"),
  login: (username, password) => request("/api/login", { method: "POST", json: { username, password } }),
  logout: () => request("/api/logout", { method: "POST" }),
  reports: () => request("/api/reports"),
  reportDetail: (rid) => request(`/api/reports/${encodeURIComponent(rid)}`),
  scanWebsite: (payload) => request("/api/scan/website", { method: "POST", json: payload }),
  scanPdf: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/scan/pdf", { method: "POST", formData: fd });
  },
  research: (payload) => request("/api/research", { method: "POST", json: payload }),
  ask: ({ q, source, scope, summarize }) => {
    const params = new URLSearchParams({ q });
    if (source) params.set("source", source);
    if (scope) params.set("scope", scope);
    if (summarize) params.set("summarize", "1");
    return request(`/api/ask?${params.toString()}`);
  },
};

export { ApiError };
