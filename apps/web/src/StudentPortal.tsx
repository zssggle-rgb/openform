import { useEffect, useRef, useState, type FormEvent } from "react";
import logo from "../../../assets/brand/svg/openform-logo-primary.svg";
import { RequestError, request } from "./http";
import { getStudentSession } from "./roster";
import { StudentClassroom, type ParticipantSession } from "./StudentClassroom";
import { clearPendingWrites } from "./RuntimePlayer";

export function StudentPortal({ page = "S01", classroomId, attemptId, classroomCode }: { page?: string; classroomId?: string | null; attemptId?: string | null; classroomCode?: string | null }) {
  const [session, setSession] = useState<ParticipantSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [entryMode, setEntryMode] = useState<"quick" | "personal">("quick");
  const playing = Boolean(session && ["S02", "S03"].includes(page));
  const [targetCode, setTargetCode] = useState(classroomCode ?? null);
  useEffect(() => { if (classroomCode) setTargetCode(classroomCode); }, [classroomCode]);
  const lifetime = useRef<AbortController | null>(null);
  async function currentSession(signal: AbortSignal): Promise<ParticipantSession> {
    try { return { ...await getStudentSession(signal), kind: "student" }; }
    catch (reason) {
      if (!(reason instanceof RequestError && reason.status === 401)) throw reason;
      const guest = await request<ParticipantSession>("/api/guest-auth/session", { signal });
      if (!guest || typeof guest.guest_id !== "string" || typeof guest.classroom_id !== "string"
        || typeof guest.workspace_id !== "string" || typeof guest.csrf_token !== "string" || !/^[a-f0-9]{64}$/.test(guest.csrf_token)) throw new Error("快速身份服务返回了无法识别的内容。");
      return { ...guest, kind: "guest" };
    }
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    void currentSession(controller.signal).then((value) => { if (!controller.signal.aborted) setSession(value); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { if (reason instanceof RequestError && reason.status === 401) clearPendingWrites(); else setError(reason instanceof Error ? reason.message : "身份验证未完成。"); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted) return;
    setBusy(true); setError("");
    const form = event.currentTarget;
    try {
      await request("/api/student-auth/code", { method: "POST", body: { code: new FormData(form).get("code") }, signal });
      clearPendingWrites();
      form.reset();
      const value = await getStudentSession(signal);
      if (!signal.aborted) setSession({ ...value, kind: "student" });
    } catch (reason) { if (!signal.aborted) setError(reason instanceof Error ? reason.message : "验证未完成，请重试。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function enterQuick(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); setError(""); const form = event.currentTarget; const fields = new FormData(form);
    try {
      await request("/api/guest-auth/enter", { method: "POST", body: { code: String(fields.get("code")).trim().toUpperCase(), display_name: fields.get("display_name") }, signal });
      clearPendingWrites(); form.reset(); const value = await currentSession(signal); if (!signal.aborted) setSession(value);
    } catch (reason) { if (!signal.aborted) setError(reason instanceof Error ? reason.message : "进入未完成。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  function expired(reason: unknown) {
    clearPendingWrites(); setSession(null); setError(reason instanceof Error ? reason.message : "身份已失效，请重新进入。");
    location.hash = targetCode ? `#S01?code=${targetCode}` : "#S01";
  }
  async function logout() {
    const signal = lifetime.current?.signal;
    if (!session || !signal || signal.aborted) return;
    setBusy(true); setError("");
    try {
      await request(`/api/${session.kind}-auth/logout`, { method: "POST", csrf: session.csrf_token, signal });
      clearPendingWrites();
      if (!signal.aborted) { setSession(null); location.hash = targetCode ? `#S01?code=${targetCode}` : "#S01"; }
    } catch (reason) {
      if (!signal.aborted) {
        if (reason instanceof RequestError && reason.status === 401) { clearPendingWrites(); setSession(null); location.hash = targetCode ? `#S01?code=${targetCode}` : "#S01"; }
        setError(reason instanceof Error ? reason.message : "退出未完成，请重试。");
      }
    } finally { if (!signal.aborted) setBusy(false); }
  }
  return <div className={`student-shell${playing ? " student-playing" : ""}`}><header><img src={logo} width="136" alt="OpenForm" /><div className="header-links">{!playing && <a className="help-link" href="/guide.html#student" target="_blank" rel="noreferrer">使用说明<span className="sr-only">（新标签页）</span></a>}{!session && <a href="#G01">教师入口</a>}</div></header>
    <main className="student-container">{error && <p className="error-box" role="alert">{error}</p>}
      {loading ? <p role="status">正在验证学生身份…</p> : session ? <>
        <div className="student-identity"><strong>{session.display_name}</strong><button disabled={busy} onClick={() => void logout()}>换一位同学</button></div>
        <nav className="student-navigation" aria-label="学生导航"><a href="#S01" aria-current={page === "S01" ? "page" : undefined}>进入课堂</a><a href="#S04" aria-current={page === "S04" ? "page" : undefined}>我的记录</a></nav>
        <StudentClassroom key={`${session.kind}:${session.student_id ?? session.guest_id}`} session={session} page={page} classroomId={classroomId} attemptId={attemptId} classroomCode={classroomCode} onClassroomCode={setTargetCode} onExpired={expired} />
      </> : <section className="panel"><h1>进入课堂</h1><div className="tab-bar"><button aria-pressed={entryMode === "quick"} onClick={() => setEntryMode("quick")}>课堂码与称呼</button><button aria-pressed={entryMode === "personal"} onClick={() => setEntryMode("personal")}>个人进入码</button></div>
        {entryMode === "personal" ? <>
        <form onSubmit={(event) => void authenticate(event)}><label>个人进入码<input name="code" autoComplete="off" autoCapitalize="characters" spellCheck={false} required minLength={16} maxLength={23} placeholder="XXXX-XXXX-XXXX-XXXX" disabled={busy} /></label>
          <button className="primary wide" disabled={busy}>{busy ? "正在进入…" : "继续"}</button></form>
        <p className="field-help">忘记个人进入码，请联系教师。</p>
      </> : <>
        <form key={classroomCode ?? "entry"} onSubmit={(event) => void enterQuick(event)}><label>课堂码<input name="code" required minLength={8} maxLength={8} autoCapitalize="characters" autoComplete="off" defaultValue={classroomCode ?? ""} readOnly={Boolean(classroomCode)} disabled={busy} /></label>
          <label>你的称呼<input name="display_name" required maxLength={80} autoComplete="off" disabled={busy} /></label><button className="primary wide" disabled={busy}>进入课堂</button></form>
      </>}</section>}
    </main></div>;
}
