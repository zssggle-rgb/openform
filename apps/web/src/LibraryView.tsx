import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { request, RequestError } from "./http";
import type { Session, Workspace } from "./identity";
import type { Page } from "./roster";
import { ActivityFrame } from "./ActivityFrame";
import { BridgeError, type BridgeHandler, type BridgeMethod } from "../runtime/bridge";

interface Resource { id: string; title: string; objective: string; number: number; subject: string; grade: string; publisher: string; active: boolean }
interface Detail { id: string; active: boolean; revision: number; can_withdraw: boolean; versions: { number: number; subject: string; grade: string; manifest: { title: string; objective: string; questions: { id: string; title: string; kind: string }[] } }[] }
interface CopyOperation { id: string; number: number; request_key: string }
interface Preview { runtime_origin: string; runtime_url: string; title: string; capabilities: BridgeMethod[] }

function pendingCopy(key: string): CopyOperation | null {
  const stored = sessionStorage.getItem(key); if (!stored) return null;
  const value: unknown = JSON.parse(stored);
  if (!value || typeof value !== "object" || !("id" in value) || !("request_key" in value) || !("number" in value)
    || typeof value.id !== "string" || typeof value.request_key !== "string" || !Number.isSafeInteger(value.number)) throw new Error("复制恢复信息无法读取，请联系管理员处理。");
  return value as CopyOperation;
}

