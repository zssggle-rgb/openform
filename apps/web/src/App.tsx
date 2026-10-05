import { useEffect, useRef, useState, type FormEvent } from "react";
import logo from "../../../assets/brand/svg/openform-logo-primary.svg";
import { RequestError, request } from "./http";
import { getSession, invitationFromHash, type Invitation, type Member, type Session, type Workspace } from "./identity";
import { RosterView } from "./RosterView";
import { StudentPortal } from "./StudentPortal";
import { routeFromHash } from "./roster";

const messageOf = (error: unknown) => error instanceof Error ? error.message : "操作未完成，请重试。";

function replaceRoute(hash: string) {
  history.replaceState(null, "", hash);
  dispatchEvent(new HashChangeEvent("hashchange"));
}

export function App() {
  const [route, setRoute] = useState(() => routeFromHash(location.hash));
  useEffect(() => { const changed = () => setRoute(routeFromHash(location.hash)); addEventListener("hashchange", changed); return () => removeEventListener("hashchange", changed); }, []);
  return route.page.startsWith("S") ? <StudentPortal /> : <StaffApp route={route} />;
}

function StaffApp({ route }: { route: ReturnType<typeof routeFromHash> }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [invite, setInvite] = useState(() => invitationFromHash(location.hash));
  const [busy, setBusy] = useState(false);
  const [inviteDetails, setInviteDetails] = useState<{ name: string; is_teacher: boolean; is_admin: boolean } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void getSession(controller.signal).then((value) => { if (active) setSession(value); })
      .catch((reason: unknown) => { if (active && !(reason instanceof RequestError && reason.status === 401)) setError(messageOf(reason)); })
      .finally(() => { if (active) setLoading(false); });
    const hashChanged = () => setInvite(invitationFromHash(location.hash));
    addEventListener("hashchange", hashChanged);
    return () => { active = false; controller.abort(); removeEventListener("hashchange", hashChanged); };
  }, []);

  useEffect(() => {
    if (session && !session.workspaces.some((workspace) => workspace.id === workspaceId && workspace.active)) {
      setWorkspaceId(session.workspaces.find((workspace) => workspace.active)?.id ?? "");
    }
  }, [session, workspaceId]);

  useEffect(() => {
    setInviteDetails(null);
    if (!session || !invite) return;
    const controller = new AbortController();
    void request<{ name: string; is_teacher: boolean; is_admin: boolean }>("/api/invites/preview", {
      method: "POST", csrf: session.csrf_token, body: { token: invite }, signal: controller.signal,
    }).then((details) => { if (!controller.signal.aborted) setInviteDetails(details); })
      .catch((reason) => { if (!controller.signal.aborted) setError(messageOf(reason)); });
    return () => controller.abort();
  }, [session?.account_id, session?.csrf_token, invite]);

  async function refreshSession() { setSession(await getSession()); }
  function expired(reason: unknown) {
    if (reason instanceof RequestError && reason.status === 401) { setSession(null); setWorkspaceId(""); }
    setError(messageOf(reason));
  }
  async function logout() {
    if (!session) return;
    setBusy(true); setError("");
    try { await request<void>("/api/auth/logout", { method: "POST", csrf: session.csrf_token }); setSession(null); setWorkspaceId(""); }
    catch (reason) { expired(reason); }
    finally { setBusy(false); }
  }
  async function acceptInvite() {
    if (!session || !invite) return;
    setBusy(true); setError("");
    try {
      const joined = await request<{ workspace_id: string }>("/api/invites/accept", { method: "POST", body: { token: invite }, csrf: session.csrf_token });
      await refreshSession(); setWorkspaceId(joined.workspace_id); setInvite(null); replaceRoute("#C01");
    } catch (reason) { expired(reason); }
    finally { setBusy(false); }
  }

  const workspace = session?.workspaces.find((space) => space.id === workspaceId && space.active);
  return <>
    <header className="topbar"><img src={logo} width="152" alt="OpenForm" />
      {session && <div className="topbar-controls"><label className="sr-only" htmlFor="space">当前空间</label>
        <select id="space" value={workspaceId} disabled={busy} onChange={(event) => { setWorkspaceId(event.target.value); setError(""); }}>
          {session.workspaces.filter((space) => space.active).map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
        </select><span>{session.display_name}</span><button disabled={busy} onClick={() => void logout()}>退出登录</button></div>}
    </header>
    {loading ? <main><p role="status">正在验证账号…</p></main> : !session ? <Login error={error} onAuthenticated={async () => { setError(""); await refreshSession(); }} /> : <>
      {invite && <section className="invite-banner"><strong>{inviteDetails ? `加入 ${inviteDetails.name}` : "正在核验学校邀请"}</strong>
        <p>{inviteDetails ? `受邀职责：${[inviteDetails.is_teacher && "教师", inviteDetails.is_admin && "学校管理员"].filter(Boolean).join("、")}。你的个人空间继续保留。` : "核验学校和受邀职责后再接受邀请。"}</p>
        <button className="primary" disabled={busy || !inviteDetails} onClick={() => void acceptInvite()}>接受学校邀请</button>
        <button disabled={busy} onClick={() => { setInvite(null); replaceRoute("#G01"); }}>暂不加入</button></section>}
      {error && <div className="global-error" role="alert">{error}</div>}
      {workspace ? <WorkspaceView key={`${session.account_id}:${workspace.id}`} session={session} workspace={workspace} route={route} onError={expired} />
        : <main><h1>当前没有可用空间</h1><p>请刷新账号状态或联系学校管理员。</p><button onClick={() => void refreshSession().catch(expired)}>刷新账号</button></main>}
    </>}
  </>;
}

