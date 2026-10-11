import { useEffect, useRef, useState, type FormEvent } from "react";
import { RequestError, request } from "./http";
import type { Session, Workspace } from "./identity";
import type { ClassEntry, Page } from "./roster";
import { RuntimePlayer, type Attempt } from "./RuntimePlayer";
import { AuthoringView } from "./AuthoringView";
import { ClassroomEntryCard } from "./ClassroomEntryCard";
import { ClassroomResults, type ClassroomSummary, type AnswerRecord } from "./ClassroomResults";
import { ResourcePublication } from "./ResourcePublication";
import { AnalysisView } from "./AnalysisView";
import { ExportAction } from "./TransferView";
import { CollaborationView, ImportedVersions } from "./TeachingTools";

interface Activity { id: string; title: string; draft_revision: number; published_number: number | null; source_resource_number: number | null; source_resource_available: boolean | null; latest_resource_number: number | null }
interface Detail extends Activity { versions: { id: string; number: number }[]; manifest: { objective: string; questions: { id: string; title: string }[] }; grading: { questionId: string; expected: unknown }[] }
interface Classroom { id: string; title: string; code: string; state: string; revision: number; mode: string; data_epoch: number; records_deleted_at: string | null }
type Summary = ClassroomSummary;
type RecordEntry = AnswerRecord;
const states: Record<string, string> = { prepared: "待开课", open: "进行中", paused: "已暂停", ended: "已结束" };

