import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { RequestError, request } from "./http";
import type { Member, Session, Workspace } from "./identity";
import type { Assignment, ClassEntry, Page, StudentEntry } from "./roster";

const messageOf = (reason: unknown) => reason instanceof Error ? reason.message : "操作未完成，请重试。";

function usePage<T>(url: string, refresh: number, onError: (reason: unknown) => void) {
  const [page, setPage] = useState<Page<T>>({ items: [], next_cursor: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const report = useRef(onError); report.current = onError;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setPage({ items: [], next_cursor: null });
    void request<Page<T>>(url, { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setPage(value); })
      .catch((reason) => { if (!controller.signal.aborted) { setError(messageOf(reason)); report.current(reason); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [url, refresh]);
  return { ...page, loading, error };
}

function Pagination({ cursor, next, previous, onChange, busy }: { cursor: string | null; next: string | null; previous: (string | null)[]; onChange: (cursor: string | null, previous: (string | null)[]) => void; busy: boolean }) {
  return <div className="pagination"><span>每页最多 50 条</span>
    <button type="button" disabled={busy || previous.length === 0} onClick={() => onChange(previous.at(-1) ?? null, previous.slice(0, -1))}>上一页</button>
    <button type="button" disabled={busy || !next} onClick={() => onChange(next, [...previous, cursor])}>下一页</button></div>;
}

export function RosterView({ session, workspace, section, classId, onError }: { session: Session; workspace: Workspace; section: "classes" | "students" | "detail"; classId: string | null; onError: (reason: unknown) => void }) {
  const base = `/api/workspaces/${encodeURIComponent(workspace.id)}`;
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [conflicts, setConflicts] = useState(0);
  const [classCursor, setClassCursor] = useState<string | null>(null);
  const [classPrevious, setClassPrevious] = useState<(string | null)[]>([]);
  const [editingClass, setEditingClass] = useState<ClassEntry | "new" | null>(null);
  const [selectedClass, setSelectedClass] = useState(classId ?? "");
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => { const controller = new AbortController(); lifetime.current = controller; return () => controller.abort(); }, []);
  const classes = usePage<ClassEntry>(`${base}/classes${classCursor ? `?cursor=${encodeURIComponent(classCursor)}` : ""}`, refresh, onError);
  async function mutate<T>(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown): Promise<{ value: T } | null> {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return null;
    setBusy(true); setNotice("");
    try {
      const value = await request<T>(path, { method, body, csrf: session.csrf_token, signal });
      if (signal.aborted) return null;
      setRefresh((count) => count + 1); setNotice("已保存。");
      return { value };
    } catch (reason) {
      if (!signal.aborted) {
        onError(reason);
        if (reason instanceof RequestError && reason.code === "REVISION_CONFLICT") {
          setEditingClass(null); setConflicts((count) => count + 1); setRefresh((count) => count + 1);
        }
      }
      return null;
    } finally { if (!signal.aborted) setBusy(false); }
  }
  async function saveClass(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const editing = editingClass;
    if (!editing) return;
    const result = await mutate(editing === "new" ? `${base}/classes` : `${base}/classes/${editing.id}`, editing === "new" ? "POST" : "PATCH",
      { name: fields.get("name"), ...(editing === "new" ? {} : { active: fields.has("active"), expected_revision: editing.revision }) });
    if (result) setEditingClass(null);
  }
  const title = section === "classes" ? (workspace.kind === "campus" && workspace.is_admin ? "班级与任课" : "我的班级") : section === "detail" ? "班级详情" : "学生名册";
  const detailPage = workspace.kind === "campus" && workspace.is_admin ? "C02" : "T09";
  return <><div className="page-heading"><div><h1>{title}</h1><p>{workspace.name} · {workspace.is_admin ? "维护稳定名单与任课关系" : "只显示你的任课范围"}</p></div>
    {section === "classes" && workspace.is_admin && <button className="primary" disabled={busy} onClick={() => setEditingClass("new")}>新建班级</button>}</div>
    {notice && <p className="success-box" role="status">{notice}</p>}
    {section === "detail" && <p><a href={workspace.kind === "campus" && workspace.is_admin ? "#C02" : "#T08"}>返回班级列表</a></p>}
    {classes.error && <p className="error-box" role="alert">{classes.error} <button onClick={() => setRefresh((count) => count + 1)}>重新读取</button></p>}
    {section === "classes" ? <>{classes.loading ? <p role="status">正在读取班级…</p> : !classes.error && <section className="panel table-scroll"><table><thead><tr><th>班级</th><th>有效学生</th><th>状态</th><th>操作</th></tr></thead><tbody>
      {classes.items.map((entry) => <tr key={entry.id}><td><a href={`#${detailPage}?class=${entry.id}`}>{entry.name}</a></td><td>{entry.student_count}</td><td>{entry.active ? "已启用" : "已停用"}</td><td>
        <div className="row-actions"><a href={`#${detailPage}?class=${entry.id}`}>查看名单与任课</a>{workspace.is_admin && <button disabled={busy} onClick={() => setEditingClass(entry)}>编辑班级</button>}</div></td></tr>)}</tbody></table>
      {classes.items.length === 0 && <div className="empty-state"><h2>{workspace.is_admin ? "还没有班级" : "还没有任课班级"}</h2><p>{workspace.is_admin ? "新建班级，再建立名单和任课关系。" : "请联系学校管理员设置任课关系。快速活动会随课堂功能接入。"}</p></div>}
      <Pagination cursor={classCursor} next={classes.next_cursor} previous={classPrevious} busy={busy || classes.loading} onChange={(cursor, previous) => { setClassCursor(cursor); setClassPrevious(previous); }} />
    </section>}</> : <>
      {section === "students" && <div className="roster-filter"><label>班级范围<select value={selectedClass} disabled={busy || classes.loading} onChange={(event) => setSelectedClass(event.target.value)}><option value="">全部有权查看的学生</option>
        {selectedClass && !classes.items.some((entry) => entry.id === selectedClass) && <option value={selectedClass}>已选班级</option>}
        {classes.items.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}{entry.active ? "" : "（停用）"}</option>)}</select></label>
        <Pagination cursor={classCursor} next={classes.next_cursor} previous={classPrevious} busy={busy || classes.loading} onChange={(cursor, previous) => { setClassCursor(cursor); setClassPrevious(previous); }} /></div>}
      {section === "detail" && !classId ? <p className="error-box">班级链接缺少有效标识，请返回班级列表。</p> : <>
        <StudentTable key={selectedClass} base={base} classId={selectedClass} workspace={workspace} classes={classes.items} classesNext={classes.next_cursor} classesLoading={classes.loading} classPaging={<Pagination cursor={classCursor} next={classes.next_cursor} previous={classPrevious} busy={busy || classes.loading} onChange={(cursor, previous) => { setClassCursor(cursor); setClassPrevious(previous); }} />} refresh={refresh} conflicts={conflicts} busy={busy} mutate={mutate} onError={onError} />
        {section === "detail" && classId && <Assignments base={base} classId={classId} workspace={workspace} refresh={refresh} busy={busy} mutate={mutate} onError={onError} />}
      </>}
    </>}
    {editingClass && <section className="panel section" key={editingClass === "new" ? "new" : `${editingClass.id}:${editingClass.revision}`}><h2>{editingClass === "new" ? "新建班级" : "编辑班级"}</h2>
      <form className="compact-form" onSubmit={(event) => void saveClass(event)}><label>班级名称<input name="name" required maxLength={80} defaultValue={editingClass === "new" ? "" : editingClass.name} disabled={busy} /></label>
        {editingClass !== "new" && <label className="checkbox-label"><input name="active" type="checkbox" defaultChecked={editingClass.active} disabled={busy} />启用班级</label>}
        <div className="row-actions"><button className="primary" disabled={busy}>保存班级</button><button type="button" disabled={busy} onClick={() => setEditingClass(null)}>取消</button></div></form></section>}
  </>;
}

type Mutation = <T>(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown) => Promise<{ value: T } | null>;

function StudentTable({ base, classId, workspace, classes, classesNext, classesLoading, classPaging, refresh, conflicts, busy, mutate, onError }: {
  base: string; classId: string; workspace: Workspace; classes: ClassEntry[]; classesNext: string | null; classesLoading: boolean; classPaging: ReactNode; refresh: number; conflicts: number; busy: boolean; mutate: Mutation; onError: (reason: unknown) => void;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<StudentEntry | "new" | null>(null);
  const [editClassId, setEditClassId] = useState(classId);
  const [issued, setIssued] = useState<{ student_id: string; code: string; expires_at: string } | null>(null);
  const codeGeneration = useRef(0);
  useEffect(() => () => { codeGeneration.current += 1; }, []);
  const parameters = new URLSearchParams({ q: query });
  if (classId) parameters.set("class_id", classId);
  if (cursor) parameters.set("cursor", cursor);
  const people = usePage<StudentEntry>(`${base}/students?${parameters}`, refresh, onError);
  useEffect(() => { codeGeneration.current += 1; setIssued(null); }, [query, cursor]);
  useEffect(() => { setEditing(null); }, [conflicts]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    const fields = new FormData(event.currentTarget);
    const result = await mutate(editing === "new" ? `${base}/students` : `${base}/students/${editing.id}`, editing === "new" ? "POST" : "PATCH", {
      reference: fields.get("reference"), display_name: fields.get("display_name"), class_id: fields.get("class_id") || null,
      ...(editing === "new" ? {} : { active: fields.has("active"), expected_revision: editing.revision }),
    });
    if (result) { setEditing(null); setIssued(null); }
  }
  const existingClass = editing && editing !== "new" ? editing.class_id : classId;
  return <><div className="roster-tools"><form className="member-search" onSubmit={(event) => { event.preventDefault(); setCursor(null); setPrevious([]); setQuery(String(new FormData(event.currentTarget).get("query") ?? "")); setEditing(null); }}>
    <label>查找学生<input name="query" placeholder="姓名或学校内部编号" maxLength={80} disabled={busy} /></label><button disabled={busy}>搜索</button></form>
    {workspace.is_admin && <button className="primary" disabled={busy || people.loading} onClick={() => { setEditing("new"); setEditClassId(classId); setIssued(null); }}>添加学生</button>}</div>
    {people.loading ? <p role="status">正在读取学生名单…</p> : people.error ? <p className="error-box" role="alert">{people.error}</p> : <section className="panel table-scroll"><table><thead><tr><th>学生</th><th>内部编号</th><th>班级</th><th>状态</th><th>操作</th></tr></thead><tbody>
      {people.items.map((student) => <tr key={student.id}><td>{student.display_name}</td><td>{student.reference}</td><td>{student.class_name ?? "待分班"}</td><td>{student.active ? "已启用" : "已停用"}</td><td><div className="row-actions">
        {workspace.is_admin && <button disabled={busy} onClick={() => { setEditing(student); setEditClassId(student.class_id ?? ""); setIssued(null); }}>维护名单</button>}
        <button disabled={busy || !student.active} onClick={() => { setIssued(null); const generation = ++codeGeneration.current; void mutate<{ student_id: string; code: string; expires_at: string }>(`${base}/students/${student.id}/code`, "POST", { expected_epoch: student.auth_epoch }).then((result) => { if (result && generation === codeGeneration.current) setIssued(result.value); }); }}>{student.has_code ? "重置个人码" : "发放个人码"}</button>
        {student.has_code && <button disabled={busy} onClick={() => { setIssued(null); void mutate(`${base}/students/${student.id}/code?expected_epoch=${student.auth_epoch}`, "DELETE"); }}>撤销个人码</button>}
      </div></td></tr>)}</tbody></table>
      {people.items.length === 0 && <p className="empty-state">当前范围内没有符合条件的学生。</p>}
      <Pagination cursor={cursor} next={people.next_cursor} previous={previous} busy={busy || people.loading} onChange={(next, stack) => { setCursor(next); setPrevious(stack); setEditing(null); }} />
    </section>}
    <p className="field-help">换班或改名保留同一个学生标识。重置、撤销个人码或停用学生会使旧码和旧学生会话失效。</p>
    {issued && <section className="credential-result"><h2>{people.items.find((student) => student.id === issued.student_id)?.display_name ?? "所选学生"} 的个人进入码</h2>
      <label>本次生成的个人码<input readOnly value={issued.code} onFocus={(event) => event.currentTarget.select()} /></label><p>仅在本次操作后显示。有效期至 {new Date(issued.expires_at).toLocaleString("zh-CN")}，请单独交给本人。</p><button onClick={() => setIssued(null)}>隐藏个人码</button></section>}
    {editing && <section className="panel section" key={editing === "new" ? "new" : `${editing.id}:${editing.revision}`}><h2>{editing === "new" ? "添加学生" : `维护 ${editing.display_name} 的名单条目`}</h2>
      <form className="compact-form" onSubmit={(event) => void save(event)}><label>学校内部编号<input name="reference" maxLength={64} required defaultValue={editing === "new" ? "" : editing.reference} disabled={busy} /></label>
        <label>姓名<input name="display_name" maxLength={80} required defaultValue={editing === "new" ? "" : editing.display_name} disabled={busy} /></label>
        <label>所属班级<select name="class_id" value={editClassId} onChange={(event) => setEditClassId(event.target.value)} disabled={busy || classesLoading}><option value="">待分班</option>
          {editClassId && !classes.some((entry) => entry.id === editClassId) && <option value={editClassId}>已选班级</option>}
          {classes.map((entry) => <option key={entry.id} value={entry.id} disabled={!entry.active && entry.id !== existingClass}>{entry.name}{entry.active ? "" : "（停用）"}</option>)}</select></label>
        {(classesNext || existingClass && !classes.some((entry) => entry.id === existingClass)) && <p className="field-help">列表按页读取，使用下面的分页选择其他班级。</p>}{classPaging}
        {editing !== "new" && <label className="checkbox-label"><input name="active" type="checkbox" defaultChecked={editing.active} disabled={busy} />启用学生条目</label>}
        <p className="field-help">同名学生分别使用不同编号，不按姓名合并历史。</p>
        <div className="row-actions"><button className="primary" disabled={busy || classesLoading}>保存名单</button><button type="button" disabled={busy} onClick={() => setEditing(null)}>取消</button></div></form></section>}
  </>;
}

function Assignments({ base, classId, workspace, refresh, busy, mutate, onError }: { base: string; classId: string; workspace: Workspace; refresh: number; busy: boolean; mutate: Mutation; onError: (reason: unknown) => void }) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);
  const [query, setQuery] = useState("");
  const [memberCursor, setMemberCursor] = useState<string | null>(null);
  const [memberPrevious, setMemberPrevious] = useState<(string | null)[]>([]);
  const [chosen, setChosen] = useState<Member | null>(null);
  const assignments = usePage<Assignment>(`${base}/classes/${classId}/assignments${cursor ? `?cursor=${cursor}` : ""}`, refresh, onError);
  const parameters = new URLSearchParams({ q: query }); if (memberCursor) parameters.set("cursor", memberCursor);
  return <section className="panel section"><h2>任课教师</h2>
    {assignments.loading ? <p role="status">正在读取任课关系…</p> : assignments.error ? <p className="error-box" role="alert">{assignments.error}</p> : <>
      {assignments.items.map((assignment) => <div className="list-row" key={assignment.account_id}><span>{assignment.display_name} · {assignment.subject}</span><span>{assignment.active && assignment.member_eligible ? "有效任课" : "已停用或成员失效"}</span>
        {workspace.is_admin && <button disabled={busy} onClick={() => void mutate(`${base}/classes/${classId}/assignments/${assignment.account_id}`, "PATCH", { subject: assignment.subject, active: !assignment.active, expected_revision: assignment.revision })}>{assignment.active ? "停用任课" : "启用任课"}</button>}</div>)}
      {assignments.items.length === 0 && <p>尚未建立任课关系。学校管理员可以指定教师。</p>}
      <Pagination cursor={cursor} next={assignments.next_cursor} previous={previous} busy={busy || assignments.loading} onChange={(value, stack) => { setCursor(value); setPrevious(stack); }} />
    </>}
    {workspace.is_admin && <><h2>指定任课教师</h2><form className="member-search" onSubmit={(event) => { event.preventDefault(); setMemberCursor(null); setMemberPrevious([]); setChosen(null); setQuery(String(new FormData(event.currentTarget).get("query") ?? "")); }}>
      <label>查找本空间成员<input name="query" maxLength={80} placeholder="姓名或登录名" disabled={busy} /></label><button disabled={busy}>搜索成员</button></form>
      <TeacherPicker url={`${base}/members?${parameters}`} chosen={chosen} busy={busy} refresh={refresh} cursor={memberCursor} previous={memberPrevious} onChange={(value, stack) => { setMemberCursor(value); setMemberPrevious(stack); }} onChoose={setChosen} onError={onError} />
      {chosen && <AssignmentEditor key={chosen.account_id} base={base} classId={classId} chosen={chosen} refresh={refresh} busy={busy} mutate={mutate} onError={onError} onClose={() => setChosen(null)} />}
    </>}
  </section>;
}