function Login({ error, onAuthenticated }: { error: string; onAuthenticated: () => Promise<void> }) {
  const [registration, setRegistration] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setFailure("");
    const form = event.currentTarget;
    const fields = new FormData(form);
    const body = { login: fields.get("login"), password: fields.get("password"), ...(registration ? { display_name: fields.get("display_name") } : {}) };
    try { await request(registration ? "/api/auth/register" : "/api/auth/login", { method: "POST", body }); form.reset(); await onAuthenticated(); }
    catch (reason) { setFailure(messageOf(reason)); }
    finally { setBusy(false); }
  }
  return <main className="login-container"><section className="panel login-panel">
    <h1>{registration ? "创建个人账号" : "进入 OpenForm"}</h1><p>教师与校园共用的课堂活动平台</p>
    {(failure || error) && <p className="error-box" role="alert">{failure || error}</p>}
    <form onSubmit={(event) => void submit(event)}>
      <label>登录名<input name="login" autoComplete="username" required minLength={3} maxLength={64} pattern="[a-zA-Z0-9._-]+" disabled={busy} /></label>
      <p className="field-help">使用字母、数字、点、短横线或下划线。</p>
      {registration && <label>显示名称<input name="display_name" required maxLength={80} autoComplete="name" disabled={busy} /></label>}
      <label>密码<input name="password" type="password" required minLength={registration ? 12 : 1} maxLength={256} autoComplete={registration ? "new-password" : "current-password"} disabled={busy} /></label>
      {registration && <p className="field-help">至少 12 个字符。创建后拥有独立个人空间。</p>}
      <button className="primary wide" disabled={busy}>{busy ? "正在验证…" : registration ? "创建账号" : "登录"}</button>
    </form>
    <button className="text-button" disabled={busy} onClick={() => { setRegistration(!registration); setFailure(""); }}>{registration ? "已有账号，返回登录" : "创建个人账号"}</button>
    <p className="field-help">学校成员使用同一账号登录，再接受管理员的邀请。忘记密码请联系部署管理员。</p>
    <p><a href="#S01">学生使用个人码进入</a></p>
  </section></main>;
}

