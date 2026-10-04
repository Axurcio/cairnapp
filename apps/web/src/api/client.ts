import type {
  ConsentScope,
  Evidence,
  Journey,
  JourneySummary,
  MessageResponse,
  Observation,
  Report,
  Session,
  TimelineEntry,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// The session cookie is HttpOnly, so scripts never see it. The CSRF token is the one
// secret the page holds: every write must echo it, which a cross-site page cannot do.
let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Called when the API reports the session is gone (expired, revoked, signed out elsewhere). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** Turns FastAPI error bodies ({detail: string | validation errors[]}) into one message. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => (d as { msg?: unknown }).msg)
      .filter((m): m is string => typeof m === "string");
    if (parts.length) return parts.join("; ");
  }
  return `Request failed (${status})`;
}

export async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const response = await fetch(path, {
    method,
    headers,
    body: payload,
    credentials: "same-origin",
  });
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && path !== "/v1/auth/login") onUnauthorized?.();
    throw new ApiError(response.status, errorMessage(response.status, data));
  }
  return data as T;
}

const journey = (id: string) => `/v1/journeys/${encodeURIComponent(id)}`;

export const api = {
  login: (email: string, password: string) =>
    request<Session>("POST", "/v1/auth/login", { email, password }),
  session: () => request<Session>("GET", "/v1/auth/session"),
  logout: () => request<void>("POST", "/v1/auth/logout"),

  journeys: () => request<JourneySummary[]>("GET", "/v1/journeys"),
  journey: (id: string) => request<Journey>("GET", journey(id)),
  timeline: (id: string) => request<TimelineEntry[]>("GET", `${journey(id)}/timeline`),
  observations: (id: string) => request<Observation[]>("GET", `${journey(id)}/observations`),
  report: (id: string) => request<Report>("GET", `${journey(id)}/report`),
  consents: (id: string) => request<{ granted: ConsentScope[] }>("GET", `${journey(id)}/consents`),
  sendMessage: (id: string, text: string) =>
    request<MessageResponse>("POST", `${journey(id)}/messages`, { text }),
  uploadEvidence: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Evidence>("POST", `${journey(id)}/evidence`, form);
  },
  revokeConsent: (id: string, scopes: ConsentScope[]) =>
    request<{ status: string }>("POST", `${journey(id)}/consent/revoke`, { scopes }),
};
