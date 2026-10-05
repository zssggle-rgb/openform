import { useCallback, useEffect, useRef, useState } from "react";
import { BridgeError, type BridgeMethod, type BridgeRequest } from "../runtime/bridge";
import { validReceipt, type Receipt } from "../runtime/validators.generated.js";
import { ActivityFrame } from "./ActivityFrame";
import { RequestError, request } from "./http";
import { ImageUploads, type ImageReservation } from "./ImageUploads";

export interface Attempt {
  workspace_id: string; attempt_id: string; title: string; capabilities: BridgeMethod[];
  runtime_origin: string; runtime_url: string; trial_id?: string; classroom_id?: string;
  state?: string; classroom_state?: string; number?: number; revision?: number;
  image_fields?: { path: string; title: string }[];
}
const QUEUE_PREFIX = "openform.pending.";

export function clearPendingWrites() {
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index--) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(QUEUE_PREFIX)) sessionStorage.removeItem(key);
    }
  } catch { /* The browser may already have discarded this session's storage. */ }
}

function readQueue(key: string): BridgeRequest[] {
  try {
    const data: unknown = JSON.parse(sessionStorage.getItem(key) ?? "[]");
    if (Array.isArray(data) && data.length <= 4 && data.every((item) => item && typeof item === "object"
      && ["saveProgress", "submit"].includes(item.method) && typeof item.params?.idempotencyKey === "string")) return data as BridgeRequest[];
  } catch { /* An unreadable queue must never be sent as a new operation. */ }
  return [];
}

