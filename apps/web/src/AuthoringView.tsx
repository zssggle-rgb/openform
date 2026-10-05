import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { request } from "./http";
import type { Session, Workspace } from "./identity";
import type { Page } from "./roster";

interface Manifest { title: string; objective: string; entry: string; questions: { id: string; title: string; kind: string; dataPath: string }[]; [key: string]: unknown }
interface Draft { manifest: Manifest; assets: Record<string, string>; grading: unknown[]; expected_revision: number }
interface Job { id: string; status: string; result: { id: string; draft_revision: number } | null; error_message: string | null; created_at: string; usage?: { total_tokens?: number }; prompt?: string; raw_output?: string | null }
interface ImportResult { id: string; status: string; result: { id: string } | null; error_message: string | null; draft?: Draft }
interface Generation { prompt: string; activity_id: string | null; expected_revision: number; request_key: string }
const labels: Record<string, string> = { queued: "排队中", running: "正在生成", succeeded: "草稿已保存 · 待试做", failed: "未生成可用草稿", outcome_unknown: "结果与费用待确认", cancelled: "已取消" };
const kinds: Record<string, string> = { choice: "选择", number: "数值", text: "文字", image: "图片", observations: "测量记录" };

function encode(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
  return btoa(binary);
}
function decode(value: string): string {
  return new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(atob(value), (char) => char.charCodeAt(0)));
}
async function hash(encoded: string): Promise<string> {
  const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map((value) => value.toString(16).padStart(2, "0")).join("");
}

