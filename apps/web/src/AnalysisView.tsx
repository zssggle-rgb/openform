import { useEffect, useRef, useState, type FormEvent } from "react";
import { request, RequestError } from "./http";
import type { Session, Workspace } from "./identity";
import type { Page } from "./roster";
import { AnswerDisplay, type QuestionDisplay } from "./AnswerDisplay";

interface Coverage { included: number; total_completed: number; omitted: number; rule: string }
interface Finding { title: string; explanation: string; evidence: { record_id: string; question_id: string }[] }
interface Report { id: string; revision: number; reviewed_at: string | null; shared_text: string | null; captured_at: string;
  body: { overview: string; findings: Finding[]; suggestions: Finding[]; limitations: string[] };
  payload: { classroom_title: string; version_number: number; coverage: Coverage; statistics: { completed: number; planned_count: number | null; completion_rate: number | null }; questions: { id: string; title: string }[]; records: { record_id: string; answers: unknown }[] } }
interface ReportEntry { id: string; captured_at: string; reviewed_at: string | null; invalidated_at: string | null; coverage: Coverage }
interface AnalysisJob { id: string; status: string; result: { id: string } | null; error_code?: string | null; created_at?: string }
interface Evidence { display_name: string; group_name: string | null; number: number; created_at: string; classroom_id: string; data: unknown; questions: QuestionDisplay[]; questionId: string }
interface Pending { prompt: string; request_key: string }
const labels: Record<string, string> = { queued: "正在准备教学建议…", running: "正在整理教学建议…", succeeded: "教学建议已生成", failed: "教学建议暂时无法生成，请保留要求后重试。", outcome_unknown: "暂时无法确认结果，请稍后查看记录。", cancelled: "已取消" };