export function RuntimePlayer({ attempt, endpoint, csrf, actorKey, onReceipt, onExpired }: {
  attempt: Attempt; endpoint: string; csrf: string; actorKey: string;
  onReceipt?: (receipt: Receipt) => void; onExpired: (error: unknown) => void;
}) {
  const queueKey = `${QUEUE_PREFIX}${attempt.workspace_id}.${actorKey}.${attempt.attempt_id}`;
  const [pending, setPending] = useState(() => readQueue(queueKey));
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [notice, setNotice] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [imageReservation, setImageReservation] = useState<ImageReservation | null>(null);
  const [progress, setProgress] = useState<unknown>(null);
  const lifetime = useRef<AbortController | null>(null);
  const callbacks = useRef({ onReceipt, onExpired }); callbacks.current = { onReceipt, onExpired };
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    return () => controller.abort();
  }, [endpoint]);

  function persist(items: BridgeRequest[]) {
    if (items.length) sessionStorage.setItem(queueKey, JSON.stringify(items)); else sessionStorage.removeItem(queueKey);
    setPending(items);
  }
  const rememberReceipt = useCallback((result: unknown, method?: string): Receipt => {
    if (!validReceipt(result) || result.attemptId !== attempt.attempt_id
      || method === "submit" && result.state !== "submitted" || method === "saveProgress" && result.state !== "saved") {
      throw new BridgeError("RESULT_UNKNOWN", "收到的回执无法核验，请保留原操作并重新确认。");
    }
    setReceipt(result); callbacks.current.onReceipt?.(result); return result;
  }, [attempt.attempt_id]);

  const handler = useCallback(async (message: BridgeRequest, signal: AbortSignal) => {
    const writing = message.method === "saveProgress" || message.method === "submit";
    const operationKey = message.params.idempotencyKey;
    if (writing) {
      try {
        const queue = readQueue(queueKey);
        const original = queue.find((item) => item.method === message.method && item.params.idempotencyKey === operationKey);
        if (original && JSON.stringify(original.params) !== JSON.stringify(message.params)) throw new BridgeError("IDEMPOTENCY_CONFLICT", "原操作内容不能改变。");
        if (!original) {
          if (queue.length >= 4) throw new BridgeError("RESULT_UNKNOWN", "请先恢复尚未确认的操作，再继续保存或提交。");
          persist([...queue, message]);
        }
      } catch (error) {
        if (error instanceof BridgeError) throw error;
        throw new BridgeError("LOCAL_STORAGE_UNAVAILABLE", "无法保留原操作，请允许浏览器会话存储后重试。本次尚未发送。");
      }
    }
    try {
      const result = await request<unknown>(`${endpoint}/bridge`, { method: "POST", body: message, csrf, signal });
      if (message.method === "requestUpload" && result && typeof result === "object" && "fileId" in result && "field" in result
        && typeof result.fileId === "string" && typeof result.field === "string") setImageReservation(result as ImageReservation);
      if (message.method === "loadProgress" && result && typeof result === "object" && "data" in result) setProgress(result.data);
      if (writing) {
        rememberReceipt(result, message.method);
        setProgress(message.params.data);
        persist(readQueue(queueKey).filter((item) => item.method !== message.method || item.params.idempotencyKey !== operationKey));
      } else if (message.method === "loadProgress" && result && typeof result === "object" && "receipt" in result && result.receipt) {
        rememberReceipt(result.receipt);
      }
      return result;
    } catch (error) {
      if (error instanceof RequestError) {
        if (writing && error.status >= 400 && error.status < 500) {
          try { persist(readQueue(queueKey).filter((item) => item.method !== message.method || item.params.idempotencyKey !== operationKey)); } catch { /* Original operation remains recoverable. */ }
        }
        if (error.status === 401) { clearPendingWrites(); callbacks.current.onExpired(error); }
        throw new BridgeError(error.code, error.message);
      }
      throw error;
    }
  }, [endpoint, csrf, queueKey, rememberReceipt]);

  async function recover() {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return;
    setRecovering(true); setNotice("");
    try {
      for (const item of readQueue(queueKey)) {
        const query = new URLSearchParams({ method: item.method, key: String(item.params.idempotencyKey) });
        let result: unknown;
        try {
          try { result = await request(`${endpoint}/operations?${query}`, { signal }); }
          catch (error) {
            if (!(error instanceof RequestError && error.status === 404 && error.code === "OPERATION_NOT_FOUND")) throw error;
            result = await request(`${endpoint}/bridge`, { method: "POST", body: item, csrf, signal });
          }
        } catch (error) {
          if (error instanceof RequestError && error.status >= 400 && error.status < 500) {
            persist(readQueue(queueKey).filter((other) => other.method !== item.method || other.params.idempotencyKey !== item.params.idempotencyKey));
            if (!signal.aborted) setGeneration((value) => value + 1);
          }
          throw error;
        }
        rememberReceipt(result, item.method);
        persist(readQueue(queueKey).filter((other) => other.method !== item.method || other.params.idempotencyKey !== item.params.idempotencyKey));
      }
      if (!signal.aborted) { setNotice("原操作回执已确认。活动已重新读取服务端状态。"); setGeneration((value) => value + 1); }
    } catch (error) {
      if (!signal.aborted) {
        setNotice(error instanceof Error ? error.message : "恢复未完成，原操作仍保留。");
        if (error instanceof RequestError && error.status === 401) { clearPendingWrites(); callbacks.current.onExpired(error); }
      }
    } finally { if (!signal.aborted) setRecovering(false); }
  }
  return <section>
    {pending.length > 0 && <div className="pending-box" role="status"><p>有 {pending.length} 项操作尚未收到确认回执。当前不能认定为已提交。</p>
      <button disabled={recovering} onClick={() => void recover()}>{recovering ? "正在确认原操作…" : "找回原回执 / 用原内容重试"}</button></div>}
    {receipt && <p className="success-box" role="status">{receipt.state === "submitted" ? "已提交" : "已保存"} · 服务端版本 {receipt.revision} · 回执 {receipt.receiptId}</p>}
    {notice && <p role="status">{notice}</p>}
    {(attempt.image_fields?.length ?? 0) > 0 && <ImageUploads fields={attempt.image_fields!} reservation={imageReservation} endpoint={endpoint} csrf={csrf}
      handler={handler} progress={progress} signal={lifetime.current?.signal} blocked={pending.length > 0}
      onCancel={() => setImageReservation(null)} onComplete={() => { setImageReservation(null); setGeneration((value) => value + 1); }} />}
    {imageReservation && <p role="status">正在添加图片。当前作答已保存；请在上方完成或取消添加，再继续填写。</p>}
    <ActivityFrame key={`${attempt.attempt_id}:${generation}`} title={attempt.title} runtimeOrigin={attempt.runtime_origin}
      runtimeUrl={attempt.runtime_url} capabilities={attempt.capabilities} handler={handler} interactionDisabled={imageReservation !== null} />
  </section>;
}