function WorkspaceView({ session, workspace, route, onError }: { session: Session; workspace: Workspace; route: ReturnType<typeof routeFromHash>; onError: (error: unknown) => void }) {
  const admin = workspace.kind === "campus" && workspace.is_admin && (route.page.startsWith("C") || !workspace.is_teacher);
  const rosterPage = ["C02", "C03", "T08", "T09"].includes(route.page);
  const section = route.classId || route.page === "T09" ? "detail" : route.page === "C03" ? "students" : "classes";
  return <div className="workbench"><aside><p className="sidebar-caption">{admin ? "校园管理" : "教学工作台"}</p>
    {workspace.kind === "campus" && workspace.is_admin && workspace.is_teacher && <div className="mode-switch">
      <button aria-pressed={!admin} onClick={() => { location.hash = "#T01"; }}>教学工作台</button>
      <button aria-pressed={admin} onClick={() => { location.hash = "#C01"; }}>校园管理</button></div>}
    <a href={admin ? "#C01" : "#T01"} aria-current={!rosterPage ? "page" : undefined}>{admin ? "成员与权限" : "我的活动"}</a>
    <a href={admin ? "#C02" : "#T08"} aria-current={rosterPage && route.page !== "C03" ? "page" : undefined}>{admin ? "班级与任课" : "我的班级"}</a>
    {admin && <a href="#C03" aria-current={route.page === "C03" ? "page" : undefined}>学生名册</a>}
    <a href="#S01">学生入口</a></aside>
    <main>{rosterPage ? <RosterView key={`${route.page}:${route.classId ?? ""}`} session={session} workspace={workspace} section={section} classId={route.classId} onError={onError} /> : admin ? <Members session={session} workspace={workspace} onError={onError} /> : <>
      <div className="page-heading"><div><h1>我的活动</h1><p>{workspace.name} · {workspace.kind === "personal" ? "个人空间" : "学校教学空间"}</p></div></div>
      <section className="panel empty-state"><h2>活动功能正在开发</h2><p>账号和空间已接入真实服务；活动制作与课堂将在后续任务接入。</p>
        {workspace.kind === "campus" && <p>你已取得学校教师身份。班级和课堂只会显示你有权使用的范围。</p>}</section>
    </>}</main>
  </div>;
}

