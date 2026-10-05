export type Readiness = "ready" | "unavailable";

export async function checkReady(signal?: AbortSignal): Promise<Readiness> {
  try {
    const response = await fetch("/api/health/ready", { signal, credentials: "same-origin" });
    if (!response.ok) return "unavailable";
    const body: unknown = await response.json();
    return body !== null && typeof body === "object" && "status" in body && body.status === "ready"
      && "service" in body && body.service === "openform-api" ? "ready" : "unavailable";
  } catch {
    return "unavailable";
  }
}
