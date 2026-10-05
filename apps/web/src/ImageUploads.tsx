import { useEffect, useState, type ChangeEvent } from "react";
import { RequestError } from "./http";
import type { BridgeHandler, BridgeRequest } from "../runtime/bridge";

export interface ImageReservation { fileId: string; field: string; status: string }
interface ImageField { path: string; title: string }

function atPath(data: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => value && typeof value === "object" && Object.hasOwn(value, key) ? (value as Record<string, unknown>)[key] : undefined, data);
}
function withImage(data: Record<string, unknown>, path: string, fileId: string): Record<string, unknown> {
  const result = structuredClone(data); let current = result;
  const segments = path.split(".");
  for (const key of segments.slice(0, -1)) {
    if (!Object.hasOwn(current, key)) Object.defineProperty(current, key, { value: {}, enumerable: true, writable: true, configurable: true });
    const value = current[key];
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("图片字段结构不正确，请联系教师。");
    current = value as Record<string, unknown>;
  }
  const ids = atPath(result, path);
  if (ids !== undefined && (!Array.isArray(ids) || ids.some((id) => typeof id !== "string"))) throw new Error("图片字段结构不正确。");
  const files = Array.isArray(ids) ? ids as string[] : [];
  Object.defineProperty(current, segments.at(-1)!, { value: files.includes(fileId) ? files : [...files, fileId], enumerable: true, writable: true, configurable: true });
  return result;
}
function bridge(method: BridgeRequest["method"], params: Record<string, unknown> = {}): BridgeRequest {
  return { protocolVersion: "openform.activity/1", requestId: crypto.randomUUID(), method, params };
}

export function ImageUploads({ fields, reservation, endpoint, csrf, handler, progress, signal, blocked, submitted, onComplete, onCancel }: {
  fields: ImageField[]; reservation: ImageReservation | null; endpoint: string; csrf: string; handler: BridgeHandler;
  progress: unknown; signal: AbortSignal | undefined; blocked: boolean; submitted: boolean; onComplete: () => void; onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [unattached, setUnattached] = useState<ImageReservation | null>(null);
  useEffect(() => {
    if (unattached) { const files = atPath(progress, unattached.field); if (Array.isArray(files) && files.includes(unattached.fileId)) setUnattached(null); }
  }, [progress, unattached]);
  async function attach(item: ImageReservation) {
    if (!signal || signal.aborted) return;
    const current = await handler(bridge("loadProgress"), signal) as { data: Record<string, unknown>; revision: number };
    await handler(bridge("saveProgress", { data: withImage(current.data, item.field, item.fileId), expectedRevision: current.revision, idempotencyKey: crypto.randomUUID() }), signal);
    if (!signal.aborted) { setUnattached(null); setNotice("图片已校验、持久化并保存到本次作答，尚未最终提交。"); onComplete(); }
  }
  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const image = event.target.files?.[0]; event.target.value = "";
    if (!image || !reservation || !signal || signal.aborted) return;
    if (!["image/png", "image/jpeg"].includes(image.type) || image.size > 10 * 1024 * 1024) { setNotice("请选择不超过 10 MiB 的 PNG/JPEG 图片。"); return; }
    setBusy(true); setNotice("正在上传和校验图片…");
    const controller = new AbortController(); const cancel = () => controller.abort();
    signal.addEventListener("abort", cancel, { once: true }); const timer = setTimeout(cancel, 60000);
    try {
      const response = await fetch(`${endpoint}/uploads/${reservation.fileId}`, { method: "PUT", body: image, credentials: "same-origin", signal: controller.signal,
        headers: { "Content-Type": image.type, "X-CSRF-Token": csrf } });
      const result = await response.json() as { fileId?: string; status?: string; code?: string; message?: string };
      if (!response.ok) throw new RequestError(response.status, result.code ?? "UPLOAD_FAILED", result.message ?? "图片未接收，请重试。");
      if (result.status !== "ready" || result.fileId !== reservation.fileId) throw new Error("图片上传结果未确认，请保留本次入口后重试。");
      if (signal.aborted) return;
      setUnattached(reservation); await attach(reservation);
    } catch (error) {
      if (!signal.aborted) setNotice(error instanceof Error && error.name !== "AbortError" ? error.message : "上传结果未确认，可选择同一张图片，用原入口重试。");
    } finally { clearTimeout(timer); signal.removeEventListener("abort", cancel); if (!signal.aborted) setBusy(false); }
  }
  return <section className="panel image-upload-panel"><h2>本次作答的图片</h2>
    <p>{submitted ? "本次作答已提交，图片随最终提交保留。" : "在活动中点击“添加实验照片”，先保存作答，再在这里选择图片。最多 5 张，每张 PNG/JPEG 不超过 10 MiB、最长边 4096。"}</p>
    {fields.map((field) => { const ids = atPath(progress, field.path); return <div key={field.path}><h3>{field.title}</h3>
      {Array.isArray(ids) && ids.map((id) => typeof id === "string" && /^[a-f0-9-]{36}$/i.test(id) ? <a key={id} href={`${endpoint}/files/${id}`} target="_blank" rel="noreferrer"><img className="evidence-image" src={`${endpoint}/files/${id}`} alt={`${field.title}，已保存图片`} /></a> : null)}
      {reservation?.field === field.path && <label>选择图片<input type="file" accept="image/png,image/jpeg" disabled={busy || blocked || submitted} onChange={(event) => void choose(event)} /></label>}</div>; })}
    {unattached && <button disabled={busy || blocked || submitted} onClick={() => { setBusy(true); void attach(unattached).catch((error: unknown) => setNotice(error instanceof Error ? error.message : "图片尚未附加，请重试。")).finally(() => setBusy(false)); }}>图片已上传，重试保存到本次作答</button>}
    {reservation && <button disabled={busy || blocked} onClick={() => { setUnattached(null); setNotice("已取消添加，当前作答继续保留。"); onCancel(); }}>取消添加 / 继续填写</button>}
    {notice && <p role="status">{submitted ? "图片已随本次作答提交，可通过上方缩略图查看。" : notice}</p>}
  </section>;
}
