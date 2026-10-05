import { useEffect, useRef, useState, type FormEvent } from "react";
import { request } from "./http";
import type { Session, Workspace } from "./identity";
import type { ClassEntry, Page } from "./roster";
import { RuntimePlayer, type Attempt } from "./RuntimePlayer";
import { AuthoringView } from "./AuthoringView";

interface Activity { id: string; title: string; draft_revision: number; published_number: number | null }
interface Detail extends Activity { versions: { id: string; number: number }[]; manifest: { objective: string; questions: { id: string; title: string }[] }; grading: { questionId: string; expected: unknown }[] }
interface Classroom { id: string; title: string; code: string; state: string; revision: number; mode: string }
interface Summary { planned_count: number | null; planned_completed: number; extra_completed: number; completed: number; completion_rate: number | null;
  participated: number; in_progress: number; not_entered: number | null; not_submitted: number; attempt_count: number; submission_count: number;
  questions: { id: string; title: string; kind: string; data_path: string; graded: boolean; graded_count: number; answered_count: number; unanswered_count: number; accuracy: number | null }[]; rule: string }
interface RecordEntry { attempt_id: string; display_name: string; number: number; group_name: string | null; data: unknown; receipt: { receiptId: string } }
const states: Record<string, string> = { prepared: "待开课", open: "进行中", paused: "已暂停", ended: "已结束" };