export function AnalysisView({ session, workspace, classroomId, onError }: { session: Session; workspace: Workspace; classroomId: string; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`, key = `openform.analysis.${workspace.id}.${session.account_id}.${classroomId}`;
  const [pending, setPending] = useState<Pending | null>(null), [prompt, setPrompt] = useState("围绕教学目标归纳错误、开放回答与再次讲解建议。");
  const [job, setJob] = useState<AnalysisJob | null>(null), [reports, setReports] = useState<ReportEntry[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null), [evidence, setEvidence] = useState<Evidence | null>(null), [confirmed, setConfirmed] = useState(false);
  const [reportLoading, setReportLoading] = useState(false), [evidenceLoading, setEvidenceLoading] = useState(false), [reportsState, setReportsState] = useState("loading");
  const evidenceSelection = useRef(0);
  const evidencePanel = useRef<HTMLElement | null>(null);
  useEffect(() => { if (evidence) evidencePanel.current?.scrollIntoView({ block: "nearest" }); }, [evidence]);
  const [busy, setBusy] = useState(false), [blocked, setBlocked] = useState(false), [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  const reportSelection = useRef(0);
  const syncedJob = useRef<string | null>(null);
  const [reportReadFailure, setReportReadFailure] = useState<{ id: string; message: string; retryable: boolean } | null>(null);
  const [tasks, setTasks] = useState<AnalysisJob[]>([]), [taskCursor, setTaskCursor] = useState<string | null>(null);
  async function loadReports(signal: AbortSignal) {
    const page = await request<Page<ReportEntry>>(`${base}/classrooms/${classroomId}/reports`, { signal });
    if (!signal.aborted) { setReports(page.items); setCursor(page.next_cursor); setReportsState("ready"); }
  }
  async function openReport(id: string, signal: AbortSignal) {
    const selection = ++reportSelection.current;
    evidenceSelection.current++; setEvidence(null); setEvidenceLoading(false); setReportLoading(true);
    setReportReadFailure(null); setReport(null); setConfirmed(false); setNotice("");
    try {
      const value = await request<Report>(`${base}/reports/${id}`, { signal });
      if (!signal.aborted && selection === reportSelection.current) setReport(value);
    } finally { if (!signal.aborted && selection === reportSelection.current) setReportLoading(false); }
  }
  async function syncReport(id: string, signal: AbortSignal) {
    const selection = reportSelection.current + 1;
    try { await openReport(id, signal); }
    catch (error) {
      if (signal.aborted) return;
      if (error instanceof RequestError && error.status === 401) { onError(error); return; }
      if (selection !== reportSelection.current) return;
      const retryable = !(error instanceof RequestError && [403, 404, 410].includes(error.status));
      setReportReadFailure({ id, retryable, message: error instanceof RequestError && !retryable ? error.message : "报告暂时未能打开，请重新读取。" });
    }
    try { await loadReports(signal); }
    catch (error) { if (!signal.aborted) { setReportsState("failed"); if (error instanceof RequestError && error.status === 401) onError(error); } }
  }
  async function loadJob(id: string, signal: AbortSignal, openResult = false) {
    const value = await request<AnalysisJob>(`${base}/analysis/jobs/${id}`, { signal });
    if (signal.aborted) return;
    setJob(value);
    setTasks((items) => items.map((item) => item.id === value.id ? value : item));
    const reportSignal = lifetime.current?.signal;
    if (value.status === "succeeded" && value.result && (openResult || syncedJob.current !== value.id) && reportSignal && !reportSignal.aborted) {
      syncedJob.current = value.id;
      await syncReport(value.result.id, reportSignal);
    }
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    reportSelection.current += 1; syncedJob.current = null;
    setPending(null); setJob(null); setReport(null); setEvidence(null); setConfirmed(false);
    setReports([]); setCursor(null); setTasks([]); setTaskCursor(null); setReportReadFailure(null);
    setBusy(false); setBlocked(false); setNotice(""); setPrompt("围绕教学目标归纳错误、开放回答与再次讲解建议。");
    setReportLoading(false); setEvidenceLoading(false); setReportsState("loading"); evidenceSelection.current++;
    try {
      const stored = sessionStorage.getItem(key + ".pending");
      if (stored) {
        const value: unknown = JSON.parse(stored);
        if (!value || typeof value !== "object" || !("prompt" in value) || !("request_key" in value) || typeof value.prompt !== "string" || typeof value.request_key !== "string") throw new Error("分析恢复信息无法识别，请联系管理员处理。");
        setPending(value as Pending); setPrompt(value.prompt);
      }
    } catch (error) { setBlocked(true); onError(error); }
    void loadReports(controller.signal).catch((error) => { if (!controller.signal.aborted) { setReportsState("failed"); onError(error); } });
    void request<Page<AnalysisJob>>(`${base}/classrooms/${classroomId}/analysis/jobs`, { signal: controller.signal })
      .then((page) => { if (!controller.signal.aborted) { setTasks(page.items); setTaskCursor(page.next_cursor); } }).catch((error) => { if (!controller.signal.aborted) onError(error); });
    const latest = sessionStorage.getItem(key + ".job");
    if (latest) void loadJob(latest, controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); });
    return () => { controller.abort(); reportSelection.current += 1; };
  }, [base, classroomId, key]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await loadJob(job.id, controller.signal); }
      catch (error) { if (!controller.signal.aborted) onError(error); }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000); }
    };
    timer = setTimeout(() => void poll(), 5000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job?.id, job?.status]);
  async function act(run: (signal: AbortSignal) => Promise<void>) {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await act(async (signal) => {
      const body = pending ?? { prompt, request_key: crypto.randomUUID() };
      sessionStorage.setItem(key + ".pending", JSON.stringify(body)); setPending(body);
      try {
        const value = await request<AnalysisJob>(`${base}/classrooms/${classroomId}/analysis`, { method: "POST", csrf: session.csrf_token, signal, body });
        sessionStorage.removeItem(key + ".pending"); sessionStorage.setItem(key + ".job", value.id);
        if (!signal.aborted) { setPending(null); setJob(value); setTasks((items) => items.some((item) => item.id === value.id) ? items : [value, ...items]); await loadJob(value.id, signal); }
      } catch (error) {
        if (error instanceof RequestError && error.status >= 400 && error.status < 500) { sessionStorage.removeItem(key + ".pending"); if (!signal.aborted) setPending(null); }
        throw error;
      }
    });
  }
  async function update(action: "review" | "share", text?: string) {
    if (!report) return;
    const selection = reportSelection.current;
    await act(async (signal) => {
      try {
        await request(`${base}/reports/${report.id}/${action}`, { method: "POST", csrf: session.csrf_token, signal,
          body: { confirmed: true, expected_revision: report.revision, ...(action === "share" ? { text } : {}) } });
        if (signal.aborted || selection !== reportSelection.current) return;
        await syncReport(report.id, signal); if (!signal.aborted && reportSelection.current === selection + 1) setNotice(action === "review" ? "已完成复核。" : text?.trim() ? "课堂总结已共享，学生可以查看。" : "课堂总结已撤回。");
      } catch (error) { if (!(error instanceof RequestError && error.status === 401) && !signal.aborted && selection === reportSelection.current) await syncReport(report.id, signal); throw error; }
    });
  }
  function findings(items: Finding[]) {
    return items.map((item, index) => <article key={index}><h3>{reportText(item.title)}</h3><p className="answer-data">{reportText(item.explanation)}</p><div className="row-actions">{item.evidence.map((reference, number) => <button key={number} disabled={busy || reportLoading} onClick={() => void act(async (signal) => {
      if (!report) return;
      const selection = reportSelection.current, requestNumber = ++evidenceSelection.current;
      setEvidence(null); setEvidenceLoading(true);
      try { const value = await request<Omit<Evidence, "questionId">>(`${base}/reports/${report.id}/evidence/${reference.record_id}`, { signal }); if (!signal.aborted && selection === reportSelection.current && requestNumber === evidenceSelection.current) setEvidence({ ...value, questionId: reference.question_id }); }
      finally { if (!signal.aborted && selection === reportSelection.current && requestNumber === evidenceSelection.current) setEvidenceLoading(false); }
    })}>查看学生答案 {number + 1} · {report?.payload.questions.find((question) => question.id === reference.question_id)?.title ?? "相关题目"}</button>)}</div></article>);
  }
  function reportText(value: string): string {
    if (!report) return value;
    const names = new Map(report.payload.questions.map((question) => [question.id, `“${question.title}”`]));
    for (const record of report.payload.records) if (!names.has(record.record_id)) names.set(record.record_id, "学生答案");
    if (!names.size) return value;
    const identifiers = [...names.keys()].sort((a, b) => b.length - a.length).map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    return value.replace(new RegExp(`(?<![\\w-])(${identifiers.join("|")})(?![\\w-])`, "g"), (id) => names.get(id) ?? id);
  }
  return <section className="section analysis-view"><h2>教学诊断与建议</h2>
    <form className="compact-form analysis-request" onSubmit={(event) => void generate(event)}><label>想重点了解什么？<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} required maxLength={4000} disabled={busy || Boolean(pending) || blocked} /></label><button disabled={busy || blocked || Boolean(job && ["queued", "running"].includes(job.status))} className="primary">{pending ? "继续生成教学建议" : "生成教学建议"}</button></form>
    {job && job.status !== "succeeded" && <div className="pending-box" role="status"><p>{labels[job.status] ?? "正在读取教学建议…"}</p>{job.error_code === "MODEL_CONFIGURATION_ERROR" && <p>请联系管理员检查教学建议服务配置。</p>}</div>}
    {reportReadFailure && <div className="error-box" role="alert"><p>{reportReadFailure.message}</p>{reportReadFailure.retryable && <button disabled={busy} onClick={() => void act((signal) => syncReport(reportReadFailure.id, signal))}>重新读取报告</button>}</div>}
    {notice && <p role="status" className="success-box">{notice}</p>}
    {reportLoading && <p role="status">正在打开教学建议…</p>}
    {report && !reportLoading && <section className="panel section"><h2>{report.payload.classroom_title} · 教学建议</h2><p className="field-help">截至 {new Date(report.captured_at).toLocaleString()} · 分析了 {report.payload.coverage.included} / {report.payload.coverage.total_completed} 份已交答案{report.payload.coverage.omitted > 0 ? `，有 ${report.payload.coverage.omitted} 份未纳入` : ""} · 照片需自行查看</p>
      <p className="answer-data">{reportText(report.body.overview)}</p>
      <h3>需要关注的问题</h3>{findings(report.body.findings)}<h3>教学建议</h3>{findings(report.body.suggestions)}{report.body.limitations.length > 0 && <details><summary>阅读提醒</summary><ul>{report.body.limitations.map((item, index) => <li key={index}>{reportText(item)}</li>)}</ul></details>}
      {evidenceLoading && <p role="status">正在打开学生答案…</p>}
      {evidence && <article className="answer-record" ref={evidencePanel}><h3>{evidence.display_name}{evidence.group_name ? ` · ${evidence.group_name}` : ""}</h3><p className="field-help">提交于 {new Date(evidence.created_at).toLocaleString()} · 第 {evidence.number} 次作答</p>{evidence.questions.filter((question) => question.id === evidence.questionId).map((question) => <AnswerDisplay key={question.id} question={question} data={evidence.data} fileBase={`${base}/classrooms/${evidence.classroom_id}/files`} />)}</article>}
      {!report.reviewed_at ? <><label className="checkbox-label"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />已核对学生答案和教学建议</label><button disabled={busy || !confirmed} onClick={() => void update("review")}>完成复核</button></> : <p className="success-box">已完成复核</p>}
      {report.reviewed_at && <form key={`${report.id}:${report.revision}`} className="compact-form section" onSubmit={(event) => { event.preventDefault(); void update("share", String(new FormData(event.currentTarget).get("text"))); }}><label>给学生的课堂总结<textarea name="text" defaultValue={report.shared_text ?? ""} maxLength={2000} disabled={busy} required /></label><p className="field-help">学生只会看到这段总结，请勿填写个人姓名或个体答案。</p><button disabled={busy} className="primary">共享课堂总结</button>{report.shared_text && <button type="button" disabled={busy} onClick={() => void update("share", "")}>撤回总结</button>}</form>}
    </section>}
    <details className="section"><summary>此前的教学建议</summary>{reports.map((item) => <div key={item.id} className="list-row"><p>{new Date(item.captured_at).toLocaleString()} · {item.invalidated_at ? "已无法查看" : item.reviewed_at ? "已复核" : "待复核"}</p><button disabled={busy || Boolean(item.invalidated_at)} onClick={() => void act((signal) => syncReport(item.id, signal))}>查看建议</button></div>)}
      {reportsState === "loading" ? <p>正在读取记录…</p> : reportsState === "failed" ? <p className="error-box">记录暂时无法读取。</p> : !reports.length && <p>还没有教学建议。</p>}{cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<ReportEntry>>(`${base}/classrooms/${classroomId}/reports?cursor=${cursor}`, { signal }); if (!signal.aborted) { setReports((items) => [...items, ...page.items]); setCursor(page.next_cursor); } })}>加载更多建议</button>}</details>
    {tasks.length > 0 && <details className="section"><summary>生成记录</summary>{tasks.map((task) => <div key={task.id} className="list-row"><p>{task.created_at ? new Date(task.created_at).toLocaleString() : "此前的请求"} · {labels[task.status] ?? "正在读取建议…"}</p><button disabled={busy} onClick={() => void act((signal) => loadJob(task.id, signal, true))}>查看结果</button></div>)}{taskCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<AnalysisJob>>(`${base}/classrooms/${classroomId}/analysis/jobs?cursor=${taskCursor}`, { signal }); if (!signal.aborted) { setTasks((items) => [...items, ...page.items]); setTaskCursor(page.next_cursor); } })}>加载更多记录</button>}</details>}
  </section>;
}