function Members({ session, workspace, onError }: { session: Session; workspace: Workspace; onError: (error: unknown) => void }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [newInvite, setNewInvite] = useState<{ id: string; token: string; expires_at: string } | null>(null);
  const [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Member | null>(null);
  const base = `/api/workspaces/${encodeURIComponent(workspace.id)}`;

  async function reload(signal?: AbortSignal) {
    const parameters = new URLSearchParams({ q: query });
    if (cursor) parameters.set("cursor", cursor);
    const [people, invitations] = await Promise.all([request<{ items: Member[]; next_cursor: string | null }>(`${base}/members?${parameters}`, { signal }), request<{ items: Invitation[] }>(`${base}/invites`, { signal })]);
    if (!signal?.aborted) { setMembers(people.items); setNextCursor(people.next_cursor); setInvites(invitations.items); setLoading(false); }
  }
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    setLoading(true); setEditing(null);
    void reload(controller.signal).catch((reason) => { if (!controller.signal.aborted) { onError(reason); setLoading(false); } });
    return () => controller.abort();
  }, [base, cursor, query]);

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return;
    event.preventDefault(); setBusy(true); setNotice("");
    const fields = new FormData(event.currentTarget);
    try {
      const created = await request<{ id: string; token: string; expires_at: string }>(`${base}/invites`, { method: "POST", csrf: session.csrf_token, signal,
        body: { is_teacher: fields.has("is_teacher"), is_admin: fields.has("is_admin"), target_login: fields.get("target_login") || null } });
      if (!signal.aborted) setNewInvite(created);
      await reload(signal);
    } catch (reason) { if (!signal.aborted) onError(reason); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function change(member: Member, data = { is_teacher: member.is_teacher, is_admin: member.is_admin, active: !member.active }) {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await request(`${base}/members/${encodeURIComponent(member.account_id)}`, { method: "PATCH", csrf: session.csrf_token, signal,
      body: { ...data, expected_epoch: member.auth_epoch } }); await reload(signal);
      if (!signal.aborted) { setEditing(null); setNotice("成员职责与校园访问状态已更新，个人空间继续保留。"); } }
    catch (reason) {
      if (!signal.aborted) {
        onError(reason);
        if (reason instanceof RequestError && reason.code === "REVISION_CONFLICT") {
          setEditing(null);
          try { await reload(signal); } catch (reloadError) { if (!signal.aborted) onError(reloadError); }
        }
      }
    }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function revoke(id: string) {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return;
    setBusy(true); setNotice("");
    try { await request(`${base}/invites/${encodeURIComponent(id)}`, { method: "DELETE", csrf: session.csrf_token, signal });
      if (!signal.aborted && newInvite?.id === id) setNewInvite(null);
      await reload(signal); if (!signal.aborted) setNotice("邀请已撤销。"); }
    catch (reason) { if (!signal.aborted) onError(reason); }
    finally { if (!signal.aborted) setBusy(false); }
  }

  return <><div className="page-heading"><div><h1>成员与权限</h1><p>{workspace.name} · 管理职责与教学权限分别授予</p></div></div>
    {notice && <p className="success-box" role="status">{notice}</p>}
    <form className="member-search" onSubmit={(event) => { event.preventDefault(); const fields = new FormData(event.currentTarget); setCursor(null); setPrevious([]); setQuery(String(fields.get("query") || "")); }}>
      <label>查找成员<input name="query" placeholder="姓名或登录名" maxLength={80} disabled={busy} /></label><button disabled={busy}>搜索</button>
    </form>
    {loading ? <p role="status">正在读取学校成员…</p> : <section className="panel table-scroll"><table><thead><tr><th>成员</th><th>登录名</th><th>职责</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>{members.map((member) => <tr key={member.account_id}><td>{member.display_name}</td><td>{member.login}</td><td>{[member.is_teacher && "教师", member.is_admin && "学校管理员"].filter(Boolean).join("、")}</td>
        <td><span className={`tag ${member.active ? "success" : "warning"}`}>{member.active ? "已启用" : "已停用"}</span></td>
        <td>{member.account_id === session.account_id ? "当前身份" : <div className="row-actions"><button disabled={busy} onClick={() => void change(member)}>{member.active ? "停用校园访问" : "启用校园访问"}</button>
          <button disabled={busy} onClick={() => setEditing(member)}>调整职责</button></div>}</td></tr>)}</tbody></table>
      {members.length === 0 && <p className="empty-state">没有符合条件的成员。</p>}
      <div className="pagination"><span>每页最多 50 位成员</span><button disabled={busy || previous.length === 0} onClick={() => { setCursor(previous.at(-1) ?? null); setPrevious(previous.slice(0, -1)); }}>上一页</button>
        <button disabled={busy || !nextCursor} onClick={() => { setPrevious([...previous, cursor]); setCursor(nextCursor); }}>下一页</button></div></section>}
    {editing && <section className="panel section" key={`${editing.account_id}:${editing.auth_epoch}`}><h2>调整 {editing.display_name} 的职责</h2><form onSubmit={(event) => { event.preventDefault(); const fields = new FormData(event.currentTarget); void change(editing, { is_teacher: fields.has("is_teacher"), is_admin: fields.has("is_admin"), active: editing.active }); }}>
      <div className="checkbox-row"><label><input type="checkbox" name="is_teacher" defaultChecked={editing.is_teacher} disabled={busy} />教师</label>
        <label><input type="checkbox" name="is_admin" defaultChecked={editing.is_admin} disabled={busy} />学校管理员</label></div>
      <button className="primary" disabled={busy}>保存职责</button><button disabled={busy} onClick={() => setEditing(null)} type="button">取消</button>
    </form></section>}
    <section className="panel section"><h2>邀请学校成员</h2><p>邀请 7 天内有效，只能由一个账号接受。管理角色不自动开放学生回答。</p>
      <form className="invite-form" onSubmit={(event) => void createInvite(event)}>
        <label>限定登录名（可选）<input name="target_login" maxLength={64} pattern="[a-zA-Z0-9._-]+" disabled={busy} /></label>
        <div className="checkbox-row"><label><input type="checkbox" name="is_teacher" defaultChecked disabled={busy} />教师</label>
          <label><input type="checkbox" name="is_admin" disabled={busy} />学校管理员</label></div><button className="primary" disabled={busy}>生成邀请</button>
      </form>
      {newInvite && <div className="credential-result"><label>邀请链接<input readOnly value={`${location.origin}/#G01?invite=${newInvite.token}`} onFocus={(event) => event.currentTarget.select()} /></label>
        <p>完整链接只在本次生成后显示，请交给受邀人。有效期至 {new Date(newInvite.expires_at).toLocaleString("zh-CN")}。</p>
        <button onClick={() => setNewInvite(null)}>隐藏邀请链接</button></div>}
      {invites.length > 0 && <div className="invite-list"><p className="field-help">全部待接受邀请与最近记录，最多显示 100 条。</p>{invites.map((invitation) => <div key={invitation.id} className="list-row">
        <span>{invitation.target_login || "未限定账号"} · {invitation.is_teacher ? "教师" : ""}{invitation.is_teacher && invitation.is_admin ? " / " : ""}{invitation.is_admin ? "管理员" : ""}</span>
        <span>{invitation.accepted ? "已接受" : !invitation.active ? "已撤销" : Date.parse(invitation.expires_at) < Date.now() ? "已过期" : "待接受"}</span>
        {invitation.active && !invitation.accepted && <button disabled={busy} onClick={() => void revoke(invitation.id)}>撤销邀请</button>}</div>)}</div>}
    </section>
  </>;
}
