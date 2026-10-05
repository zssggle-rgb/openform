import { useEffect, useRef, useState, type FormEvent } from "react";
import { request, RequestError } from "./http";
import type { Session, Workspace } from "./identity";
import type { Page } from "./roster";

interface Coverage { included: number; total_completed: number; omitted: number; rule: string }
interface Finding { title: string; explanation: string; evidence: { record_id: string; question_id: string }[] }
interface Report { id: string; revision: number; reviewed_at: string | null; shared_text: string | null; captured_at: string;
  body: { overview: string; findings: Finding[]; suggestions: Finding[]; limitations: string[] };
  payload: { version_number: number; coverage: Coverage; statistics: { completed: number; planned_count: number | null; completion_rate: number | null }; questions: { id: string; title: string }[]; records: { record_id: string; answers: unknown }[] } }
interface ReportEntry { id: string; captured_at: string; reviewed_at: string | null; invalidated_at: string | null; coverage: Coverage }
interface AnalysisJob { id: string; status: string; result: { id: string } | null; error_message: string | null; raw_output?: string | null; usage?: { total_tokens?: number } }
interface Pending { prompt: string; request_key: string }
const labels: Record<string, string> = { queued: "排队中", running: "分析中", succeeded: "报告已生成 · 待教师复核", failed: "未生成可用报告", outcome_unknown: "结果与费用未知", cancelled: "已取消" };

