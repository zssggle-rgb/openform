import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { request, RequestError } from "./http";
import type { Session, Workspace } from "./identity";
import type { Page } from "./roster";

interface Manifest { title: string; objective: string; entry: string; questions: { id: string; title: string; kind: string; dataPath: string }[]; [key: string]: unknown }
interface Draft { manifest: Manifest; assets: Record<string, string>; grading: unknown[]; expected_revision: number }
interface Job { id: string; activity_id?: string | null; status: string; result: { id: string; draft_revision: number } | null; error_code?: string | null; error_message: string | null; created_at: string; prompt?: string }
interface ImportResult { id: string; status: string; result: { id: string } | null; error_message: string | null; draft?: Draft }
interface Generation { prompt: string; activity_id: string | null; expected_revision: number; request_key: string }
const labels: Record<string, string> = { queued: "正在准备活动…", running: "正在制作活动…", succeeded: "活动已生成，可以预览并试做", failed: "暂未生成活动，请调整要求或选择样板开始。", outcome_unknown: "生成结果尚未确认，请稍后查看。", cancelled: "本次制作已取消，已有活动保留。" };
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
function object(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function importedDraft(value: unknown): Draft {
  if (!object(value) || !object(value.manifest) || !object(value.assets) || !Array.isArray(value.grading)) throw new Error("页面包需包含 manifest、assets 和 grading。");
  const metadata = value.manifest;
  if (typeof metadata.title !== "string" || typeof metadata.objective !== "string" || typeof metadata.entry !== "string"
    || !Array.isArray(metadata.questions) || metadata.questions.some((question: unknown) => !object(question) || ["id", "title", "kind", "dataPath"].some((key) => typeof question[key] !== "string"))
    || Object.values(value.assets).some((asset) => typeof asset !== "string") || typeof value.assets[metadata.entry] !== "string") throw new Error("活动清单、题目或入口文件不完整，请检查页面包格式。");
  return value as unknown as Draft;
}
async function hash(encoded: string): Promise<string> {
  const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map((value) => value.toString(16).padStart(2, "0")).join("");
}

export function AuthoringView({ session, workspace, activity, activityNames, onSaved, onError }: {
  session: Session; workspace: Workspace; activity: { id: string; draft_revision: number; title: string } | null;
  activityNames: Record<string, string>;
  onSaved: (id: string, signal?: AbortSignal) => Promise<boolean>; onError: (error: unknown) => void;
}) {
  const base = `/api/workspaces/${workspace.id}`, storageKey = `openform.authoring.${workspace.id}.${session.account_id}`;
  const pendingKey = `${storageKey}.pending.${activity?.id ?? "new"}`;
  const jobKey = `${storageKey}.job.${activity?.id ?? "new"}`;
  const [prompt, setPrompt] = useState(""), [source, setSource] = useState<Draft | null>(null);
  const [manifest, setManifest] = useState(""), [grading, setGrading] = useState("[]"), [html, setHtml] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [modelReady, setModelReady] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importPending, setImportPending] = useState(() => sessionStorage.getItem(storageKey + ".import-pending"));
  const [pending, setPending] = useState<Generation | null>(() => {
    try {
      const stored = sessionStorage.getItem(pendingKey) ?? sessionStorage.getItem(storageKey + ".pending");
      if (!stored) return null;
      const value = JSON.parse(stored) as Generation;
      return value.activity_id === (activity?.id ?? null) ? value : null;
    } catch { return null; }
  });
  const controller = useRef<AbortController | null>(null);
  const followingJob = useRef<string | null>(null), openedJob = useRef<string | null>(null);
  const onSavedRef = useRef(onSaved); onSavedRef.current = onSaved;
  function displayDraft(input: unknown) {
    const value = importedDraft(input), entry = decode(value.assets[value.manifest.entry]);
    setSource(value); setManifest(JSON.stringify(value.manifest, null, 2)); setGrading(JSON.stringify(value.grading, null, 2)); setHtml(entry);
  }
  async function refresh(signal?: AbortSignal) {
    const list = await request<Page<Job>>(`${base}/authoring/jobs`, { signal });
    const scopedJob = sessionStorage.getItem(jobKey);
    const latest = scopedJob ?? sessionStorage.getItem(storageKey + ".job");
    if (latest && !list.items.some((item) => item.id === latest)) {
      try { list.items.unshift(await request<Job>(`${base}/authoring/jobs/${latest}`, { signal })); }
      catch (error) {
        if (error instanceof RequestError && [403, 404].includes(error.status)) {
          if (!signal?.aborted) sessionStorage.removeItem(scopedJob ? jobKey : storageKey + ".job");
        } else throw error;
      }
    }
    if (!signal?.aborted) {
      const restored = list.items.find((item) => item.id === latest);
      if (!followingJob.current && restored && (scopedJob || (["queued", "running"].includes(restored.status) && (restored.activity_id ?? null) === (activity?.id ?? null)))) followingJob.current = restored.id;
      setJobs(list.items); setCursor(list.next_cursor);
    }
  }
  useEffect(() => {
    const current = new AbortController(); controller.current = current;
    void request<{ model_available: boolean }>(`${base}/authoring/config`, { signal: current.signal })
      .then((value) => { if (!current.signal.aborted) setModelReady(value.model_available); }).catch((error) => { if (!current.signal.aborted) onError(error); });
    void refresh(current.signal).catch((error) => { if (!current.signal.aborted) onError(error); });
    return () => current.abort();
  }, [base]);
  const currentJob = jobs.find((job) => job.id === followingJob.current);
  async function openJob(job: Job, signal: AbortSignal) {
    if (!job.result || signal.aborted) return;
    const opened = await onSavedRef.current(job.result.id, signal);
    if (opened && sessionStorage.getItem(jobKey) === job.id) sessionStorage.removeItem(jobKey);
  }
  const pollingId = currentJob && ["queued", "running"].includes(currentJob.status) ? currentJob.id : null;
  useEffect(() => {
    if (!pollingId) return;
    const current = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await request<Job>(`${base}/authoring/jobs/${pollingId}`, { signal: current.signal });
        if (!current.signal.aborted) setJobs((previous) => previous.map((job) => job.id === value.id ? value : job));
      } catch (error) { if (!current.signal.aborted) onError(error); }
      finally { if (!current.signal.aborted) timer = setTimeout(() => void poll(), 5000); }
    };
    timer = setTimeout(() => void poll(), 5000);
    return () => { current.abort(); clearTimeout(timer); };
  }, [base, pollingId]);
  useEffect(() => {
    if (!currentJob?.result || currentJob.status !== "succeeded" || openedJob.current === currentJob.id) return;
    if (currentJob.result.id === activity?.id && currentJob.result.draft_revision === activity.draft_revision) return;
    const signal = controller.current?.signal;
    if (!signal || signal.aborted) return;
    openedJob.current = currentJob.id;
    void openJob(currentJob, signal).catch((error) => { if (!signal.aborted) { openedJob.current = null; onError(error); } });
  }, [currentJob?.id, currentJob?.status, currentJob?.result?.id, currentJob?.result?.draft_revision]);
  useEffect(() => {
    const current = new AbortController();
    setSource(null); setHtml(""); setManifest(""); setGrading("[]"); setNotice("");
    if (activity) void request<Draft>(`${base}/activities/${activity.id}/source`, { signal: current.signal })
      .then((value) => { if (!current.signal.aborted) displayDraft(value); }).catch((error) => { if (!current.signal.aborted) onError(error); });
    return () => current.abort();
  }, [base, activity?.id, activity?.draft_revision]);
  async function act(run: (signal: AbortSignal) => Promise<unknown>) {
    const signal = controller.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function generate() {
    await act(async (signal) => {
      const body = pending ?? { prompt, activity_id: activity?.id ?? null, expected_revision: activity?.draft_revision ?? 0, request_key: crypto.randomUUID() };
      sessionStorage.setItem(pendingKey, JSON.stringify(body)); setPending(body);
      let job: Job;
      try { job = await request<Job>(`${base}/authoring/jobs`, { method: "POST", csrf: session.csrf_token, body, signal }); }
      catch (error) {
        if (!signal.aborted && error instanceof RequestError && error.status > 0 && error.status < 500) { sessionStorage.removeItem(pendingKey); setPending(null); }
        throw error;
      }
      if (signal.aborted) return;
      sessionStorage.setItem(jobKey, job.id);
      sessionStorage.removeItem(pendingKey);
      const legacy = sessionStorage.getItem(storageKey + ".pending");
      try { if (legacy && JSON.parse(legacy).request_key === body.request_key) sessionStorage.removeItem(storageKey + ".pending"); }
      catch { /* A malformed legacy preference cannot invalidate a confirmed job. */ }
      setPending(null); followingJob.current = job.id;
      setNotice(""); setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]); await refresh(signal);
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
      const key = importPending ?? crypto.randomUUID();
      const body = { draft: await draft(), activity_id: activity?.id ?? null, request_key: key };
      const fingerprint = await hash(encode(JSON.stringify(body)));
      const previous = sessionStorage.getItem(storageKey + ".import-hash");
      if (importPending && previous && previous !== fingerprint) throw new Error("原导入结果尚未确认，请先恢复记录或重新选择同一原文件；不能复用操作键保存不同内容。");
      sessionStorage.setItem(storageKey + ".import-hash", fingerprint);
      sessionStorage.setItem(storageKey + ".import-pending", key); setImportPending(key);
      let value: ImportResult;
      try { value = await request<ImportResult>(`${base}/authoring/imports`, { method: "POST", csrf: session.csrf_token, body, signal }); }
      catch (error) {
        if (!signal.aborted && error instanceof RequestError && error.status > 0 && error.status < 500) { sessionStorage.removeItem(storageKey + ".import-pending"); setImportPending(null); }
        throw error;
      }
      if (signal.aborted) return;
      sessionStorage.setItem(storageKey + ".import", value.id);
      sessionStorage.removeItem(storageKey + ".import-pending"); setImportPending(null);
      if (value.result) { await onSaved(value.result.id); setNotice("草稿已保存。修改后的版本需要重新试做，已发布版本保持不变。"); }
      else setNotice(`未能导入该文件，已有活动保留。${value.error_message ?? "请检查文件后重试。"}`);
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
  async function recoverImport() {
    await act(async (signal) => {
      const id = importPending ?? sessionStorage.getItem(storageKey + ".import");
      if (!id) { setNotice("当前浏览器没有待恢复的导入记录。"); return; }
      try {
        const value = await request<ImportResult>(`${base}/authoring/imports/${id}`, { signal });
        if (!signal.aborted && value.draft) { displayDraft(value.draft); sessionStorage.setItem(storageKey + ".import", value.id);
          sessionStorage.removeItem(storageKey + ".import-pending"); setImportPending(null);
          setNotice(value.error_message ?? "已恢复原导入文件。"); if (value.result) await onSaved(value.result.id); }
      } catch (error) {
        if (!signal.aborted && error instanceof RequestError && error.status === 404) setNotice("尚未找到原导入回执；操作键已保留，请稍后恢复或选择同一原文件重试。");
        else throw error;
      }
    });
  }
  return <section className="panel authoring">
    <h2>{activity ? activity.title : "教学内容"}</h2>
    <div>
      <label>教学目标与{activity ? "修改" : "制作"}要求<textarea rows={5} maxLength={8000} value={prompt} disabled={busy || !!pending} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：给一年级设计一个校园词汇闯关活动，每题有情境提示，答完可以保存进度。" /></label>
      <button className="primary" disabled={busy || !!pollingId || !modelReady || (!prompt.trim() && !pending)} onClick={() => void generate()}>{pending ? "继续确认制作结果" : activity ? "按要求修改活动" : "生成活动"}</button>
      {!modelReady && <p className="field-help">{activity ? "暂时无法生成，可以继续预览现有活动。" : "暂时无法生成，可以从右侧选择样板开始。"}</p>}
      {pending && <p role="status">尚未确认制作结果，请继续确认。</p>}
      {currentJob && <div role="status" className={currentJob.status === "failed" ? "error-box section" : "section"}><p>{currentJob.error_code === "MODEL_CONFIGURATION_ERROR" ? "活动生成暂不可用，请联系管理员。已有活动仍可使用。" : labels[currentJob.status] ?? "正在读取活动"}</p>
        {["queued", "running", "outcome_unknown"].includes(currentJob.status) && <button disabled={busy} onClick={() => void act((signal) => refresh(signal))}>查看制作结果</button>}
        {currentJob.result && <button disabled={busy} onClick={() => void act((signal) => openJob(currentJob, signal))}>打开活动</button>}</div>}
    </div>
    {source && <div className="section question-list"><h3>题目与收集内容</h3><p>{source.manifest.objective}</p><ol>{source.manifest.questions.map((question) => {
      const rule = source.grading.find((item) => object(item) && item.questionId === question.id);
      return <li key={question.id}><h3>{question.title}</h3><span className="tag">{kinds[question.kind] ?? "作答"}</span>{object(rule) && "expected" in rule ? <p>参考答案：{String(rule.expected)}</p> : <p>开放回答</p>}</li>;
    })}</ol></div>}
    {notice && <p role="status" className="notice-box">{notice}</p>}
    {importOpen && <div className="section"><h3>导入页面或修改现有文件</h3><p>支持单个 UTF-8 HTML 配合数据约定，或 OpenForm JSON 页面包。页面须接入保存/提交协议；外部网络、表单与不支持的资源会被拒绝并保留原文件。</p>
      {importPending && <p className="notice-box">上次导入结果未确认。请先恢复原请求记录，避免重复创建活动。</p>}
      <label>选择 HTML 或 JSON 页面包<input type="file" accept=".html,.json" disabled={busy} onChange={(event) => void loadFile(event)} /></label>
      <label>页面 HTML<textarea className="source-input" rows={8} value={html} onChange={(event) => setHtml(event.target.value)} disabled={busy || !!importPending} /></label>
      <details><summary>数据约定与答案标准（高级）</summary><label>活动清单 JSON<textarea className="source-input" rows={10} value={manifest} onChange={(event) => setManifest(event.target.value)} disabled={busy || !!importPending} /></label>
        <label>服务端答案标准 JSON<textarea className="source-input" rows={4} value={grading} onChange={(event) => setGrading(event.target.value)} disabled={busy || !!importPending} /></label></details>
      <div className="row-actions"><button className="primary" disabled={busy || !html.trim() || !manifest.trim()} onClick={() => void save()}>保存草稿并检查兼容性</button>
        <button disabled={busy} onClick={() => void recoverImport()}>恢复上次导入文件</button></div>
    </div>}
    <details className="section"><summary>最近制作的活动</summary><button disabled={busy} onClick={() => void act((signal) => refresh(signal))}>刷新活动</button>
      {jobs.map((job) => <div className="list-row" key={job.id}><div><strong>{job.result ? activityNames[job.result.id] ?? "已生成的活动" : "未完成的活动"}</strong><p>{labels[job.status] ?? "等待查看"}</p></div>
        {job.result && <button disabled={busy} onClick={() => void act((signal) => openJob(job, signal))}>打开活动</button>}
        <button disabled={busy} onClick={() => void act(async (signal) => { const value = await request<Job>(`${base}/authoring/jobs/${job.id}`, { signal }); if (!signal.aborted) { setPrompt(value.prompt ?? ""); setNotice("已恢复教学要求，可以继续修改。"); } })}>恢复教学要求</button>
      </div>)}{!jobs.length && <p>还没有制作记录。</p>}
      {cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Job>>(`${base}/authoring/jobs?cursor=${cursor}`, { signal }); if (!signal.aborted) { setJobs((current) => [...current, ...page.items]); setCursor(page.next_cursor); } })}>加载更多任务</button>}
    </details>
    <div className="section"><button disabled={busy} className="text-button" onClick={() => setImportOpen(!importOpen)}>{importOpen ? "收起文件导入" : "导入活动文件（高级）"}</button></div>
  </section>;
}