export function AuthoringView({ session, workspace, activity, onSaved, onError }: {
  session: Session; workspace: Workspace; activity: { id: string; draft_revision: number; title: string } | null;
  onSaved: (id: string) => Promise<void>; onError: (error: unknown) => void;
}) {
  const base = `/api/workspaces/${workspace.id}`, storageKey = `openform.authoring.${workspace.id}.${session.account_id}`;
  const [prompt, setPrompt] = useState(""), [source, setSource] = useState<Draft | null>(null);
  const [manifest, setManifest] = useState(""), [grading, setGrading] = useState("[]"), [html, setHtml] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [modelReady, setModelReady] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [importOpen, setImportOpen] = useState(false), [raw, setRaw] = useState<string | null>(null);
  const [pending, setPending] = useState<Generation | null>(() => {
    try { const value = sessionStorage.getItem(storageKey + ".pending"); return value ? JSON.parse(value) as Generation : null; } catch { return null; }
  });
  const controller = useRef<AbortController | null>(null);
  function displayDraft(value: Draft) {
    setSource(value); setManifest(JSON.stringify(value.manifest, null, 2)); setGrading(JSON.stringify(value.grading, null, 2));
    setHtml(decode(value.assets[value.manifest.entry] ?? ""));
  }
  async function refresh(signal?: AbortSignal) {
    const list = await request<Page<Job>>(`${base}/authoring/jobs`, { signal });
    const latest = sessionStorage.getItem(storageKey + ".job");
    if (latest && !list.items.some((item) => item.id === latest)) {
      try { list.items.unshift(await request<Job>(`${base}/authoring/jobs/${latest}`, { signal })); }
      catch { if (!signal?.aborted) sessionStorage.removeItem(storageKey + ".job"); }
    }
    if (!signal?.aborted) { setJobs(list.items); setCursor(list.next_cursor); }
  }
  useEffect(() => {
    const current = new AbortController(); controller.current = current;
    void request<{ model_available: boolean }>(`${base}/authoring/config`, { signal: current.signal })
      .then((value) => { if (!current.signal.aborted) setModelReady(value.model_available); }).catch((error) => { if (!current.signal.aborted) onError(error); });
    void refresh(current.signal).catch((error) => { if (!current.signal.aborted) onError(error); });
    const timer = setInterval(() => { void refresh(current.signal).catch(() => { /* Keep last known state; explicit refresh reports connection errors. */ }); }, 5000);
    return () => { current.abort(); clearInterval(timer); };
  }, [base]);
  useEffect(() => {
    const current = new AbortController();
    setSource(null); setHtml(""); setManifest(""); setGrading("[]"); setRaw(null); setNotice("");
    if (activity) void request<Draft>(`${base}/activities/${activity.id}/source`, { signal: current.signal })
      .then((value) => { if (!current.signal.aborted) displayDraft(value); }).catch((error) => { if (!current.signal.aborted) onError(error); });
    return () => current.abort();
  }, [base, activity?.id, activity?.draft_revision]);
  async function act(run: (signal: AbortSignal) => Promise<void>) {
    const signal = controller.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function generate() {
    await act(async (signal) => {
      const body = pending ?? { prompt, activity_id: activity?.id ?? null, expected_revision: activity?.draft_revision ?? 0, request_key: crypto.randomUUID() };
      sessionStorage.setItem(storageKey + ".pending", JSON.stringify(body)); setPending(body);
      const job = await request<Job>(`${base}/authoring/jobs`, { method: "POST", csrf: session.csrf_token, body, signal });
      if (signal.aborted) return;
      sessionStorage.setItem(storageKey + ".job", job.id);
      sessionStorage.removeItem(storageKey + ".pending"); setPending(null); setNotice(`任务已入队（${job.id}）。完成后在下方打开草稿并试做。`); await refresh(signal);
    });
  }
  async function draft(): Promise<Draft> {
    const metadata = JSON.parse(manifest) as Manifest;
    const assets = { ...(source?.assets ?? {}), [metadata.entry]: encode(html) };
    const declared = await Promise.all(Object.entries(assets).map(async ([path, value]) => ({ path, sha256: await hash(value),
      mediaType: path.endsWith(".html") ? "text/html" : path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css" : (metadata.assets as { path: string; mediaType: string }[] | undefined)?.find((item) => item.path === path)?.mediaType ?? "unsupported" })));
    return { manifest: { ...metadata, assets: declared }, assets, grading: JSON.parse(grading) as unknown[], expected_revision: activity?.draft_revision ?? 0 };
  }
  async function save() {
    await act(async (signal) => {
      const body = { draft: await draft(), activity_id: activity?.id ?? null, request_key: crypto.randomUUID() };
      const value = await request<ImportResult>(`${base}/authoring/imports`, { method: "POST", csrf: session.csrf_token, body, signal });
      if (signal.aborted) return;
      sessionStorage.setItem(storageKey + ".import", value.id);
      if (value.result) { await onSaved(value.result.id); setNotice("草稿已保存。修改后的版本需要重新试做，已发布版本保持不变。"); }
      else setNotice(`原文件已保留，未替换活动：${value.error_message}（记录 ${value.id}）`);
    });
  }
  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    await act(async () => {
      if (file.size > 8 * 1024 * 1024) throw new Error("页面文件超过 8 MiB 上限。");
      const text = await file.text();
      if (file.name.endsWith(".json")) displayDraft(JSON.parse(text) as Draft);
      else { setHtml(text); setNotice("HTML 已读取；请补充数据约定和答案标准，再保存并真实试做。"); }
      setImportOpen(true);
    });
    event.target.value = "";
  }
  return <section className="panel section authoring">
    <div className="roster-tools"><div><h2>{activity ? `制作 · ${activity.title}` : "制作新活动"}</h2><p>描述教学目标，让 AI 生成互动页面；保存后试做，再发布。</p></div>
      <button disabled={busy} onClick={() => setImportOpen(!importOpen)}>{importOpen ? "收起页面导入" : "导入 / 手动修改"}</button></div>
    <div className="authoring-columns"><div>
      <label>教学目标与{activity ? "修改" : "制作"}要求<textarea rows={5} maxLength={8000} value={prompt} disabled={busy || !!pending} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：给一年级设计一个校园词汇闯关活动，每题有情境提示，答完可以保存进度。" /></label>
      <button className="primary" disabled={busy || !modelReady || (!prompt.trim() && !pending)} onClick={() => void generate()}>{pending ? "恢复原入队请求" : activity ? "按要求修改草稿" : "生成活动草稿"}</button>
      {!modelReady && <p className="field-help">模型未配置或不可用，仍可导入页面、试做和发布。</p>}
      {pending && <p className="notice-box">上一项入队结果尚未确认。点击恢复会复用原操作键，不会创建第二项任务。</p>}
      <p className="field-help">生成完成表示草稿已保存；接入验证以真实试做回执为准，教学内容由教师检查。</p>
    </div><div className="collection-panel"><h3>将收集的内容</h3>
      {source ? <ul>{source.manifest.questions.map((question) => <li key={question.id}>{question.title}<span className="field-help"> · {kinds[question.kind] ?? question.kind}</span></li>)}</ul> : <p>保存草稿后查看题目、文字、数值和图片字段。</p>}
      <p className="field-help">学生数据保存在当前空间。图片由受控区域上传；未配置标准的开放回答不会生成正确率。</p></div></div>
    {notice && <p role="status" className="notice-box">{notice}</p>}
    {importOpen && <div className="section"><h3>导入页面或修改现有文件</h3><p>支持单个 UTF-8 HTML 配合数据约定，或 OpenForm JSON 页面包。页面须接入保存/提交协议；外部网络、表单与不支持的资源会被拒绝并保留原文件。</p>
      <label>选择 HTML 或 JSON 页面包<input type="file" accept=".html,.json" disabled={busy} onChange={(event) => void loadFile(event)} /></label>
      <label>页面 HTML<textarea className="source-input" rows={8} value={html} onChange={(event) => setHtml(event.target.value)} disabled={busy} /></label>
      <details><summary>数据约定与答案标准（高级）</summary><label>活动清单 JSON<textarea className="source-input" rows={10} value={manifest} onChange={(event) => setManifest(event.target.value)} disabled={busy} /></label>
        <label>服务端答案标准 JSON<textarea className="source-input" rows={4} value={grading} onChange={(event) => setGrading(event.target.value)} disabled={busy} /></label></details>
      <div className="row-actions"><button className="primary" disabled={busy || !html.trim() || !manifest.trim()} onClick={() => void save()}>保存草稿并检查兼容性</button>
        <button disabled={busy} onClick={() => void act(async (signal) => { const id = sessionStorage.getItem(storageKey + ".import"); if (!id) { setNotice("当前浏览器没有待恢复的导入记录。"); return; } const value = await request<ImportResult>(`${base}/authoring/imports/${id}`, { signal }); if (!signal.aborted && value.draft) { displayDraft(value.draft); setNotice(value.error_message ?? "已恢复原导入文件。"); } })}>恢复上次导入文件</button></div>
    </div>}
    <details className="section" open><summary>制作任务 · 刷新后仍可找回</summary><button disabled={busy} onClick={() => void act((signal) => refresh(signal))}>刷新任务</button>
      <div className="table-scroll"><table><thead><tr><th>任务</th><th>状态</th><th>处理</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td><small>{new Date(job.created_at).toLocaleString("zh-CN")}</small><p className="field-help">{job.id}</p></td><td>{labels[job.status] ?? "未知状态"}<p>{job.error_message}</p>{job.usage?.total_tokens !== undefined && <small>用量 {job.usage.total_tokens} tokens</small>}</td><td>
        {job.result && <button disabled={busy} onClick={() => void act(() => onSaved(job.result!.id))}>打开生成草稿</button>}
        <button disabled={busy} onClick={() => void act(async (signal) => { const value = await request<Job>(`${base}/authoring/jobs/${job.id}`, { signal }); if (!signal.aborted) { setPrompt(value.prompt ?? ""); setRaw(value.raw_output ?? null); setNotice("已读取任务要求。结果未知的任务请先核对供应商费用，再手动生成新任务。"); } })}>查看要求 / 原输出</button>
      </td></tr>)}{!jobs.length && <tr><td colSpan={3}>尚无制作任务。</td></tr>}</tbody></table></div>
      {cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Job>>(`${base}/authoring/jobs?cursor=${cursor}`, { signal }); if (!signal.aborted) { setJobs((current) => [...current, ...page.items]); setCursor(page.next_cursor); } })}>加载更多任务</button>}
    </details>
    {raw && <details className="section"><summary>模型原输出（未执行，待教师检查）</summary><pre className="answer-data">{raw}</pre></details>}
  </section>;
}
