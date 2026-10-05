import { afterEach, describe, expect, it, vi } from "vitest";
import { RequestError, request } from "./http";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("bounded authenticated request", () => {
  it("sends same-origin cookies and session CSRF without storing credentials", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetch);
    await expect(request("/api/test", { method: "POST", body: { name: "synthetic" }, csrf: "test-csrf" })).resolves.toEqual({ ok: true });
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", method: "POST", headers: { "X-CSRF-Token": "test-csrf", "Content-Type": "application/json" } });
  });
  it("accepts a committed empty response without trying to parse JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(request("/api/test")).resolves.toBeUndefined();
  });
  it("preserves safe authorization failure status for clearing the current identity", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "UNAUTHENTICATED", message: "请重新登录。" }), { status: 401 })));
    await expect(request("/api/test")).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED", message: "请重新登录。" });
  });
  it("does not display unbounded error content or invent success from invalid JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: "x".repeat(1000) }), { status: 500 })));
    await expect(request("/api/test")).rejects.toMatchObject({ message: "请求未完成，请稍后重试。" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("invalid JSON")));
    await expect(request("/api/test")).rejects.toBeInstanceOf(RequestError);
  });
  it("reports network failure separately from an unconfirmed timeout", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(request("/api/test")).rejects.toMatchObject({ code: "SERVICE_UNAVAILABLE" });
    const controller = new AbortController(); controller.abort();
    await expect(request("/api/test", { signal: controller.signal })).rejects.toMatchObject({ code: "RESULT_UNKNOWN" });
  });
  it("aborts pending network work at the bounded deadline", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_path, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    })));
    const expectation = expect(request("/api/test")).rejects.toMatchObject({ code: "RESULT_UNKNOWN" });
    await vi.advanceTimersByTimeAsync(10000);
    await expectation;
  });
});
