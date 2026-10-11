import { useEffect, useRef, useState } from "react";
import { AnswerDisplay, type QuestionDisplay } from "./AnswerDisplay";
import { request } from "./http";
import type { Page } from "./roster";

export interface ClassroomSummary {
  planned_count: number | null; planned_completed: number; completed: number; completion_rate: number | null;
  participated: number; not_entered: number | null; not_submitted: number;
  questions: (QuestionDisplay & { answered_count: number; unanswered_count: number; accuracy: number | null; graded_count: number })[];
}
export interface AnswerRecord { attempt_id: string; display_name: string; number: number; group_name: string | null; data: unknown; created_at: string }
interface Participant { id: string; display_name: string; group_name: string | null; status: string; current_state: string | null; latest_completed_attempt_id: string | null; submitted_at: string | null }
const statusLabels: Record<string, string> = { not_entered: "未进入", entered: "作答中", saved: "已保存，未提交", submitted: "已提交" };

export function ClassroomResults({ endpoint, summary, mode, state, records, cursor, busy, onMore, onError }: { endpoint: string; summary: ClassroomSummary; mode: string; state: string; records: AnswerRecord[]; cursor: string | null; busy: boolean; onMore: () => void; onError: (error: unknown) => void }) {
  const [people, setPeople] = useState<Participant[]>([]), [next, setNext] = useState<string | null>(null), [filter, setFilter] = useState("all");
  const [readState, setReadState] = useState("loading"), [retry, setRetry] = useState(0), [loadingMore, setLoadingMore] = useState(false);
  const [answer, setAnswer] = useState<AnswerRecord | null>(null), [answerState, setAnswerState] = useState("idle");
  const lifetime = useRef<AbortController | null>(null), selected = useRef(0);
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller; selected.current++;
    setPeople([]); setNext(null); setAnswer(null); setAnswerState("idle"); setReadState("loading"); setLoadingMore(false);
    void request<Page<Participant>>(`${endpoint}/participants?status=${filter}`, { signal: controller.signal }).then((page) => {
      if (!controller.signal.aborted) { setPeople(page.items); setNext(page.next_cursor); setReadState("ready"); }
    }).catch((error) => { if (!controller.signal.aborted) { setReadState("failed"); onError(error); } });
    return () => controller.abort();
  }, [endpoint, filter, summary, retry]);
  async function more() {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted || !next) return;
    setLoadingMore(true);
    try { const page = await request<Page<Participant>>(`${endpoint}/participants?status=${filter}&cursor=${encodeURIComponent(next)}`, { signal }); if (!signal.aborted) { setPeople((items) => [...items, ...page.items]); setNext(page.next_cursor); } }
    catch (error) { if (!signal.aborted) onError(error); } finally { if (!signal.aborted) setLoadingMore(false); }
  }
  async function openAnswer(id: string) {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    const selection = ++selected.current; setAnswer(null); setAnswerState("loading");
    try { const page = await request<Page<AnswerRecord>>(`${endpoint}/records?attempt_id=${id}`, { signal }); if (!signal.aborted && selection === selected.current) { setAnswer(page.items[0] ?? null); setAnswerState(page.items.length ? "ready" : "missing"); } }
    catch (error) { if (!signal.aborted && selection === selected.current) { setAnswerState("failed"); onError(error); } }
  }
  function answers(entry: AnswerRecord) {
    return <article className="answer-record"><h3>{entry.display_name}{entry.group_name ? ` · ${entry.group_name}` : ""}</h3><p className="field-help">提交于 {new Date(entry.created_at).toLocaleString()} · 第 {entry.number} 次作答</p>{summary.questions.map((question) => <AnswerDisplay key={question.id} question={question} data={entry.data} fileBase={`${endpoint}/files`} />)}</article>;
  }
  return <>
    <div className="metric-strip"><span>参与 {summary.participated} 人</span><span>已交 {summary.completed} 人</span><span>已进入未交 {summary.not_submitted} 人</span>{mode !== "quick" && state !== "prepared" && <><span>未进入 {summary.not_entered} {mode === "group" ? "组" : "人"}</span>{summary.completion_rate !== null && <span>{mode === "group" ? "小组" : "班级"}完成率 {Math.round(summary.completion_rate * 100)}%</span>}</>}</div>
    <h2>学生作答</h2><label className="results-filter">查看<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部学生</option><option value="not_submitted">未交</option><option value="submitted">已交</option></select></label>
    {readState === "loading" ? <p role="status">正在读取学生作答…</p> : readState === "failed" ? <div className="error-box"><p>学生作答暂时无法读取。</p><button onClick={() => setRetry((value) => value + 1)}>重新读取</button></div> : <div className="table-scroll"><table><thead><tr><th>学生</th><th>作答情况</th><th>提交时间</th><th>答案</th></tr></thead><tbody>{people.map((person) => <tr key={person.id}><td>{person.display_name}{person.group_name && <p className="field-help">{person.group_name}</p>}</td><td>{statusLabels[person.status]}{person.status === "submitted" && person.current_state === "in_progress" && <p className="field-help">再次作答中</p>}</td><td>{person.submitted_at ? new Date(person.submitted_at).toLocaleString() : "—"}</td><td>{person.latest_completed_attempt_id && <button disabled={answerState === "loading"} onClick={() => void openAnswer(person.latest_completed_attempt_id!)}>查看答案</button>}</td></tr>)}{!people.length && <tr><td colSpan={4}>{state === "prepared" ? "开课后可查看学生作答。" : filter === "all" ? "还没有学生进入。" : "没有符合条件的学生。"}</td></tr>}</tbody></table>{next && <button disabled={loadingMore} onClick={() => void more()}>加载更多学生</button>}</div>}
    {answerState === "loading" && <p role="status">正在打开答案…</p>}{answerState === "failed" && <p className="error-box">答案暂时无法打开，请重新选择学生。</p>}{answerState === "missing" && <p>这份答案已无法查看，请刷新课堂结果。</p>}{answer && answers(answer)}
    <h2>题目情况</h2><div className="question-results">{summary.questions.map((question) => <article key={question.id}><h3>{question.title}</h3><p>已答 {question.answered_count} 人 · 未答 {question.unanswered_count} 人</p>{question.accuracy !== null ? <p>正确率 {Math.round(question.accuracy * 100)}%</p> : !question.has_standard ? <p className="field-help">开放回答</p> : <p className="field-help">暂无已交答案</p>}</article>)}</div>
    <details className="section"><summary>全部已交答案</summary>{records.map((entry) => <details key={entry.attempt_id}><summary>{entry.display_name} · {new Date(entry.created_at).toLocaleString()} · 第 {entry.number} 次作答</summary>{answers(entry)}</details>)}{!records.length && <p>暂无已交答案。</p>}{cursor && <button disabled={busy} onClick={onMore}>加载更多答案</button>}</details>
  </>;
}
