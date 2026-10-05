export class RequestError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export async function request<T>(path: string, options: {
  method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown; csrf?: string; signal?: AbortSignal;
} = {}): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options.signal?.aborted) cancel();
  options.signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(cancel, 10000);
  try {
    const response = await fetch(path, {
      method: options.method ?? "GET", credentials: "same-origin", signal: controller.signal,
      headers: { ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(options.csrf ? { "X-CSRF-Token": options.csrf } : {}) },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    if (response.status === 204) return undefined as T;
    const body: unknown = await response.json();
    if (!response.ok) {
      const error = body !== null && typeof body === "object" ? body as Record<string, unknown> : {};
      throw new RequestError(response.status, typeof error.code === "string" ? error.code : "SERVICE_UNAVAILABLE",
        typeof error.message === "string" && error.message.length <= 300 ? error.message : "请求未完成，请稍后重试。");
    }
    return body as T;
  } catch (error) {
    if (error instanceof RequestError) throw error;
    if (controller.signal.aborted) throw new RequestError(0, "RESULT_UNKNOWN", "请求超时或已取消，结果尚未确认。请重新加载查看。");
    throw new RequestError(0, "SERVICE_UNAVAILABLE", "连接失败，请检查网络后重试。");
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", cancel);
  }
}
