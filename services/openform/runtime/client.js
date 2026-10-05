(() => {
  "use strict";
  const protocolVersion = "openform.activity/1";
  const methods = ["ready", "loadProgress", "saveProgress", "appendEvents", "submit", "requestUpload", "getOwnHistory", "getSharedSummary"];
  const pending = new Map();
  let nonce = null;
  let port = null;
  let connection = null;
  let finishConnection = null;

  function failure(code, message) { return Object.assign(new Error(message), { code }); }
  function reset() {
    port?.close(); port = null;
    for (const item of pending.values()) {
      clearTimeout(item.timer);
      item.reject(failure("RESULT_UNKNOWN", "页面连接已关闭，操作结果尚未确认。请重新连接并读取当前状态。"));
    }
    pending.clear();
    finishConnection?.reject(failure("RESULT_UNKNOWN", "页面连接已关闭。"));
    connection = null; finishConnection = null;
  }
  function connected() {
    if (port) return Promise.resolve();
    if (!connection) {
      connection = new Promise((resolve, reject) => { finishConnection = { resolve, reject }; });
      // A page can register its callbacks after the timeout; avoid an unhandled rejection in the meantime.
      connection.catch(() => {});
    }
    return connection;
  }
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (event.source !== window.parent || !message || typeof message !== "object"
      || Object.keys(message).sort().join(",") !== "nonce,phase,protocolVersion"
      || message.protocolVersion !== protocolVersion || !/^[a-f0-9]{64}$/.test(message.nonce)) return;
    if (message.phase === "init" && event.ports.length === 0) {
      if (nonce !== null) reset();
      nonce = message.nonce;
      window.parent.postMessage({ protocolVersion, phase: "ready", nonce }, event.origin);
    } else if (message.phase === "connect" && message.nonce === nonce && event.ports.length === 1 && !port) {
      port = event.ports[0];
      port.onmessage = (reply) => {
        const value = reply.data;
        if (!value || value.protocolVersion !== protocolVersion || typeof value.requestId !== "string") return;
        const item = pending.get(value.requestId);
        if (!item) return;
        pending.delete(value.requestId); clearTimeout(item.timer);
        if (value.ok === true && Object.hasOwn(value, "result")) item.resolve(value.result);
        else item.reject(failure(value.error?.code || "SERVICE_UNAVAILABLE", value.error?.message || "操作未完成，请重试。"));
      };
      port.onmessageerror = reset;
      port.start();
      finishConnection?.resolve(); finishConnection = null;
    }
  });

  async function request(method, params = {}) {
    let timer;
    try {
      await Promise.race([connected(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(failure("BRIDGE_UNAVAILABLE", "页面通信尚未建立，请重新打开活动。")), 10000);
      })]);
    } finally { clearTimeout(timer); }
    if (!port || pending.size >= 8) throw failure("BRIDGE_UNAVAILABLE", "页面连接繁忙或已失效，请稍后重试。");
    const requestId = crypto.randomUUID();
    const value = { protocolVersion, requestId, method, params };
    let bytes;
    try { bytes = new TextEncoder().encode(JSON.stringify(value)).length; }
    catch { throw failure("INVALID_CONTRACT", "操作内容无法序列化。"); }
    if (bytes > 65536) throw failure("PAYLOAD_TOO_LARGE", "操作内容超过 64 KiB 上限。");
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        pending.delete(requestId);
        reject(failure("RESULT_UNKNOWN", "尚未收到操作回执，结果未确认。请保留原幂等键重试，或读取当前状态。"));
      }, 10000);
      pending.set(requestId, { resolve, reject, timer: timeout });
      try { port.postMessage(value); }
      catch {
        clearTimeout(timeout); pending.delete(requestId);
        reject(failure("RESULT_UNKNOWN", "页面连接已失效，操作结果未确认。"));
      }
    });
  }
  const api = Object.fromEntries(methods.map((method) => [method, (params) => request(method, params)]));
  api.newIdempotencyKey = () => crypto.randomUUID();
  Object.defineProperty(window, "OpenForm", { value: Object.freeze(api), writable: false, configurable: false });
  window.addEventListener("pagehide", reset);
})();