export function AnalysisView({ session, workspace, classroomId, onError }: { session: Session; workspace: Workspace; classroomId: string; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`, key = `openform.analysis.${workspace.id}.${session.account_id}.${classroomId}`;
  const [pending, setPending] = useState<Pending | null>(null), [prompt, setPrompt] = useState("围绕教学目标归纳错误、开放回答与再次讲解建议。");
  const [job, setJob] = useState<AnalysisJob | null>(null), [reports, setReports] = useState<ReportEntry[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null), [evidence, setEvidence] = useState<unknown>(null), [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false), [blocked, setBlocked] = useState(false), [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  const reportSelection = useRef(0);
  const [tasks, setTasks] = useState<AnalysisJob[]>([]), [taskCursor, setTaskCursor] = useState<string | null>(null);
  async function loadReports(signal: AbortSignal) {
    const page = await request<Page<ReportEntry>>(`${base}/classrooms/${classroomId}/reports`, { signal });
    if (!signal.aborted) { setReports(page.items); setCursor(page.next_cursor); }
  }
  async function openReport(id: string, signal: AbortSignal) {
    const selection = ++reportSelection.current;
    const value = await request<Report>(`${base}/reports/${id}`, { signal });
    if (!signal.aborted && selection === reportSelection.current) { setReport(value); setEvidence(null); setConfirmed(false); }
  }
  async function loadJob(id: string, signal: AbortSignal) {
    const value = await request<AnalysisJob>(`${base}/analysis/jobs/${id}`, { signal });
    if (signal.aborted) return;
    setJob(value);
    setTasks((items) => items.map((item) => item.id === value.id ? value : item));
    if (value.status === "succeeded" && value.result) { await openReport(value.result.id, signal); await loadReports(signal); }
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    try {
      const stored = sessionStorage.getItem(key + ".pending");
      if (stored) {
        const value: unknown = JSON.parse(stored);
        if (!value || typeof value !== "object" || !("prompt" in value) || !("request_key" in value) || typeof value.prompt !== "string" || typeof value.request_key !== "string") throw new Error("分析恢复信息无法识别，请联系管理员处理。");
        setPending(value as Pending); setPrompt(value.prompt);
      }
    } catch (error) { setBlocked(true); onError(error); }
    void loadReports(controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); });
    void request<Page<AnalysisJob>>(`${base}/classrooms/${classroomId}/analysis/jobs`, { signal: controller.signal })
      .then((page) => { if (!controller.signal.aborted) { setTasks(page.items); setTaskCursor(page.next_cursor); } }).catch((error) => { if (!controller.signal.aborted) onError(error); });
    const latest = sessionStorage.getItem(key + ".job");
    if (latest) void loadJob(latest, controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); });
    return () => controller.abort();
  }, [base, classroomId]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const controller = new AbortController(), id = setInterval(() => { void loadJob(job.id, controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); }); }, 5000);
    return () => { controller.abort(); clearInterval(id); };
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
    await act(async (signal) => {
      try {
        await request(`${base}/reports/${report.id}/${action}`, { method: "POST", csrf: session.csrf_token, signal,
          body: { confirmed: true, expected_revision: report.revision, ...(action === "share" ? { text } : {}) } });
        await openReport(report.id, signal); await loadReports(signal); if (!signal.aborted) setNotice(action === "review" ? "已记录教师复核。" : text?.trim() ? "课堂摘要已共享，仅参与者可查看。" : "共享已撤回。");
      } catch (error) { await openReport(report.id, signal); throw error; }
    });
  }
  function findings(items: Finding[]) {
    return items.map((item, index) => <article key={index}><h3>{item.title}</h3><p className="answer-data">{item.explanation}</p><div className="row-actions">{item.evidence.map((reference, number) => <button key={number} disabled={busy} onClick={() => void act(async (signal) => { const value = await request(`${base}/reports/${report!.id}/evidence/${reference.record_id}`, { signal }); if (!signal.aborted) setEvidence(value); })}>依据 {number + 1} · {report?.payload.questions.find((question) => question.id === reference.question_id)?.title ?? reference.question_id}</button>)}</div></article>);
  }
  return <section className="section"><h2>教学诊断与建议</h2><p>模型只归纳固定快照中的文本、数值与结构化答案；基础统计由规则计算，图片未分析。学生内容会发给已配置的模型服务，请先确认适合分析。</p>
    <form className="compact-form" onSubmit={(event) => void generate(event)}><label>本次分析要求<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} required maxLength={4000} disabled={busy || Boolean(pending) || blocked} /></label><button disabled={busy || blocked || Boolean(job && ["queued", "running"].includes(job.status))} className="primary">{pending ? "恢复原分析请求" : "生成固定快照诊断"}</button></form>
    {job && <div className="pending-box"><p>{labels[job.status] ?? job.status} · {job.usage?.total_tokens === undefined ? "用量未确认" : `${job.usage.total_tokens} token`}</p>{job.error_message && <p>{job.error_message}</p>}{job.raw_output && job.status !== "succeeded" && <details><summary>查看未发布的模型原输出</summary><pre className="answer-data">{job.raw_output}</pre></details>}</div>}
    {notice && <p role="status" className="success-box">{notice}</p>}
    {tasks.length > 0 && <details className="section"><summary>我的分析任务（可跨设备恢复）</summary>{tasks.map((task) => <div key={task.id} className="list-row"><p>{labels[task.status] ?? task.status} · {task.id.slice(0, 8)}</p><button disabled={busy} onClick={() => void act((signal) => loadJob(task.id, signal))}>查看任务 / 恢复进度</button></div>)}{taskCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<AnalysisJob>>(`${base}/classrooms/${classroomId}/analysis/jobs?cursor=${taskCursor}`, { signal }); if (!signal.aborted) { setTasks((items) => [...items, ...page.items]); setTaskCursor(page.next_cursor); } })}>加载更多任务</button>}</details>}
    <div className="section"><h3>诊断历史</h3>{reports.map((item) => <div key={item.id} className="list-row"><p>{new Date(item.captured_at).toLocaleString()} · 覆盖 {item.coverage.included}/{item.coverage.total_completed} · {item.invalidated_at ? "资料删除后已失效" : item.reviewed_at ? "已复核" : "待复核"}</p><button disabled={busy || Boolean(item.invalidated_at)} onClick={() => void act((signal) => openReport(item.id, signal))}>查看报告</button></div>)}
      {!reports.length && <p>暂无报告；可直接查看上方统计与原始提交。</p>}{cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<ReportEntry>>(`${base}/classrooms/${classroomId}/reports?cursor=${cursor}`, { signal }); if (!signal.aborted) { setReports((items) => [...items, ...page.items]); setCursor(page.next_cursor); } })}>加载更多报告</button>}</div>
    {report && <section className="panel section"><h2>快照诊断 · {report.reviewed_at ? "已由教师复核" : "待教师复核"}</h2><p>活动 v{report.payload.version_number} · 截止 {new Date(report.captured_at).toLocaleString()} · 已纳入 {report.payload.coverage.included} / {report.payload.coverage.total_completed} 份，遗漏 {report.payload.coverage.omitted} 份。</p><p className="field-help">{report.payload.coverage.rule}</p>
      <p>平台统计：完成 {report.payload.statistics.completed}；计划人数 {report.payload.statistics.planned_count ?? "未知"}；完成率 {report.payload.statistics.completion_rate === null ? "无固定分母" : `${Math.round(report.payload.statistics.completion_rate * 100)}%`}。</p><p className="answer-data">{report.body.overview}</p>
      <h3>发现与归类</h3>{findings(report.body.findings)}<h3>教学建议</h3>{findings(report.body.suggestions)}<h3>局限</h3><ul>{report.body.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
      <p className="field-help">平台验证引用存在，不自动证明解释正确；请逐项查看依据，不将报告自动转为成绩或能力标签。</p>
      {evidence !== null && <details open><summary>原始依据 · 仅教师授权查看</summary><pre className="answer-data">{JSON.stringify(evidence, null, 2)}</pre></details>}
      {!report.reviewed_at && <><label className="checkbox-label"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />已核对结论、原始依据和覆盖局限</label><button disabled={busy || !confirmed} onClick={() => void update("review")}>记录教师复核</button></>}
      {report.reviewed_at && <form key={`${report.id}:${report.revision}`} className="compact-form section" onSubmit={(event) => { event.preventDefault(); void update("share", String(new FormData(event.currentTarget).get("text"))); }}><label>准备共享的课堂摘要<textarea name="text" defaultValue={report.shared_text ?? ""} maxLength={2000} disabled={busy} required /></label><p>只发布你填写并确认的摘要。避免个体作答、姓名及联系方式；全文报告与原始依据不会随摘要共享。</p><button disabled={busy} className="primary">确认并共享课堂摘要</button>{report.shared_text && <button type="button" disabled={busy} onClick={() => void update("share", "")}>撤回共享</button>}</form>}
    </section>}
  </section>;
}
