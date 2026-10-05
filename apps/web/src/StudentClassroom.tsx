import { useEffect, useRef, useState, type FormEvent } from "react";
import { RequestError, request } from "./http";
import type { Page } from "./roster";
import { RuntimePlayer, type Attempt } from "./RuntimePlayer";
import { SharedSummary } from "./SharedSummary";

export interface ParticipantSession {
  kind: "student" | "guest"; workspace_id: string; workspace_name: string; display_name: string; csrf_token: string;
  student_id?: string; guest_id?: string; classroom_id?: string; reference?: string;
}
interface HistoryEntry { attempt_id: string; classroom_id: string; title: string; number: number; state: string; revision: number; receipt: { receiptId: string } | null }

export function StudentClassroom({ session, page = "S01", classroomId, attemptId, onExpired }: { session: ParticipantSession; page?: string; classroomId?: string | null; attemptId?: string | null; onExpired: (error: unknown) => void }) {
  const base = `/api/${session.kind}`;
  const [attempt, setAttempt] = useState<Attempt | null>(null), [completed, setCompleted] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  async function loadHistory(signal?: AbortSignal) {
    const result = await request<Page<HistoryEntry>>(`${base}/history`, { signal });
    if (!signal?.aborted) { setHistory(result.items); setCursor(result.next_cursor); }
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    void loadHistory(controller.signal).catch((reason) => { if (!controller.signal.aborted) fail(reason); });
    return () => controller.abort();
  }, [base]);
  useEffect(() => {
    if (page !== "S04") return;
    const controller = new AbortController();
    void loadHistory(controller.signal).catch((reason) => { if (!controller.signal.aborted) fail(reason); });
    return () => controller.abort();
  }, [base, page]);
  useEffect(() => {
    if (attemptId ? attempt?.attempt_id === attemptId : !classroomId || attempt?.classroom_id === classroomId) return;
    const controller = new AbortController(); setAttempt(null);
    const operation = attemptId ? request<Attempt>(`${base}/attempts/${attemptId}`, { signal: controller.signal }) : request<Attempt>(`${base}/classrooms/${classroomId}/join`, { method: "POST", csrf: session.csrf_token, signal: controller.signal });
    void operation.then((value) => { if (!controller.signal.aborted) { setAttempt(value); setCompleted(value.state === "submitted"); } }).catch((error) => { if (!controller.signal.aborted) fail(error); });
    return () => controller.abort();
  }, [base, classroomId, attemptId]);
  function fail(reason: unknown) {
    setError(reason instanceof Error ? reason.message : "操作未完成。");
    if (reason instanceof RequestError && reason.status === 401) onExpired(reason);
  }
  async function act(run: (signal: AbortSignal) => Promise<void>) {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setError("");
    try { await run(signal); } catch (reason) { if (!signal.aborted) fail(reason); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  function opened(value: Attempt) { setAttempt(value); setCompleted(value.state === "submitted"); location.hash = `#${value.state === "submitted" ? "S03" : "S02"}?classroom=${value.classroom_id}&attempt=${value.attempt_id}`; }
  async function join(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const code = String(new FormData(event.currentTarget).get("code")).trim().toUpperCase();
    await act(async (signal) => { const value = await request<Attempt>(`${base}/classrooms/join`, { method: "POST", csrf: session.csrf_token, body: { code }, signal }); if (!signal.aborted) opened(value); });
  }
  async function reopen(classroom: string) {
    await act(async (signal) => { const value = await request<Attempt>(`${base}/classrooms/${classroom}/join`, { method: "POST", csrf: session.csrf_token, signal }); if (!signal.aborted) opened(value); });
  }
  async function retry() {
    if (!attempt?.classroom_id || !completed) return;
    await act(async (signal) => { const value = await request<Attempt>(`${base}/classrooms/${attempt.classroom_id}/attempts`, { method: "POST", csrf: session.csrf_token,
      body: { previous_attempt_id: attempt.attempt_id }, signal }); if (!signal.aborted) opened(value); });
  }
  return <>
    {error && <p className="error-box" role="alert">{error}</p>}
    {page === "S01" && <section className="panel section"><h2>进入课堂</h2>{session.kind === "guest" ? <><p>快速身份只适用于本次课堂，跨设备请联系教师。</p><button className="primary" disabled={busy} onClick={() => void reopen(session.classroom_id!)}>打开当前课堂</button></> :
      <form onSubmit={(event) => void join(event)}><label>8 位课堂码<input name="code" required minLength={8} maxLength={8} autoCapitalize="characters" autoComplete="off" spellCheck={false} disabled={busy} /></label><button className="primary wide" disabled={busy}>进入课堂</button></form>}</section>}
    {attempt && ["S02", "S03", "S05"].includes(page) && <section className="panel section"><h2>{page === "S03" ? "提交回执 · " : page === "S05" ? "共享结果 · " : ""}{attempt.title}</h2><p>第 {attempt.number ?? 1} 次尝试</p>
      {attempt.classroom_state !== "open" && <p className="pending-box">课堂已暂停或结束。可以读取原进度和回执，当前不能接收新作答。</p>}
      {page !== "S05" && <RuntimePlayer key={attempt.attempt_id} attempt={attempt} endpoint={`${base}/attempts/${attempt.attempt_id}`} csrf={session.csrf_token}
        actorKey={`${session.kind}.${session.student_id ?? session.guest_id}`} onExpired={onExpired}
        onReceipt={(receipt) => { if (receipt.state === "submitted") { setCompleted(true); if (page === "S02") location.hash = `#S03?classroom=${attempt.classroom_id}&attempt=${attempt.attempt_id}`; } }} />}
      {completed && <button disabled={busy} onClick={() => void retry()}>明确开始新尝试（保留本次提交）</button>}
      {attempt.classroom_id && <SharedSummary key={attempt.classroom_id} base={base} classroomId={attempt.classroom_id} onError={fail} />}
      <a href="#S04">返回我的记录</a></section>}
    {page === "S04" && <section className="panel section"><h2>我的记录</h2>{history.length ? history.map((entry) => <div className="list-row" key={entry.attempt_id}><div><strong>{entry.title}</strong><p>第 {entry.number} 次尝试 · {entry.receipt ? `已提交 · 回执 ${entry.receipt.receiptId}` : `已保存进度，第 ${entry.revision} 版；尚未提交`}</p></div><a href={`#${entry.receipt ? "S03" : "S02"}?classroom=${entry.classroom_id}&attempt=${entry.attempt_id}`}>查看或继续此尝试</a></div>) : <p>暂无已保存或已提交记录。</p>}
      {cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<HistoryEntry>>(`${base}/history?cursor=${cursor}`, { signal }); if (!signal.aborted) { setHistory((items) => [...items, ...page.items]); setCursor(page.next_cursor); } })}>加载更多历史</button>}</section>}
    {["S02", "S03", "S05"].includes(page) && !attempt && <p>正在恢复课堂；无可恢复入口时请从“进入课堂”重新验证课堂码。</p>}
  </>;
}