function answerText(value: unknown): string {
  if (value === undefined || value === null) return "未填写";
  if (Array.isArray(value)) return value.map(answerText).join("；");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key === "temperature" ? "温度（℃）" : key === "seconds" ? "溶解时间（秒）" : key}：${answerText(item)}`).join("，");
  return String(value);
}

export function TeachingView({ session, workspace, page = "T01", initialActivityId, initialClassroomId, onError }: { session: Session; workspace: Workspace; page?: string; initialActivityId?: string | null; initialClassroomId?: string | null; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`;
  const [activities, setActivities] = useState<Activity[]>([]), [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [classes, setClasses] = useState<ClassEntry[]>([]), [detail, setDetail] = useState<Detail | null>(null);
  const [trial, setTrial] = useState<Attempt | null>(null), [trialDone, setTrialDone] = useState(false);
  const [contentConfirmed, setContentConfirmed] = useState(false), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [selectedClassroom, setSelectedClassroom] = useState<Classroom | null>(null), [summary, setSummary] = useState<Summary | null>(null);
  const [records, setRecords] = useState<RecordEntry[]>([]), [recordCursor, setRecordCursor] = useState<string | null>(null);
  const [activityCursor, setActivityCursor] = useState<string | null>(null), [classroomCursor, setClassroomCursor] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [recordsState, setRecordsState] = useState("loading");
  const [activityLoading, setActivityLoading] = useState(false);
  const [query, setQuery] = useState(""), [filter, setFilter] = useState("all");
  const activityList = ["T01", "G01"].includes(page), authoringPage = ["T03", "T04"].includes(page), classroomList = page === "T05";
  const classroomPage = ["T06", "T07"].includes(page);
  const lifetime = useRef<AbortController | null>(null);
  const activitySelection = useRef(0);
  const classroomSelection = useRef(0);
  useEffect(() => { setNotice(""); }, [base, page, initialActivityId, initialClassroomId]);
  async function reload(signal?: AbortSignal) {
    const [apps, lessons, roster] = await Promise.all([request<Page<Activity>>(`${base}/activities`, { signal }),
      request<Page<Classroom>>(`${base}/classrooms`, { signal }), request<Page<ClassEntry>>(`${base}/classes`, { signal })]);
    if (!signal?.aborted) { setActivities(apps.items); setActivityCursor(apps.next_cursor); setClassrooms(lessons.items); setClassroomCursor(lessons.next_cursor); setClasses(roster.items.filter((item) => item.active)); }
  }
  useEffect(() => {
    classroomSelection.current++;
    const controller = new AbortController(); lifetime.current = controller;
    void reload(controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base]);
  useEffect(() => {
    if (!initialActivityId) { activitySelection.current++; setDetail(null); setTrial(null); setActivityLoading(false); return; }
    setDetail(null); setTrial(null); setActivityLoading(true);
    const controller = new AbortController();
    void openActivity(initialActivityId, controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); }).finally(() => { if (!controller.signal.aborted) setActivityLoading(false); });
    return () => controller.abort();
  }, [base, initialActivityId, authoringPage]);
  useEffect(() => {
    classroomSelection.current++; setSelectedClassroom(null); setSummary(null); setRecords([]);
    if (!initialClassroomId) return;
    const controller = new AbortController();
    void showClassroom(initialClassroomId, controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); });
    return () => controller.abort();
  }, [base, initialClassroomId]);
  async function act(run: (signal: AbortSignal) => Promise<void>) {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function openActivity(id: string, signal: AbortSignal) {
    const selection = ++activitySelection.current;
    const value = await request<Detail>(`${base}/activities/${id}`, { signal });
    if (!signal.aborted && selection === activitySelection.current) { setDetail(value); setTrial(null); setTrialDone(false); setContentConfirmed(false); }
  }
  async function sample(kind: string) {
    await act(async (signal) => {
      const created = await request<{ id: string }>(`${base}/activities/samples`, { method: "POST", csrf: session.csrf_token, body: { kind }, signal });
      await reload(signal); await openActivity(created.id, signal);
      if (!signal.aborted) location.hash = `#T03?activity=${created.id}`;
    });
  }
  async function startTrial() {
    if (!detail) return;
    const selection = activitySelection.current;
    await act(async (signal) => {
      const value = await request<Attempt>(`${base}/activities/${detail.id}/trials`, { method: "POST", csrf: session.csrf_token, body: { expected_revision: detail.draft_revision }, signal });
      if (!signal.aborted && selection === activitySelection.current) { setTrial(value); setTrialDone(false); setContentConfirmed(false); }
    });
  }
  async function publish() {
    if (!detail || !trial || !trialDone || !contentConfirmed) return;
    const selection = activitySelection.current;
    await act(async (signal) => {
      await request(`${base}/activities/${detail.id}/publish`, { method: "POST", csrf: session.csrf_token, signal,
        body: { expected_revision: detail.draft_revision, trial_id: trial.trial_id, content_confirmed: true } });
      await reload(signal); if (!signal.aborted && selection === activitySelection.current) { await openActivity(detail.id, signal); setNotice("固定版本已发布，可用于准备课堂。后续修改草稿不会改变这个版本。"); }
    });
  }
  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!detail) return;
    const fields = new FormData(event.currentTarget);
    const selection = activitySelection.current;
    await act(async (signal) => {
      const lesson = await request<{ id: string }>(`${base}/classrooms`, { method: "POST", csrf: session.csrf_token, signal,
        body: { title: fields.get("title"), version_id: fields.get("version_id"), class_id: fields.get("class_id") || null, groups: [] } });
      await reload(signal); if (!signal.aborted && selection === activitySelection.current) { setNotice("课堂已准备。点击“开课”后学生才能进入。"); location.hash = `#T06?classroom=${lesson.id}`; }
    });
  }
  async function showClassroom(id: string, signal: AbortSignal) {
    const selection = ++classroomSelection.current;
    const lesson = await request<Classroom>(`${base}/classrooms/${id}`, { signal });
    if (signal.aborted || selection !== classroomSelection.current) return;
    setSelectedClassroom(lesson); setSummary(null); setRecords([]); setRecordsState("loading");
    try {
      const [stats, answers] = await Promise.all([request<Summary>(`${base}/classrooms/${id}/summary`, { signal }), request<Page<RecordEntry>>(`${base}/classrooms/${id}/records`, { signal })]);
      if (!signal.aborted && selection === classroomSelection.current) { setSummary(stats); setRecords(answers.items); setRecordCursor(answers.next_cursor); setRecordsState("ready"); }
    } catch (error) { if (!signal.aborted && selection === classroomSelection.current) setRecordsState(error instanceof RequestError && error.status === 403 ? "forbidden" : "failed"); if (!(error instanceof RequestError && error.status === 403)) throw error; }
  }
  async function transition(lesson: Classroom, state: string) {
    const selection = classroomSelection.current;
    await act(async (signal) => {
      await request(`${base}/classrooms/${lesson.id}/state`, { method: "PATCH", csrf: session.csrf_token, signal, body: { state, expected_revision: lesson.revision } });
      await reload(signal); if (selection === classroomSelection.current && selectedClassroom?.id === lesson.id) await showClassroom(lesson.id, signal);
    });
  }
  return <>
    <div className="page-heading"><div><h1>{authoringPage ? "制作活动" : page === "T02" ? "活动详情" : classroomList ? "我的课堂" : page === "T06" ? "课堂结果" : page === "T07" ? "教学诊断" : "我的活动"}</h1><p>{workspace.name}{detail && authoringPage ? ` · ${detail.title}` : ""}</p></div>{activityList && <a className="primary-link" href="#T03">新建活动</a>}{authoringPage && <a href="#T01">返回我的活动</a>}{classroomPage && <a href="#T05">返回我的课堂</a>}</div>
    {notice && <p className="success-box" role="status">{notice}</p>}
    {loading || activityLoading ? <p role="status">正在加载活动…</p> : <>
      <div className={authoringPage ? "authoring-workspace" : undefined}>
      {authoringPage && <AuthoringView key={detail?.id ?? "new"} session={session} workspace={workspace} activity={detail} activityNames={Object.fromEntries(activities.map((item) => [item.id, item.title]))} onError={onError} onSaved={async (id, callerSignal) => {
        const signal = callerSignal ?? lifetime.current?.signal; if (!signal || signal.aborted) return false;
        const selection = activitySelection.current, route = location.hash;
        await reload(signal);
        if (signal.aborted || selection !== activitySelection.current || route !== location.hash) return false;
        const value = await request<Detail>(`${base}/activities/${id}`, { signal });
        if (signal.aborted || selection !== activitySelection.current || route !== location.hash) return false;
        activitySelection.current++; setDetail(value); setTrial(null); setTrialDone(false); setContentConfirmed(false);
        location.hash = `#T03?activity=${id}`;
        return true;
      }} />}
      {authoringPage && !detail && <section className="panel"><div className="roster-tools"><h2>从活动样板开始</h2><div className="row-actions">
        <button disabled={busy} onClick={() => void sample("quiz")}>新建随堂测验</button><button disabled={busy} onClick={() => void sample("words")}>新建词汇闯关</button><button disabled={busy} onClick={() => void sample("lab")}>新建实验探究</button></div></div>
        <p>也可以在制作器描述教学想法或导入已有页面。</p></section>}
      {activityList && <><section className="panel roster-tools"><label>搜索当前已加载活动<input value={query} onChange={(event) => setQuery(event.target.value)} /></label><label>发布状态<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部</option><option value="draft">未发布</option><option value="published">有固定版本</option></select></label><button onClick={() => { setQuery(""); setFilter("all"); }}>清空筛选</button></section><section className="panel table-scroll section"><table><thead><tr><th>活动名称</th><th>草稿</th><th>发布版本</th><th>操作</th></tr></thead><tbody>
        {activities.filter((item) => item.title.includes(query) && (filter === "all" || (filter === "published") === Boolean(item.published_number))).map((item) => <tr key={item.id}><td>{item.title}{item.source_resource_number && <p className="field-help">来自校内资源 v{item.source_resource_number} · {item.source_resource_available === false ? "源已撤回，副本保留" : (item.latest_resource_number ?? 0) > item.source_resource_number ? "源有新版，当前副本独立保留" : "独立副本"}</p>}</td><td>第 {item.draft_revision} 版</td><td>{item.published_number ? `v${item.published_number}` : "未发布"}</td><td><a href={`#T02?activity=${item.id}`}>打开活动</a> · <a href={`#T03?activity=${item.id}`}>继续制作</a></td></tr>)}
        {!activities.some((item) => item.title.includes(query) && (filter === "all" || (filter === "published") === Boolean(item.published_number))) && <tr><td colSpan={4} className="empty-state">{activities.length ? <>没有符合条件的活动。<button onClick={() => { setQuery(""); setFilter("all"); }}>清空筛选</button></> : <>还没有活动。<a href="#T03">新建活动</a></>}</td></tr>}</tbody></table>
        {activityCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Activity>>(`${base}/activities?cursor=${activityCursor}`, { signal }); if (!signal.aborted) { setActivities((items) => [...items, ...page.items]); setActivityCursor(page.next_cursor); } })}>加载更多活动</button>}</section></>}
      {detail && (page === "T02" || authoringPage) && <section className={`panel${authoringPage ? " activity-preview" : " section"}`}><div className="roster-tools"><div><h2>{authoringPage ? "预览与试做" : detail.title}</h2><p>{detail.manifest.objective}</p></div>{!authoringPage && <a href="#T01">返回我的活动</a>}</div>
        {page === "T02" && <><a className="primary-link" href={`#T03?activity=${detail.id}`}>继续制作与试做</a><ImportedVersions session={session} workspace={workspace} onError={onError} activityId={detail.id} revision={detail.draft_revision} /><CollaborationView session={session} workspace={workspace} onError={onError} objectId={detail.id} kind="activity" /></>}
        {detail.versions.length > 0 && <ExportAction session={session} workspace={workspace} onError={onError} objectId={detail.id} kind="resource" />}
        {workspace.kind === "campus" && detail.versions.length > 0 && <ResourcePublication key={detail.id} base={base} activity={detail} session={session} onError={onError} />}
        {!authoringPage && <details><summary>题目与参考答案</summary><ol>{detail.manifest.questions.map((question) => <li key={question.id}>{question.title}<p>参考答案：{detail.grading.some((rule) => rule.questionId === question.id) ? answerText(detail.grading.find((rule) => rule.questionId === question.id)!.expected) : "开放回答"}</p></li>)}</ol></details>}
        <div className="row-actions"><button className={trial ? "" : "primary"} disabled={busy} onClick={() => void startTrial()}>{trial ? "重新试做" : "预览并试做"}</button>
          <button className={trialDone && contentConfirmed ? "primary" : ""} disabled={busy || !trialDone || !contentConfirmed} onClick={() => void publish()}>发布活动</button></div>
        {!trial && <div className="preview-empty"><p>打开活动预览，完成一次作答后发布。</p></div>}
        {trial && <><RuntimePlayer key={trial.attempt_id} attempt={trial} endpoint={`${base}/attempts/${trial.attempt_id}`} csrf={session.csrf_token} actorKey={`staff.${session.account_id}`}
          onReceipt={(receipt) => { if (receipt.state === "submitted") setTrialDone(true); }} onExpired={onError} />
          <label className="checkbox-label"><input type="checkbox" checked={contentConfirmed} disabled={!trialDone || busy} onChange={(event) => setContentConfirmed(event.target.checked)} />题目和参考答案已核对，可以用于课堂</label></>}
        {detail.versions.length > 0 && <form className="compact-form section" onSubmit={(event) => void prepare(event)}><h2>准备课堂</h2>
          <label>课堂名称<input name="title" required maxLength={80} defaultValue={detail.title} disabled={busy} /></label>
          <label>固定版本<select name="version_id" disabled={busy}>{detail.versions.map((version) => <option key={version.id} value={version.id}>v{version.number}</option>)}</select></label>
          <label>参与范围<select name="class_id" disabled={busy}><option value="">快速课堂（无固定名册）</option>{classes.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>
          <p className="field-help">班级课堂按开课时名册计算完成率；快速课堂只显示参与和提交人数。</p><button className="primary" disabled={busy}>准备课堂</button></form>}
      </section>}
      {classroomList && <section className="panel table-scroll section"><table><thead><tr><th>课堂</th><th>状态</th><th>课堂码</th><th>操作</th></tr></thead><tbody>
        {classrooms.map((lesson) => <tr key={lesson.id}><td>{lesson.title}</td><td>{states[lesson.state]}</td><td><code>{lesson.code}</code></td><td><div className="row-actions">
          {lesson.state === "prepared" && <button disabled={busy} onClick={() => void transition(lesson, "open")}>开课</button>}
          {lesson.state === "open" && <button disabled={busy} onClick={() => void transition(lesson, "paused")}>暂停</button>}
          {lesson.state === "paused" && <button disabled={busy} onClick={() => void transition(lesson, "open")}>继续课堂</button>}
          {lesson.state !== "ended" && <button disabled={busy} onClick={() => void transition(lesson, "ended")}>结束课堂</button>}
          {lesson.records_deleted_at ? <span>资料已删除</span> : <a href={`#T06?classroom=${lesson.id}`}>查看课堂与结果</a>}</div>{!lesson.records_deleted_at && <details><summary>分发给学生</summary><ClassroomEntryCard title={lesson.title} code={lesson.code} /></details>}</td></tr>)}
        {!classrooms.length && <tr><td colSpan={4}>尚无课堂，发布活动后准备课堂。</td></tr>}</tbody></table>
        {classroomCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Classroom>>(`${base}/classrooms?cursor=${classroomCursor}`, { signal }); if (!signal.aborted) { setClassrooms((items) => [...items, ...page.items]); setClassroomCursor(page.next_cursor); } })}>加载更多课堂</button>}</section>}
      {selectedClassroom && page === "T06" && <section className="panel section"><div className="roster-tools"><h2>{selectedClassroom.title} · {states[selectedClassroom.state]}</h2><button disabled={busy} onClick={() => void act((signal) => showClassroom(selectedClassroom.id, signal))}>刷新结果</button></div>
        <div className="row-actions">{selectedClassroom.state !== "ended" && <><button disabled={busy} onClick={() => void transition(selectedClassroom, selectedClassroom.state === "open" ? "paused" : "open")}>{selectedClassroom.state === "open" ? "暂停接收" : "开放接收"}</button><button disabled={busy} onClick={() => void transition(selectedClassroom, "ended")}>结束课堂</button></>}<a href={`#T07?classroom=${selectedClassroom.id}`}>教学诊断与共享</a><ExportAction session={session} workspace={workspace} onError={onError} objectId={selectedClassroom.id} kind="archive" epoch={selectedClassroom.data_epoch} /></div>
        <details><summary>分发给学生</summary><ClassroomEntryCard title={selectedClassroom.title} code={selectedClassroom.code} /></details>
        {summary ? <ClassroomResults endpoint={`${base}/classrooms/${selectedClassroom.id}`} summary={summary} mode={selectedClassroom.mode} state={selectedClassroom.state} records={records} cursor={recordCursor} busy={busy} onError={onError} onMore={() => { const selection = classroomSelection.current; void act(async (signal) => { const page = await request<Page<RecordEntry>>(`${base}/classrooms/${selectedClassroom.id}/records?cursor=${recordCursor}`, { signal }); if (!signal.aborted && selection === classroomSelection.current) { setRecords((items) => [...items, ...page.items]); setRecordCursor(page.next_cursor); } }); }} /> : <p>{recordsState === "forbidden" ? "你没有查看此课堂学生答案的权限。" : recordsState === "failed" ? "课堂结果暂时无法读取，请刷新重试。" : "正在读取课堂结果…"}</p>}
        <CollaborationView session={session} workspace={workspace} onError={onError} objectId={selectedClassroom.id} kind="classroom" />
        {selectedClassroom.state === "ended" && <details><summary>删除此课堂资料</summary><p>正文、进度、图片、报告和导出将失效；已经下载的副本与备份无法召回。</p><form onSubmit={(event) => { event.preventDefault(); void act(async (signal) => { await request(`${base}/classrooms/${selectedClassroom.id}/records`, { method: "DELETE", csrf: session.csrf_token, signal, body: { confirmed: true, expected_data_epoch: selectedClassroom.data_epoch } }); if (!signal.aborted) { setSelectedClassroom(null); setSummary(null); setRecords([]); location.hash = "#T05"; await reload(signal); setNotice("课堂资料已删除，旧图片、报告与导出不可读。"); } }); }}><label className="checkbox-label"><input type="checkbox" required disabled={busy} />确认删除此课堂全部资料</label><button disabled={busy}>确认删除课堂资料</button></form></details>}</section>}
      {selectedClassroom && summary && page === "T07" && <section className="panel section"><a href={`#T06?classroom=${selectedClassroom.id}`}>返回课堂与原始记录</a><AnalysisView key={selectedClassroom.id} session={session} workspace={workspace} classroomId={selectedClassroom.id} onError={onError} /></section>}
      {selectedClassroom && !summary && page === "T07" && <p>{recordsState === "forbidden" ? "当前没有查看学生记录的授权，不能打开教学诊断。" : recordsState === "failed" ? "课堂资料读取失败，请刷新重试。" : "正在读取课堂资料…"}</p>}
      {classroomPage && !initialClassroomId && <section className="panel"><p>请先从我的课堂选择一次开展。</p><a href="#T05">选择课堂</a></section>}
      </div>
    </>}
  </>;
}