export function LibraryView({ session, workspace, resourceId, onError }: { session: Session; workspace: Workspace; resourceId?: string | null; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`, storageKey = `openform.copy.${workspace.id}.${session.account_id}`;
  const [resources, setResources] = useState<Resource[]>([]), [cursor, setCursor] = useState<string | null>(null), [detail, setDetail] = useState<Detail | null>(null);
  const [query, setQuery] = useState({ q: "", subject: "", grade: "" }), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  const selectedResource = useRef(resourceId); selectedResource.current = resourceId;
  const [pending, setPending] = useState<CopyOperation | null>(null), [preview, setPreview] = useState<Preview | null>(null);
  const previewHandler = useCallback<BridgeHandler>(async (message) => {
    if (message.method === "ready") return { mode: "preview" };
    if (message.method === "loadProgress") return { data: {}, revision: 0, receipt: null };
    throw new BridgeError("PREVIEW_ONLY", "资源预览不保存数据，请先复制到我的活动，再真实试做。");
  }, []);
  async function load(parameters: typeof query, signal: AbortSignal) {
    const value = await request<Page<Resource>>(`${base}/library?${new URLSearchParams(parameters)}`, { signal });
    if (!signal.aborted) { setResources(value.items); setCursor(value.next_cursor); }
  }
  useEffect(() => {
    const current = new AbortController(); lifetime.current = current;
    try { setPending(pendingCopy(storageKey)); } catch (error) { onError(error); }
    void load(query, current.signal).catch((error) => { if (!current.signal.aborted) onError(error); }).finally(() => { if (!current.signal.aborted) setLoading(false); });
    return () => current.abort();
  }, [base]);
  useEffect(() => { setDetail(null); setPreview(null); if (!resourceId) return; const controller = new AbortController(); void request<Detail>(`${base}/library/${resourceId}`, { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setDetail(value); }).catch((error) => { if (!controller.signal.aborted) onError(error); }); return () => controller.abort(); }, [base, resourceId]);
  async function act(run: (signal: AbortSignal) => Promise<void>) {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget), parameters = { q: String(values.get("q") ?? ""), subject: String(values.get("subject") ?? ""), grade: String(values.get("grade") ?? "") };
    setQuery(parameters); await act((signal) => load(parameters, signal));
  }
  async function copy(number: number) {
    if (!detail) return;
    const previous = pendingCopy(storageKey);
    if (previous && (previous.id !== detail.id || previous.number !== number)) { onError(new Error("上一次复制结果尚未确认，请先恢复原复制操作。")); return; }
    await performCopy(previous ?? { id: detail.id, number, request_key: crypto.randomUUID() });
  }
  async function performCopy(operation: CopyOperation) {
    await act(async (signal) => {
      sessionStorage.setItem(storageKey, JSON.stringify(operation)); setPending(operation);
      try {
        const result = await request<{ id: string }>(`${base}/library/${operation.id}/copies`, { method: "POST", csrf: session.csrf_token, signal, body: { number: operation.number, request_key: operation.request_key } });
        sessionStorage.removeItem(storageKey);
        if (!signal.aborted) { setPending(null); location.hash = `#T03?activity=${result.id}`; }
      } catch (error) {
        if (error instanceof RequestError && error.status >= 400 && error.status < 500) { sessionStorage.removeItem(storageKey); if (!signal.aborted) setPending(null); }
        throw error;
      }
    });
  }
  return <>
    <div className="page-heading"><div><h1>校内资源库</h1><p>{workspace.name} · 已验证版本，复制后独立制作</p></div></div>
    <section className="panel"><form className="roster-tools" onSubmit={(event) => void search(event)}><label>名称<input name="q" maxLength={80} disabled={busy} /></label>
      <label>学科<input name="subject" maxLength={40} disabled={busy} /></label><label>年级<input name="grade" maxLength={40} disabled={busy} /></label><button className="primary" disabled={busy}>查找资源</button></form>
      <p>复制页面、题目、答案标准和数据约定；不会复制名单、进入码或学生记录。你的副本需要试做后再发布。</p></section>
    {notice && <p className="success-box" role="status">{notice}</p>}
    {pending && workspace.is_teacher && <section className="panel section"><p>上一次复制结果尚未确认。恢复时沿用同一操作键，不会重复创建副本。</p><button disabled={busy} onClick={() => void performCopy(pending)}>恢复上次复制</button></section>}
    <section className="panel section table-scroll">{loading ? <p role="status">正在读取资源…</p> : <table><thead><tr><th>资源</th><th>适用范围</th><th>发布者</th><th>版本</th><th>操作</th></tr></thead><tbody>
      {resources.map((resource) => <tr key={resource.id}><td>{resource.title}<p className="field-help">{resource.objective}</p>{!resource.active && <span>已撤回</span>}</td><td>{resource.subject || "未填写学科"} · {resource.grade || "未填写年级"}</td><td>{resource.publisher}</td><td>v{resource.number}</td><td><a href={`#T11?resource=${resource.id}`}>查看资源</a></td></tr>)}
      {!resources.length && <tr><td colSpan={5}>暂无匹配资源。有发布权的教师可从活动详情发布固定版本。</td></tr>}</tbody></table>}
      {cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const params = new URLSearchParams({ ...query, cursor }); const page = await request<Page<Resource>>(`${base}/library?${params}`, { signal }); if (!signal.aborted) { setResources((current) => [...current, ...page.items]); setCursor(page.next_cursor); } })}>加载更多资源</button>}</section>
    {detail && <section className="panel section"><div className="roster-tools"><h2>资源详情 · {detail.active ? "可复制" : "已撤回"}</h2><a href={workspace.is_teacher ? "#T10" : "#C04"}>返回资源列表</a></div>
      {detail.versions.map((version) => <details key={version.number} open={version.number === detail.versions[0].number}><summary>{version.manifest.title} · v{version.number}</summary><p>{version.manifest.objective}</p>
        <p>{version.subject || "未填写学科"} · {version.grade || "未填写年级"}</p><h3>收集内容</h3><ul>{version.manifest.questions.map((question) => <li key={question.id}>{question.title}</li>)}</ul>
        <div className="row-actions"><button disabled={busy || !detail.active} onClick={() => void act(async (signal) => { const value = await request<Preview>(`${base}/library/${detail.id}/preview`, { method: "POST", csrf: session.csrf_token, signal, body: { number: version.number, request_key: crypto.randomUUID() } }); if (!signal.aborted && selectedResource.current === detail.id) setPreview(value); })}>预览 v{version.number}</button>
        {workspace.is_teacher && <button className="primary" disabled={busy || !detail.active} onClick={() => void copy(version.number).catch(onError)}>复制 v{version.number} 到我的活动</button>}</div></details>)}
      {detail.can_withdraw && detail.active && <button disabled={busy} onClick={() => void act(async (signal) => { await request(`${base}/library/${detail.id}/withdraw`, { method: "POST", csrf: session.csrf_token, signal, body: { expected_revision: detail.revision } }); if (!signal.aborted) { await load(query, signal); if (selectedResource.current === detail.id) { setDetail((current) => current?.id === detail.id ? { ...current, active: false } : current); setNotice("资源已撤回，已有副本和课堂保留。"); } } })}>撤回校内发布</button>}
    </section>}
    {preview && <section className="panel section"><h2>资源预览 · {preview.title}</h2><p>仅查看页面，不保存试做记录；复制后才能真实试做和发布。</p><button onClick={() => setPreview(null)}>关闭预览</button><ActivityFrame title={preview.title} runtimeOrigin={preview.runtime_origin} runtimeUrl={preview.runtime_url} capabilities={preview.capabilities} handler={previewHandler} /></section>}
  </>;
}
