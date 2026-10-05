import { useEffect, useRef, useState, type FormEvent } from "react";
import logo from "../../../assets/brand/svg/openform-logo-primary.svg";
import { RequestError, request } from "./http";
import { getStudentSession, type StudentSession } from "./roster";

export function StudentPortal() {
  const [session, setSession] = useState<StudentSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    void getStudentSession(controller.signal).then((value) => { if (!controller.signal.aborted) setSession(value); })
      .catch((reason: unknown) => { if (!controller.signal.aborted && !(reason instanceof RequestError && reason.status === 401)) setError(reason instanceof Error ? reason.message : "身份验证未完成。"); })
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
      form.reset();
      const value = await getStudentSession(signal);
      if (!signal.aborted) setSession(value);
    } catch (reason) { if (!signal.aborted) setError(reason instanceof Error ? reason.message : "验证未完成，请重试。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function logout() {
    const signal = lifetime.current?.signal;
    if (!session || !signal || signal.aborted) return;
    setBusy(true); setError("");
    try {
      await request("/api/student-auth/logout", { method: "POST", csrf: session.csrf_token, signal });
      if (!signal.aborted) setSession(null);
    } catch (reason) {
      if (!signal.aborted) {
        if (reason instanceof RequestError && reason.status === 401) setSession(null);
        setError(reason instanceof Error ? reason.message : "退出未完成，请重试。");
      }
    } finally { if (!signal.aborted) setBusy(false); }
  }
  return <div className="student-shell"><header><img src={logo} width="136" alt="OpenForm" /><a href="#G01">教师入口</a></header>
    <main className="student-container">{error && <p className="error-box" role="alert">{error}</p>}
      {loading ? <p role="status">正在验证学生身份…</p> : session ? <>
        <section className="panel"><p>{session.workspace_name}</p><h1>你好，{session.display_name}</h1><p>学生编号：{session.reference}</p>
          <p>身份已验证。课堂参与和本人历史会在课堂功能接入后显示。</p>
          <button disabled={busy} onClick={() => void logout()}>退出学生身份 / 换一位同学</button>
          <p className="field-help">使用共用设备时，请先退出，再交给下一位同学。</p></section>
      </> : <section className="panel"><h1>验证个人进入码</h1><p>输入教师给你的 16 位个人码，在不同设备使用同一个学生身份。</p>
        <form onSubmit={(event) => void authenticate(event)}><label>个人进入码<input name="code" autoComplete="off" autoCapitalize="characters" spellCheck={false} required minLength={16} maxLength={23} placeholder="XXXX-XXXX-XXXX-XXXX" disabled={busy} /></label>
          <button className="primary wide" disabled={busy}>{busy ? "正在验证…" : "验证身份"}</button></form>
        <p className="field-help">个人码用来确认你是谁。课堂码用来找到活动，两种码不能互相替代。忘记个人码请联系教师。</p>
      </section>}
    </main></div>;
}