function TeacherPicker({ url, chosen, busy, refresh, cursor, previous, onChange, onChoose, onError }: { url: string; chosen: Member | null; busy: boolean; refresh: number; cursor: string | null; previous: (string | null)[]; onChange: (value: string | null, stack: (string | null)[]) => void; onChoose: (member: Member) => void; onError: (reason: unknown) => void }) {
  const people = usePage<Member>(url, refresh, onError);
  return <>{people.loading ? <p role="status">正在读取教师成员…</p> : people.error ? <p className="error-box">{people.error}</p> : <div className="teacher-picker">{people.items.filter((member) => member.active && member.is_teacher).map((member) => <button key={member.account_id} disabled={busy} aria-pressed={chosen?.account_id === member.account_id} onClick={() => onChoose(member)}>{member.display_name} · {member.login}</button>)}
    {people.items.every((member) => !member.active || !member.is_teacher) && <p>这一页没有有效教师，请搜索成员或翻页。</p>}</div>}
    <Pagination cursor={cursor} next={people.next_cursor} previous={previous} busy={busy || people.loading} onChange={onChange} /></>;
}

function AssignmentEditor({ base, classId, chosen, refresh, busy, mutate, onError, onClose }: { base: string; classId: string; chosen: Member; refresh: number; busy: boolean; mutate: Mutation; onError: (reason: unknown) => void; onClose: () => void }) {
  const page = usePage<Assignment>(`${base}/classes/${classId}/assignments?account_id=${encodeURIComponent(chosen.account_id)}`, refresh, onError);
  const existing = page.items[0];
  return page.loading ? <p role="status">正在核验任课关系…</p> : page.error ? <p className="error-box">{page.error}</p> : <form className="compact-form section" key={existing?.revision ?? 0} onSubmit={(event) => { event.preventDefault(); const subject = new FormData(event.currentTarget).get("subject");
    void mutate(`${base}/classes/${classId}/assignments/${chosen.account_id}`, "PATCH", { subject, active: true, expected_revision: existing?.revision ?? 0 }).then((result) => { if (result) onClose(); }); }}>
    <p>任课教师：{chosen.display_name}（{chosen.login}）</p><label>任教学科<input name="subject" required maxLength={40} disabled={busy} defaultValue={existing?.subject ?? ""} /></label>
    <button className="primary" disabled={busy}>保存任课关系</button><button type="button" disabled={busy} onClick={onClose}>取消</button></form>;
}
