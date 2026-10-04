import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, errorMessage, setCsrfToken, setUnauthorizedHandler } from "./client";

function respond(status: number, body: unknown) {
  return vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(body === undefined ? null : JSON.stringify(body), { status }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setUnauthorizedHandler(null);
});

describe("request", () => {
  it("sends the CSRF token on writes but not on reads", async () => {
    const fetchMock = respond(200, {});
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("csrf-123");

    await api.journeys();
    await api.sendMessage("j1", "hello");

    const [, read] = fetchMock.mock.calls[0]!;
    const [url, write] = fetchMock.mock.calls[1]!;
    expect((read!.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(url).toBe("/v1/journeys/j1/messages");
    expect((write!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-123");
    expect(write!.credentials).toBe("same-origin");
    expect(write!.body).toBe(JSON.stringify({ text: "hello" }));
  });

  it("encodes path parameters", async () => {
    const fetchMock = respond(200, {});
    vi.stubGlobal("fetch", fetchMock);
    await api.journey("../auth/logout");
    expect(fetchMock.mock.calls[0]![0]).toBe("/v1/journeys/..%2Fauth%2Flogout");
  });

  it("reports an ended session, except for a failed login", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    vi.stubGlobal("fetch", respond(401, { detail: "session expired or signed out" }));

    await expect(api.journeys()).rejects.toThrow(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);

    await expect(api.login("a@example.org", "wrong")).rejects.toThrow(
      "session expired or signed out",
    );
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe("errorMessage", () => {
  it("reads string and validation-error details", () => {
    expect(errorMessage(403, { detail: "forbidden: own data" })).toBe("forbidden: own data");
    expect(errorMessage(422, { detail: [{ msg: "too long" }, { msg: "missing" }] })).toBe(
      "too long; missing",
    );
    expect(errorMessage(500, null)).toBe("Request failed (500)");
  });
});
