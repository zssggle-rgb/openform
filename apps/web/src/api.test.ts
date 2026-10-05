import { afterEach, describe, expect, it, vi } from "vitest";
import { checkReady } from "./api";

afterEach(() => vi.unstubAllGlobals());
describe("service readiness", () => {
  it("requires a real successful API response with its expected shape", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ready", service: "openform-api" })));
    vi.stubGlobal("fetch", fetcher);
    expect(await checkReady()).toBe("ready");
    expect(fetcher).toHaveBeenCalledWith("/api/health/ready", { signal: undefined, credentials: "same-origin" });
  });
  it.each([null, {}, { status: "ready", service: "another-service" }, { status: "alive" }])("does not show readiness from an invalid response %j", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
    expect(await checkReady()).toBe("unavailable");
  });
  it("handles a database-unavailable response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
    expect(await checkReady()).toBe("unavailable");
  });
  it("handles network loss and invalid JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network unavailable")));
    expect(await checkReady()).toBe("unavailable");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not-json")));
    expect(await checkReady()).toBe("unavailable");
  });
});
