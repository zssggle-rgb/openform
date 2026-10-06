import { useEffect, useRef, useState, type FormEvent } from "react";
import logo from "../../../assets/brand/svg/openform-logo-primary.svg";
import { RequestError, request } from "./http";
import { getStudentSession } from "./roster";
import { StudentClassroom, type ParticipantSession } from "./StudentClassroom";
import { clearPendingWrites } from "./RuntimePlayer";

export function StudentPortal({ page = "S01", classroomId, attemptId }: { page?: string; classroomId?: string | null; attemptId?: string | null }) {
  const [session, setSession] = useState<ParticipantSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
  }
  async function logout() {
    const signal = lifetime.current?.signal;
    if (!session || !signal || signal.aborted) return;
    setBusy(true); setError("");
    try {
      await request(`/api/${session.kind}-auth/logout`, { method: "POST", csrf: session.csrf_token, signal });
      clearPendingWrites();
      if (!signal.aborted) setSession(null);
    } catch (reason) {
      if (!signal.aborted) {
        if (reason instanceof RequestError && reason.status === 401) { clearPendingWrites(); setSession(null); }
        setError(reason instanceof Error ? reason.message : "退出未完成，请重试。");
      }
    } finally { if (!signal.aborted) setBusy(false); }
  }
  return <div className="student-shell"><header><img src={logo} width="136" alt="OpenForm" /><div className="header-links"><a className="help-link" href="/guide.html#student" target="_blank" rel="noreferrer">使用说明<span className="sr-only">（新标签页）</span></a><a href="#G01">教师入口</a></div></header>
    <main className="student-container">{error && <p className="error-box" role="alert">{error}</p>}
      {loading ? <p role="status">正在验证学生身份…</p> : session ? <>
        <section className="panel"><p>{session.workspace_name}</p><h1>你好，{session.display_name}</h1>{session.reference && <p>学生编号：{session.reference}</p>}
          <p>{session.kind === "student" ? "个人身份已验证，可跨设备恢复本人课堂进度。" : "本次快速课堂身份已建立。"}</p>
          <button disabled={busy} onClick={() => void logout()}>退出学生身份 / 换一位同学</button>
          <p className="field-help">使用共用设备时，请先退出，再交给下一位同学。</p></section>
        <nav className="student-navigation" aria-label="学生导航"><a href="#S01" aria-current={page === "S01" ? "page" : undefined}>进入课堂</a><a href="#S04" aria-current={page === "S04" ? "page" : undefined}>我的记录</a></nav>
        <StudentClassroom key={`${session.kind}:${session.student_id ?? session.guest_id}`} session={session} page={page} classroomId={classroomId} attemptId={attemptId} onExpired={expired} />
      </> : <><section className="panel"><h1>验证个人进入码</h1><p>输入教师给你的 16 位个人码，在不同设备使用同一个学生身份。</p>
        <form onSubmit={(event) => void authenticate(event)}><label>个人进入码<input name="code" autoComplete="off" autoCapitalize="characters" spellCheck={false} required minLength={16} maxLength={23} placeholder="XXXX-XXXX-XXXX-XXXX" disabled={busy} /></label>
          <button className="primary wide" disabled={busy}>{busy ? "正在验证…" : "验证身份"}</button></form>
        <p className="field-help">个人码用来确认你是谁。课堂码用来找到活动，两种码不能互相替代。忘记个人码请联系教师。</p>
      </section><section className="panel section"><h2>参加快速课堂</h2><p>教师开设快速课堂时，可用课堂码和称呼进入。称呼只用于展示，不用于确认身份。</p>
        <form onSubmit={(event) => void enterQuick(event)}><label>课堂码<input name="code" required minLength={8} maxLength={8} autoCapitalize="characters" autoComplete="off" disabled={busy} /></label>
          <label>本次课堂称呼<input name="display_name" required maxLength={80} autoComplete="off" disabled={busy} /></label><button className="primary wide" disabled={busy}>进入快速课堂</button></form>
      </section></>}
    </main></div>;
}