function answerAt(data: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined, data);
}
function answerText(value: unknown): string {
  if (value === undefined || value === null) return "未填写";
  if (Array.isArray(value)) return value.map(answerText).join("；");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key === "temperature" ? "温度（℃）" : key === "seconds" ? "溶解时间（秒）" : key}：${answerText(item)}`).join("，");
  return String(value);
}

export function TeachingView({ session, workspace, onError }: { session: Session; workspace: Workspace; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`;
  const [activities, setActivities] = useState<Activity[]>([]), [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [classes, setClasses] = useState<ClassEntry[]>([]), [detail, setDetail] = useState<Detail | null>(null);
  const [trial, setTrial] = useState<Attempt | null>(null), [trialDone, setTrialDone] = useState(false);
  const [contentConfirmed, setContentConfirmed] = useState(false), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [selectedClassroom, setSelectedClassroom] = useState<Classroom | null>(null), [summary, setSummary] = useState<Summary | null>(null);
  const [records, setRecords] = useState<RecordEntry[]>([]), [recordCursor, setRecordCursor] = useState<string | null>(null);
  const [activityCursor, setActivityCursor] = useState<string | null>(null), [classroomCursor, setClassroomCursor] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  async function reload(signal?: AbortSignal) {
    const [apps, lessons, roster] = await Promise.all([request<Page<Activity>>(`${base}/activities`, { signal }),
      request<Page<Classroom>>(`${base}/classrooms`, { signal }), request<Page<ClassEntry>>(`${base}/classes`, { signal })]);
    if (!signal?.aborted) { setActivities(apps.items); setActivityCursor(apps.next_cursor); setClassrooms(lessons.items); setClassroomCursor(lessons.next_cursor); setClasses(roster.items.filter((item) => item.active)); }
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    void reload(controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base]);
  async function act(run: (signal: AbortSignal) => Promise<void>) {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function openActivity(id: string, signal: AbortSignal) {
    const value = await request<Detail>(`${base}/activities/${id}`, { signal });
    if (!signal.aborted) { setDetail(value); setTrial(null); setTrialDone(false); setContentConfirmed(false); }
  }
  async function sample(kind: string) {
    await act(async (signal) => {
      const created = await request<{ id: string }>(`${base}/activities/samples`, { method: "POST", csrf: session.csrf_token, body: { kind }, signal });
      await reload(signal); await openActivity(created.id, signal);
    });
  }
  async function startTrial() {
    if (!detail) return;
    await act(async (signal) => {
      const value = await request<Attempt>(`${base}/activities/${detail.id}/trials`, { method: "POST", csrf: session.csrf_token, body: { expected_revision: detail.draft_revision }, signal });
      if (!signal.aborted) { setTrial(value); setTrialDone(false); setContentConfirmed(false); }
    });
  }
  async function publish() {
    if (!detail || !trial || !trialDone || !contentConfirmed) return;
    await act(async (signal) => {
      await request(`${base}/activities/${detail.id}/publish`, { method: "POST", csrf: session.csrf_token, signal,
        body: { expected_revision: detail.draft_revision, trial_id: trial.trial_id, content_confirmed: true } });
      await reload(signal); await openActivity(detail.id, signal); if (!signal.aborted) setNotice("固定版本已发布，可用于准备课堂。后续修改草稿不会改变这个版本。");
    });
  }
  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!detail) return;
    const fields = new FormData(event.currentTarget);
    await act(async (signal) => {
      await request(`${base}/classrooms`, { method: "POST", csrf: session.csrf_token, signal,
        body: { title: fields.get("title"), version_id: fields.get("version_id"), class_id: fields.get("class_id") || null, groups: [] } });
      await reload(signal); if (!signal.aborted) setNotice("课堂已准备。点击“开课”后学生才能进入。");
    });
  }
  async function showClassroom(id: string, signal: AbortSignal) {
    const [lesson, stats, answers] = await Promise.all([request<Classroom>(`${base}/classrooms/${id}`, { signal }),
      request<Summary>(`${base}/classrooms/${id}/summary`, { signal }), request<Page<RecordEntry>>(`${base}/classrooms/${id}/records`, { signal })]);
    if (!signal.aborted) { setSelectedClassroom(lesson); setSummary(stats); setRecords(answers.items); setRecordCursor(answers.next_cursor); }
  }
  async function transition(lesson: Classroom, state: string) {
    await act(async (signal) => {
      await request(`${base}/classrooms/${lesson.id}/state`, { method: "PATCH", csrf: session.csrf_token, signal, body: { state, expected_revision: lesson.revision } });
      await reload(signal); if (selectedClassroom?.id === lesson.id) await showClassroom(lesson.id, signal);
    });
  }
  return <>
    <div className="page-heading"><div><h1>我的活动与课堂</h1><p>{workspace.name} · 制作、试做、发布，再组织课堂</p></div></div>
    {notice && <p className="success-box" role="status">{notice}</p>}
    {loading ? <p role="status">正在加载活动…</p> : <>
      <AuthoringView session={session} workspace={workspace} activity={detail} onError={onError} onSaved={async (id) => { await act(async (signal) => { await reload(signal); await openActivity(id, signal); }); }} />
      <section className="panel"><div className="roster-tools"><h2>从活动样板开始</h2><div className="row-actions">
        <button disabled={busy} onClick={() => void sample("quiz")}>新建随堂测验</button><button disabled={busy} onClick={() => void sample("words")}>新建词汇闯关</button><button disabled={busy} onClick={() => void sample("lab")}>新建实验探究</button></div></div>
        <p>样板接入真实课堂数据。打开活动后，可在上方描述修改要求或手动修改页面。</p></section>
      <section className="panel table-scroll section"><table><thead><tr><th>活动名称</th><th>草稿</th><th>发布版本</th><th>操作</th></tr></thead><tbody>
        {activities.map((item) => <tr key={item.id}><td>{item.title}</td><td>第 {item.draft_revision} 版</td><td>{item.published_number ? `v${item.published_number}` : "未发布"}</td><td><button disabled={busy} onClick={() => void act((signal) => openActivity(item.id, signal))}>打开活动</button></td></tr>)}
        {!activities.length && <tr><td colSpan={4}>尚无活动，请选择上方样板。</td></tr>}</tbody></table>
        {activityCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Activity>>(`${base}/activities?cursor=${activityCursor}`, { signal }); if (!signal.aborted) { setActivities((items) => [...items, ...page.items]); setActivityCursor(page.next_cursor); } })}>加载更多活动</button>}</section>
      {detail && <section className="panel section"><div className="roster-tools"><div><h2>{detail.title}</h2><p>{detail.manifest.objective}</p></div><button disabled={busy} onClick={() => { setDetail(null); setTrial(null); }}>关闭活动</button></div>
        <p>先在隔离页面真实保存、读取并提交一次，再确认教学内容，发布固定版本。</p>
        <details><summary>查看题目与答案标准</summary><ol>{detail.manifest.questions.map((question) => <li key={question.id}>{question.title}<p>答案标准：{detail.grading.some((rule) => rule.questionId === question.id) ? answerText(detail.grading.find((rule) => rule.questionId === question.id)!.expected) : "开放回答，不自动评分"}</p></li>)}</ol></details>
        <div className="row-actions"><button className="primary" disabled={busy} onClick={() => void startTrial()}>开始试做当前草稿</button>
          <button disabled={busy || !trialDone || !contentConfirmed} onClick={() => void publish()}>发布固定版本</button></div>
        {trial && <><RuntimePlayer key={trial.attempt_id} attempt={trial} endpoint={`${base}/attempts/${trial.attempt_id}`} csrf={session.csrf_token} actorKey={`staff.${session.account_id}`}
          onReceipt={(receipt) => { if (receipt.state === "submitted") setTrialDone(true); }} onExpired={onError} />
          <label className="checkbox-label"><input type="checkbox" checked={contentConfirmed} disabled={!trialDone || busy} onChange={(event) => setContentConfirmed(event.target.checked)} />已检查题目、答案标准和数据收集内容，确认可用于课堂</label></>}
        {detail.versions.length > 0 && <form className="compact-form section" onSubmit={(event) => void prepare(event)}><h2>准备课堂</h2>
          <label>课堂名称<input name="title" required maxLength={80} defaultValue={detail.title} disabled={busy} /></label>
          <label>固定版本<select name="version_id" disabled={busy}>{detail.versions.map((version) => <option key={version.id} value={version.id}>v{version.number}</option>)}</select></label>
          <label>参与范围<select name="class_id" disabled={busy}><option value="">快速课堂（无固定名册）</option>{classes.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>
          <p className="field-help">班级课堂按开课时名册计算完成率；快速课堂只显示参与和提交人数。</p><button className="primary" disabled={busy}>准备课堂</button></form>}
      </section>}
      <section className="panel table-scroll section"><table><thead><tr><th>课堂</th><th>状态</th><th>课堂码</th><th>操作</th></tr></thead><tbody>
        {classrooms.map((lesson) => <tr key={lesson.id}><td>{lesson.title}</td><td>{states[lesson.state]}</td><td><code>{lesson.code}</code></td><td><div className="row-actions">
          {lesson.state === "prepared" && <button disabled={busy} onClick={() => void transition(lesson, "open")}>开课</button>}
          {lesson.state === "open" && <button disabled={busy} onClick={() => void transition(lesson, "paused")}>暂停</button>}
          {lesson.state === "paused" && <button disabled={busy} onClick={() => void transition(lesson, "open")}>继续课堂</button>}
          {lesson.state !== "ended" && <button disabled={busy} onClick={() => void transition(lesson, "ended")}>结束课堂</button>}
          <button disabled={busy} onClick={() => void act((signal) => showClassroom(lesson.id, signal))}>查看结果</button></div></td></tr>)}
        {!classrooms.length && <tr><td colSpan={4}>尚无课堂，发布活动后准备课堂。</td></tr>}</tbody></table>
        {classroomCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Classroom>>(`${base}/classrooms?cursor=${classroomCursor}`, { signal }); if (!signal.aborted) { setClassrooms((items) => [...items, ...page.items]); setClassroomCursor(page.next_cursor); } })}>加载更多课堂</button>}</section>
      {selectedClassroom && summary && <section className="panel section"><div className="roster-tools"><h2>{selectedClassroom.title} · 课堂结果</h2><button disabled={busy} onClick={() => void act((signal) => showClassroom(selectedClassroom.id, signal))}>刷新结果</button></div>
        <div className="metric-strip"><span>已进入 {summary.participated}</span><span>当前尝试进行中 {summary.in_progress}</span><span>未曾提交 {summary.not_submitted}</span><span>计划名单未进入 {summary.not_entered ?? "未知"}</span><span>已完成 {summary.completed}</span><span>计划完成 {summary.planned_completed} / {summary.planned_count ?? "未知"}</span><span>额外参与完成 {summary.extra_completed}</span><span>完成率 {summary.completion_rate === null ? "暂无固定分母" : `${Math.round(summary.completion_rate * 100)}%`}</span></div>
        <p className="field-help">{summary.rule} 共 {summary.attempt_count} 次尝试，{summary.submission_count} 份最终提交。</p><ul>{summary.questions.map((question) => <li key={question.id}>{question.title}：已答 {question.answered_count}，未答 {question.unanswered_count}；{question.accuracy === null ? "未配置答案标准 / 暂无可评分提交" : `正确率 ${Math.round(question.accuracy * 100)}%（${question.graded_count} 份）`}</li>)}</ul>
        <h2>最终提交记录</h2>{records.map((entry) => <details key={entry.attempt_id}><summary>{entry.display_name}{entry.group_name ? ` · ${entry.group_name}` : ""} · 第 {entry.number} 次尝试</summary><p>回执：{entry.receipt.receiptId}</p><dl>{summary.questions.map((question) => {
          const answer = answerAt(entry.data, question.data_path);
          return <div key={question.id}><dt>{question.title}</dt><dd className="answer-data">{question.kind === "image" && Array.isArray(answer) ? answer.map((file: unknown) => typeof file === "string" && /^[a-f0-9-]{36}$/i.test(file) ? <a key={file} href={`${base}/classrooms/${selectedClassroom.id}/files/${file}`} target="_blank" rel="noreferrer"><img className="evidence-image" src={`${base}/classrooms/${selectedClassroom.id}/files/${file}`} alt={question.title} /></a> : null) : answerText(answer)}</dd></div>;
        })}</dl></details>)}
        {!records.length && <p>暂无最终提交；保存进度不计为已完成。</p>}
        {recordCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<RecordEntry>>(`${base}/classrooms/${selectedClassroom.id}/records?cursor=${recordCursor}`, { signal }); if (!signal.aborted) { setRecords((items) => [...items, ...page.items]); setRecordCursor(page.next_cursor); } })}>加载更多记录</button>}</section>}
    </>}
  </>;
}
