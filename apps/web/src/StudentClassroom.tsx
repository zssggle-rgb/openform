import { useEffect, useRef, useState, type FormEvent } from "react";
import { RequestError, request } from "./http";
import type { Page } from "./roster";
import { RuntimePlayer, type Attempt } from "./RuntimePlayer";

export interface ParticipantSession {
  kind: "student" | "guest"; workspace_id: string; workspace_name: string; display_name: string; csrf_token: string;
  student_id?: string; guest_id?: string; classroom_id?: string; reference?: string;
}
interface HistoryEntry { attempt_id: string; classroom_id: string; title: string; number: number; receipt: { receiptId: string } }

export function StudentClassroom({ session, onExpired }: { session: ParticipantSession; onExpired: (error: unknown) => void }) {
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
  function opened(value: Attempt) { setAttempt(value); setCompleted(value.state === "submitted"); }
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
    <section className="panel section"><h2>进入课堂</h2>{session.kind === "guest" ? <><p>快速身份只适用于本次课堂，跨设备请联系教师。</p><button className="primary" disabled={busy} onClick={() => void reopen(session.classroom_id!)}>打开当前课堂</button></> :
      <form onSubmit={(event) => void join(event)}><label>8 位课堂码<input name="code" required minLength={8} maxLength={8} autoCapitalize="characters" autoComplete="off" spellCheck={false} disabled={busy} /></label><button className="primary wide" disabled={busy}>进入课堂</button></form>}</section>
    {attempt && <section className="panel section"><h2>{attempt.title}</h2><p>第 {attempt.number ?? 1} 次尝试</p>
      {attempt.classroom_state !== "open" && <p className="pending-box">课堂已暂停或结束。可以读取原进度和回执，当前不能接收新作答。</p>}
      <RuntimePlayer key={attempt.attempt_id} attempt={attempt} endpoint={`${base}/attempts/${attempt.attempt_id}`} csrf={session.csrf_token}
        actorKey={`${session.kind}.${session.student_id ?? session.guest_id}`} onExpired={onExpired}
        onReceipt={(receipt) => { if (receipt.state === "submitted") { setCompleted(true); void loadHistory(lifetime.current?.signal).catch(fail); } }} />
      {completed && <button disabled={busy} onClick={() => void retry()}>明确开始新尝试（保留本次提交）</button>}
      <button disabled={busy} onClick={() => setAttempt(null)}>收起课堂</button></section>}
    <section className="panel section"><h2>我的提交历史</h2>{history.length ? history.map((entry) => <div className="list-row" key={entry.attempt_id}><div><strong>{entry.title}</strong><p>第 {entry.number} 次尝试 · 回执 {entry.receipt.receiptId}</p></div><button disabled={busy} onClick={() => void reopen(entry.classroom_id)}>查看课堂与回执</button></div>) : <p>暂无最终提交。保存进度不会显示为已完成。</p>}
      {cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<HistoryEntry>>(`${base}/history?cursor=${cursor}`, { signal }); if (!signal.aborted) { setHistory((items) => [...items, ...page.items]); setCursor(page.next_cursor); } })}>加载更多历史</button>}</section>
  </>;
}
