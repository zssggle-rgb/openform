import { useEffect, useRef, useState, type FormEvent } from "react";
import { request } from "./http";
import type { Member, Session, Workspace } from "./identity";
import type { Page } from "./roster";

interface Asset { id: string; kind: string; title: string; owner_id: string; owner_name: string; owner_eligible: boolean; creator_id: string; revision: number }
interface Event { id: string; action: string; target_id: string; actor_name: string | null; created_at: string }
const kinds: Record<string, string> = { activity: "教学活动", classroom: "课堂", archive: "历史档案" };
const actions: Record<string, string> = { "object.transferred": "资产交接", "workspace.policy-changed": "空间规则调整", "records.deleted": "课堂资料删除", "records.expired": "课堂资料到期", "archive.deleted": "历史档案删除", "archive.expired": "历史档案到期", "transfer.imported": "资料导入", "export.requested": "资料导出申请" };

export function AssetsView({ session, workspace, onError }: { session: Session; workspace: Workspace; onError: (error: unknown) => void }) {
  const base = `/api/workspaces/${workspace.id}`;
  const lifetime = useRef<AbortController | null>(null);
  const controller = { get signal() { return lifetime.current?.signal; } };
  const [assets, setAssets] = useState<Asset[]>([]), [members, setMembers] = useState<Member[]>([]), [events, setEvents] = useState<Event[]>([]);
  const [cursor, setCursor] = useState<string | null>(null), [memberCursor, setMemberCursor] = useState<string | null>(null), [eventCursor, setEventCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<Asset | null>(null), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  async function load(signal = lifetime.current?.signal) {
    const [a, m, e] = await Promise.all([request<Page<Asset>>(`${base}/assets`, { signal }), request<Page<Member>>(`${base}/members`, { signal }), request<Page<Event>>(`${base}/audit`, { signal })]);
    if (!signal?.aborted) { setAssets(a.items); setCursor(a.next_cursor); setMembers(m.items); setMemberCursor(m.next_cursor); setEvents(e.items); setEventCursor(e.next_cursor); setLoading(false); }
  }
  useEffect(() => { const current = new AbortController(); lifetime.current = current; void load(current.signal).catch((error) => { if (!current.signal.aborted) { setLoading(false); onError(error); } }); return () => current.abort(); }, [base]);
  async function act(run: () => Promise<void>) { const signal = lifetime.current?.signal; if (!signal || signal.aborted) return; setBusy(true); try { await run(); } catch (error) { if (!signal.aborted) onError(error); } finally { if (!signal.aborted) setBusy(false); } }
  async function transfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const recipient = new FormData(event.currentTarget).get("recipient");
    await act(async () => {
      await request(`${base}/assets/${selected.id}/transfer`, { method: "POST", csrf: session.csrf_token, signal: controller.signal, body: { expected_revision: selected.revision, expected_owner: selected.owner_id, recipient_id: recipient, confirmed: true } });
      await load(); if (!controller.signal?.aborted) { setSelected(null); setNotice("资产已交接，旧协作授权已撤销。固定版本和原作者记录保留。"); }
    });
  }
  return <><div className="page-heading"><div><h1>校园资产与交接</h1><p>管理员管理归属；查看学生答案仍需明确教学授权。</p></div><button disabled={busy} onClick={() => void act(load)}>刷新资产</button></div>
    {notice && <p role="status" className="success-box">{notice}</p>}
    <section className="panel table-scroll">{loading ? <p role="status">正在加载校园资产…</p> : <table><thead><tr><th>资产</th><th>类型</th><th>当前教师</th><th>操作</th></tr></thead><tbody>{assets.map((asset) => <tr key={asset.id}><td>{asset.title}</td><td>{kinds[asset.kind] ?? asset.kind}</td><td>{asset.owner_name} · {asset.owner_eligible ? "有效" : "已停用 / 无教学角色"}</td><td><button disabled={busy} onClick={() => { setSelected(asset); setNotice(""); }}>交接资产</button></td></tr>)}{!assets.length && <tr><td colSpan={4}>暂无可交接资产。</td></tr>}</tbody></table>}
      {cursor && <button disabled={busy} onClick={() => void act(async () => { const page = await request<Page<Asset>>(`${base}/assets?cursor=${cursor}`, { signal: controller.signal }); if (!controller.signal?.aborted) { setAssets((items) => [...items, ...page.items]); setCursor(page.next_cursor); } })}>加载更多资产</button>}</section>
    {selected && <section className="panel section"><h2>交接 {selected.title}</h2><p>当前归属：{selected.owner_name}。交接后旧教师失去默认访问权，所有旧协作授权撤销；原作者与固定版本保留。班级课堂接收者须有当前任课权限。</p>
      <form key={selected.id} className="compact-form" onSubmit={(event) => void transfer(event)}><label>接收教师<select name="recipient" required defaultValue="" disabled={busy}><option value="" disabled>选择本校有效教师</option>{members.filter((member) => member.active && member.is_teacher && member.account_id !== selected.owner_id).map((member) => <option key={member.account_id} value={member.account_id}>{member.display_name} · {member.login}</option>)}</select></label>
        {memberCursor && <button type="button" disabled={busy} onClick={() => void act(async () => { const page = await request<Page<Member>>(`${base}/members?cursor=${memberCursor}`, { signal: controller.signal }); if (!controller.signal?.aborted) { setMembers((items) => [...items, ...page.items]); setMemberCursor(page.next_cursor); } })}>加载更多接收教师</button>}
        <label className="checkbox-label"><input type="checkbox" required disabled={busy} />确认交接此资产并撤销原协作授权</label><div className="row-actions"><button className="primary" disabled={busy}>确认交接</button><button type="button" disabled={busy} onClick={() => setSelected(null)}>取消</button></div></form></section>}
    <section className="panel section"><h2>管理操作记录</h2><p>仅列管理元数据，不包含学生回答或密钥。</p>{events.map((event) => <div className="list-row" key={event.id}><strong>{actions[event.action] ?? event.action}</strong><span>{event.actor_name ?? "系统 / 受限身份"}</span><time>{new Date(event.created_at).toLocaleString()}</time></div>)}{!events.length && <p>暂无记录。</p>}
      {eventCursor && <button disabled={busy} onClick={() => void act(async () => { const page = await request<Page<Event>>(`${base}/audit?cursor=${eventCursor}`, { signal: controller.signal }); if (!controller.signal?.aborted) { setEvents((items) => [...items, ...page.items]); setEventCursor(page.next_cursor); } })}>加载更多操作记录</button>}</section>
  </>;
}
