import { validRequest, validHandshake } from "./validators.generated.js";

export const PROTOCOL = "openform.activity/1" as const;
export type BridgeMethod = "ready" | "loadProgress" | "saveProgress" | "appendEvents" | "submit" | "requestUpload" | "getOwnHistory" | "getSharedSummary";
export interface BridgeRequest {
  protocolVersion: typeof PROTOCOL;
  requestId: string;
  method: BridgeMethod;
  params: Record<string, unknown>;
}
export type BridgeHandler = (request: BridgeRequest, signal: AbortSignal) => Promise<unknown>;
export type BridgeState = "connecting" | "connected" | "unavailable";

function boundedJson(value: unknown): boolean {
  const stack: Array<[unknown, number]> = [[value, 0]];
  const seen = new Set<object>();
  let nodes = 0;
  while (stack.length) {
    const [item, depth] = stack.pop()!;
    if (++nodes > 10000 || depth > 32) return false;
    if (item === null || typeof item === "boolean") continue;
    if (typeof item === "string") { if (item.length > 65536) return false; continue; }
    if (typeof item === "number") { if (!Number.isFinite(item) || Number.isInteger(item) && !Number.isSafeInteger(item)) return false; continue; }
    if (typeof item !== "object" || seen.has(item)) return false;
    seen.add(item);
    if (!Array.isArray(item) && Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) return false;
    const values = Object.values(item);
    if (values.length > 10000) return false;
    for (const child of values) stack.push([child, depth + 1]);
  }
  try { return new TextEncoder().encode(JSON.stringify(value)).length <= 65536; }
  catch { return false; }
}

function nonce(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (value) => value.toString(16).padStart(2, "0")).join("");
}

export interface FrameBridgeOptions {
  runtimeOrigin: string;
  runtimeUrl: string;
  capabilities: readonly BridgeMethod[];
  handler: BridgeHandler;
  onState: (state: BridgeState) => void;
}

export function connectActivityFrame(frame: HTMLIFrameElement, options: FrameBridgeOptions): () => void {
  const expected = new URL(options.runtimeUrl);
  if (expected.origin !== options.runtimeOrigin || expected.origin === window.location.origin
    || !/^\/p\/[A-Za-z0-9_-]{43}$/.test(expected.pathname) || expected.search || expected.hash
    || frame.sandbox.length !== 1 || !frame.sandbox.contains("allow-scripts")) {
    throw new Error("互动页面地址或隔离设置无效。");
  }
  const allowed = new Set(options.capabilities);
  const inFlight = new Set<string>();
  let lifetime = new AbortController();
  let port: MessagePort | null = null;
  let currentNonce = "";
  let generation = 0;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let recent: number[] = [];
  let ready = false;
  let closed = false;

  function closeConnection() {
    ++generation; clearTimeout(timeout); port?.close(); port = null;
    lifetime.abort(); lifetime = new AbortController();
    inFlight.clear(); recent = []; ready = false; currentNonce = "";
  }
  function failConnection() {
    closeConnection(); options.onState("unavailable");
  }
  function answer(requestId: string, result: unknown, requestGeneration: number) {
    if (requestGeneration !== generation || lifetime.signal.aborted || !port) return;
    if (!boundedJson(result)) { failConnection(); return; }
    port.postMessage(result);
    inFlight.delete(requestId);
  }
  function errorReply(requestId: string, code: string, message: string, requestGeneration: number) {
    answer(requestId, { protocolVersion: PROTOCOL, requestId, ok: false, error: { code, message } }, requestGeneration);
  }
  async function receive(event: MessageEvent<unknown>) {
    const time = performance.now();
    recent = recent.filter((value) => time - value < 60000);
    recent.push(time);
    if (recent.length > 120 || recent.filter((value) => time - value < 1000).length > 10) { failConnection(); return; }
    if (!boundedJson(event.data) || !validRequest(event.data)) { failConnection(); return; }
    const request = event.data;
    const requestGeneration = generation;
    if (inFlight.has(request.requestId)) { failConnection(); return; }
    if (!allowed.has(request.method) || request.method !== "ready" && !ready) {
      errorReply(request.requestId, "FORBIDDEN", "页面未声明此能力或尚未完成初始化。", requestGeneration); return;
    }
    if (inFlight.size >= 8) {
      errorReply(request.requestId, "RATE_LIMITED", "页面操作过于频繁，请稍后重试。", requestGeneration); return;
    }
    if (request.method === "ready") {
      const requested = request.params.capabilities as BridgeMethod[];
      if (requested.length !== allowed.size || requested.some((value) => !allowed.has(value))) {
        errorReply(request.requestId, "INVALID_CONTRACT", "页面声明的能力与发布清单不一致。", requestGeneration); return;
      }
    }
    inFlight.add(request.requestId);
    const signal = lifetime.signal;
    try {
      const result = await options.handler(request, signal);
      if (requestGeneration !== generation || signal.aborted) return;
      if (request.method === "ready") ready = true;
      answer(request.requestId, { protocolVersion: PROTOCOL, requestId: request.requestId, ok: true, result }, requestGeneration);
    } catch (error) {
      // Only callers can approve a safe error message. Raw server content never enters the frame.
      if (error instanceof BridgeError) errorReply(request.requestId, error.code, error.message, requestGeneration);
      else errorReply(request.requestId, "RESULT_UNKNOWN", "操作结果尚未确认，请读取当前状态或保留原幂等键重试。", requestGeneration);
    }
  }
  function handshake(event: MessageEvent<unknown>) {
    // sandboxed frame origin is opaque. Source + fresh one-use nonce identify this document.
    if (closed || event.source !== frame.contentWindow || port || !currentNonce
      || event.ports.length || !boundedJson(event.data) || !validHandshake(event.data)
      || event.data.phase !== "ready" || event.data.nonce !== currentNonce) return;
    const channel = new MessageChannel();
    port = channel.port1;
    port.onmessage = (message) => { void receive(message); };
    port.onmessageerror = failConnection;
    port.start();
    frame.contentWindow?.postMessage({ protocolVersion: PROTOCOL, phase: "connect", nonce: currentNonce }, "*", [channel.port2]);
    currentNonce = ""; clearTimeout(timeout);
    options.onState("connected");
  }
  function load() {
    if (closed) return;
    closeConnection(); currentNonce = nonce(); options.onState("connecting");
    timeout = setTimeout(failConnection, 8000);
    frame.contentWindow?.postMessage({ protocolVersion: PROTOCOL, phase: "init", nonce: currentNonce }, "*");
  }
  window.addEventListener("message", handshake);
  frame.addEventListener("load", load);
  // Attach listeners before initiating navigation, including a cached document's load event.
  frame.src = options.runtimeUrl;
  options.onState("connecting");
  timeout = setTimeout(failConnection, 8000);
  return () => {
    closed = true;
    window.removeEventListener("message", handshake); frame.removeEventListener("load", load);
    closeConnection();
  };
}

export class BridgeError extends Error {
  constructor(public readonly code: string, message: string) { super(message); }
}
