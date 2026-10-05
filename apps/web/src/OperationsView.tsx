import { useEffect, useState, type FormEvent } from "react";
import logo from "../../../assets/brand/svg/openform-logo-primary.svg";
import { RequestError, request } from "./http";

interface Backup { snapshot_at: string; id: string; local_verified: boolean; offsite_verified: boolean; cipher_sha256?: string }
interface Recovery { snapshot_at: string; source_instance: string; verified: boolean; opened_at: string | null; gap_notice: string; counts: Record<string, number> }
interface Status { instance_id: string; generation: number; schema: string; maintenance: boolean; restored_locked: boolean; backup: Backup | null; pending_backup: Backup | null; recovery: Recovery | null; jobs: Record<string, number>; exports: Record<string, number>; csrf_token: string; model_configured: boolean; model_id: string }
const labels: Record<string, string> = { queued: "排队", running: "处理", succeeded: "完成", failed: "失败", cancelled: "取消", outcome_unknown: "结果和费用待确认", invalidated: "已失效" };
const when = (date: string) => new Date(date).toLocaleString("zh-CN", { hour12: false });

export function OperationsView() {
  const [status, setStatus] = useState<Status | null>(null), [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  function failure(reason: unknown) {
    if (reason instanceof RequestError && reason.status === 401) setStatus(null);
    setError(reason instanceof Error ? reason.message : "运维状态暂不可用，请重试。");
  }
  async function load(signal?: AbortSignal) {
    const value = await request<Status>("/api/ops/status", { signal });
    if (!signal?.aborted) { setStatus(value); setError(""); }
  }
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((reason) => {
      if (!controller.signal.aborted && !(reason instanceof RequestError && reason.status === 401)) failure(reason);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; setBusy(true); setError("");
    try { await request("/api/ops/login", { method: "POST", body: { credential: new FormData(form).get("credential") } }); form.reset(); await load(); }
    catch (reason) { form.reset(); failure(reason); }
    finally { setBusy(false); }
  }
  async function logout() {
    if (!status) return; setBusy(true);
    try { await request("/api/ops/logout", { method: "POST", csrf: status.csrf_token }); setStatus(null); }
    catch (reason) { failure(reason); }
    finally { setBusy(false); }
  }
  return <><header className="topbar"><img src={logo} width="152" alt="OpenForm" /><div className="topbar-controls"><span>独立实例运维</span>{status && <button disabled={busy} onClick={() => void logout()}>退出运维</button>}</div></header>
    <main className={status ? "ops-container" : "login-container"}>
      {error && <p className="global-error" role="alert">{error}</p>}
      {loading ? <p role="status">正在验证运维身份…</p> : !status ? <section className="panel login-panel"><h1>实例运维登录</h1><p>使用部署负责人单独配置的运维凭据。教师与校园账号不能授权此入口。</p><form className="compact-form" onSubmit={(event) => void login(event)}><label>独立运维凭据<input type="password" name="credential" autoComplete="off" required minLength={43} maxLength={43} disabled={busy} /></label><button className="primary" disabled={busy}>进入运维</button></form><p><a href="#G01">返回课堂平台</a></p></section> : <>
        <div className="page-heading"><div><h1>实例备份与恢复</h1><p>独立部署职责 · 运行状态与恢复点</p></div><button disabled={busy} onClick={() => void load().catch(failure)}>刷新状态</button></div>
        <section className="panel"><h2>{status.restored_locked ? "恢复锁定，等待重新授权" : status.maintenance ? "维护中，暂停业务访问" : "服务已开放"}</h2><p>实例 {status.instance_id} · 授权代次 {status.generation}</p><p>数据版本 {status.schema} · 模型 {status.model_id}：{status.model_configured ? "已配置" : "未配置，课堂收集仍可独立使用"}</p></section>
        {status.recovery && <section className="panel section"><h2>恢复核对</h2><p>来源实例：{status.recovery.source_instance}</p><p>恢复点：{when(status.recovery.snapshot_at)}</p><p>{status.recovery.gap_notice}</p><div className="metric-strip"><span>最终提交 {status.recovery.counts.activity_submissions}</span><span>活动版本 {status.recovery.counts.activity_versions}</span><span>图片记录 {status.recovery.counts.image_assets}</span><span>历史档案 {status.recovery.counts.classroom_archives}</span></div><p>{status.recovery.verified ? "数据库数量与文件摘要已核对。" : "核对尚未完成。"} {status.recovery.opened_at ? `已重新授权开放：${when(status.recovery.opened_at)}` : "旧账号、会话、学生码和成员授权已暂停，核对并重新授权后才能开放。"}</p></section>}
        {status.pending_backup && <p className="global-error" role="status">最近一次备份尝试尚未核验：{when(status.pending_backup.snapshot_at)}。下方继续保留上次已核验备份。</p>}
        <section className="panel section"><h2>最近备份</h2>{status.backup ? <><p>恢复点：{when(status.backup.snapshot_at)}</p><p>备份编号：{status.backup.id}</p><p>加密文件：{status.backup.local_verified ? "本机摘要核验完成" : "尚未完成核验"} · 实例外副本：{status.backup.offsite_verified ? "已核对" : "尚未确认，不能作为异机恢复保证"}</p></> : <p>尚无备份记录，不能宣称可以恢复。</p>}<p>备份与恢复由部署主机上的受控命令执行；密钥另行保管，恢复到全新的实例。</p><details><summary>运维操作流程</summary><ol><li>开启维护并等待进行中的任务停止。</li><li>同步保存数据库和图片，生成摘要并加密。</li><li>将加密备份复制到实例外，核对摘要。</li><li>新实例核验并恢复，核对可能缺失的时间段。</li><li>重新配置运维凭据、学校授权和模型密钥，再开放服务。</li></ol><p>安装目录 docs/operations/linux-operations.md 提供具体命令与故障恢复步骤。</p></details></section>
        <section className="panel section"><h2>后台任务</h2><p>模型任务：{Object.entries(status.jobs).map(([state, count]) => `${labels[state] ?? state} ${count}`).join(" · ") || "暂无"}</p><p>导出任务：{Object.entries(status.exports).map(([state, count]) => `${labels[state] ?? state} ${count}`).join(" · ") || "暂无"}</p><p>调用结果与费用未知的任务保留额度预留，不自动重复调用。</p></section>
      </>}
    </main></>;
}
