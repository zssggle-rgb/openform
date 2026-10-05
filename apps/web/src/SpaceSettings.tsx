import { useEffect, useRef, useState, type FormEvent } from "react";
import { request } from "./http";
import type { Session, Workspace } from "./identity";

interface Policy { revision: number; retention_days: number; model_token_limit: number; image_byte_limit: number; generation_enabled: boolean; analysis_enabled: boolean }
interface Status { policy: Policy; model_configured: boolean; model_id: string; model_usage: { used_tokens: number; reserved_tokens: number }; image_bytes: number; jobs: { status: string; count: number }[]; pending_record_cleanup: number; instance_model_token_limit: number; instance_image_byte_limit: number; backup_status: string }
const jobStates: Record<string, string> = { queued: "等待处理", running: "处理中", succeeded: "已完成", failed: "失败", cancelled: "已取消", outcome_unknown: "调用结果与费用待确认" };

export function SpaceSettings({ session, workspace, onError }: { session: Session; workspace: Workspace; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`;
  const editable = workspace.is_admin;
  const [policy, setPolicy] = useState<Policy | null>(null), [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  async function load(signal = lifetime.current?.signal) {
    if (editable) { const value = await request<Status>(`${base}/status`, { signal }); if (!signal?.aborted) { setStatus(value); setPolicy(value.policy); } }
    else { const value = await request<Policy>(`${base}/policy`, { signal }); if (!signal?.aborted) setPolicy(value); }
  }
  useEffect(() => { const controller = new AbortController(); lifetime.current = controller; void load(controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); }); return () => controller.abort(); }, [base]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const signal = lifetime.current?.signal; if (!policy || !editable || !signal || signal.aborted) return;
    const fields = new FormData(event.currentTarget); setBusy(true); setNotice("");
    try {
      await request(`${base}/policy`, { method: "PATCH", csrf: session.csrf_token, signal, body: {
        expected_revision: policy.revision, retention_days: Number(fields.get("retention_days")), model_token_limit: Number(fields.get("model_token_limit")), image_byte_limit: Number(fields.get("image_byte_limit")),
        generation_enabled: fields.has("generation_enabled"), analysis_enabled: fields.has("analysis_enabled"),
      } });
      await load(signal); if (!signal.aborted) setNotice("空间规则已保存。已有使用量保留；缩短期限会清理已到期资料。");
    } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  return <><div className="page-heading"><div><h1>空间设置与运行状态</h1><p>{workspace.name} · {workspace.kind === "campus" ? "校园" : "个人"}空间</p></div><button disabled={busy} onClick={() => void load().catch(onError)}>刷新状态</button></div>
    {notice && <p className="success-box" role="status">{notice}</p>}
    {!policy ? <p role="status">正在读取空间规则…</p> : <section className="panel"><h2>模型与数据规则</h2>
      {status && <><p>模型：{status.model_id} · {status.model_configured ? "已配置" : "未配置，联系部署管理员"}</p><div className="metric-strip"><span>已结算 {status.model_usage.used_tokens.toLocaleString()} 令牌</span><span>已预留 {status.model_usage.reserved_tokens.toLocaleString()} 令牌</span><span>图片 {(status.image_bytes / 1048576).toFixed(1)} MiB</span><span>待清理课堂 {status.pending_record_cleanup}</span></div><p className="field-help">累计额度不按月自动重置，令牌不是货币费用。密钥由部署管理员配置，不回显。</p></>}
      <form key={policy.revision} className="compact-form" onSubmit={(event) => void save(event)}>
        <label>资料保留天数<input name="retention_days" type="number" min="1" max="3650" required defaultValue={policy.retention_days} disabled={!editable || busy} /></label>
        <p className="field-help">课堂从结束起算；导入历史档案从导入创建起算。缩短期限可能删除已到期资料，下载副本与备份无法召回。</p>
        <label>模型累计令牌上限<input name="model_token_limit" type="number" min="0" max={status?.instance_model_token_limit} required defaultValue={policy.model_token_limit} disabled={!editable || busy} /></label>
        <label>图片容量上限（字节）<input name="image_byte_limit" type="number" min="0" max={status?.instance_image_byte_limit} required defaultValue={policy.image_byte_limit} disabled={!editable || busy} /></label>
        <label className="checkbox-label"><input name="generation_enabled" type="checkbox" defaultChecked={policy.generation_enabled} disabled={!editable || busy} />允许 AI 制作与修改</label>
        <label className="checkbox-label"><input name="analysis_enabled" type="checkbox" defaultChecked={policy.analysis_enabled} disabled={!editable || busy} />允许 AI 教学诊断</label>
        <p>暂停模型不会影响学生提交。已发出的模型调用仍需确认用量。</p>
        {editable ? <><label className="checkbox-label"><input type="checkbox" required disabled={busy} />已核对保留期限及额度变更的影响</label><button className="primary" disabled={busy}>保存空间规则</button></> : <p>当前为只读视图；调整规则请联系校园管理员。</p>}
      </form></section>}
    {status && <section className="panel section"><h2>任务与实例运维</h2>{status.jobs.length ? <ul>{status.jobs.map((item) => <li key={item.status}>{jobStates[item.status] ?? item.status}：{item.count}</li>)}</ul> : <p>暂无模型任务。</p>}<p>{status.backup_status}</p><p>备份恢复属于独立实例运维授权；学校管理权限不能直接恢复整实例。</p></section>}
  </>;
}
