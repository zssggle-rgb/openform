import { useEffect, useRef, useState, type FormEvent } from "react";
import { RequestError, request } from "./http";
import type { Session, Workspace } from "./identity";
import type { Page } from "./roster";

type Props = { session: Session; workspace: Workspace; onError: (error: unknown) => void };
interface Export { id: string; kind: string; status: string; byte_size: number; error_message: string | null; expires_at?: string }
interface Summary { format: string; title: string; source: { exported_at: string }; versions: { number: number; title: string }[]; record_count: number; image_count: number; effect: string }
interface Import { id: string; status: string; digest: string; result_id: string | null; summary: Summary }
interface Archive { id: string; title: string; record_count: number; deleted_at: string | null }
interface ArchiveDetail { id: string; title: string; version_number: number; source: { exported_at: string }; records: Page<{ id: string; body: { display_name: string; attempt_number: number; created_at: string; data: unknown; receipt_id: string; images: { source_file_id: string }[] } }> }
const states: Record<string, string> = { queued: "等待生成", running: "正在生成", succeeded: "可下载", failed: "生成失败", invalidated: "已失效", validated: "预检通过，待确认", committed: "已导入", expired: "已过期" };

export function ExportAction({ session, workspace, onError, objectId, kind, epoch, version }: Props & { objectId: string; kind: "resource" | "archive"; epoch?: number; version?: number }) {
  const [busy, setBusy] = useState(false);
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => { const controller = new AbortController(); lifetime.current = controller; return () => controller.abort(); }, [objectId]);
  async function create() {
    const signal = lifetime.current?.signal; if (!signal || signal.aborted) return;
    setBusy(true); const key = `openform.export.${session.account_id}.${workspace.id}.${objectId}.${kind}.${version ?? "all"}.${epoch ?? "none"}`;
    try {
      const requestKey = sessionStorage.getItem(key) ?? crypto.randomUUID(); sessionStorage.setItem(key, requestKey);
      await request(`/api/workspaces/${workspace.id}/transfers/exports`, { method: "POST", csrf: session.csrf_token, signal, body: { kind, object_id: objectId, request_key: requestKey, expected_data_epoch: epoch ?? null, version_number: version ?? null } });
      sessionStorage.removeItem(key); if (!signal.aborted) location.hash = "#T12";
    } catch (error) { if (!signal.aborted) onError(error); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  return <button disabled={busy} onClick={() => void create()}>{busy ? "正在提交导出…" : kind === "resource" ? "导出教学资源包" : "导出受限课堂档案"}</button>;
}

export function TransferView({ session, workspace, onError, archiveId }: Props & { archiveId?: string | null }) {
  const base = `/api/workspaces/${workspace.id}`;
  const lifetime = useRef<AbortController | null>(null);
  const [exports, setExports] = useState<Export[]>([]), [imports, setImports] = useState<Import[]>([]), [archives, setArchives] = useState<Archive[]>([]);
  const [exportCursor, setExportCursor] = useState<string | null>(null), [importCursor, setImportCursor] = useState<string | null>(null), [archiveCursor, setArchiveCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<Import | null>(null), [archive, setArchive] = useState<ArchiveDetail | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [tab, setTab] = useState(archiveId ? "archives" : "tasks");
  async function load(signal: AbortSignal) {
    const [e, i, a] = await Promise.all([request<Page<Export>>(`${base}/transfers/exports`, { signal }), request<Page<Import>>(`${base}/transfers/imports`, { signal }), request<Page<Archive>>(`${base}/archives`, { signal })]);
    const storageKey = `openform.upload.${session.account_id}.${workspace.id}`;
    const stored = sessionStorage.getItem(storageKey);
    if (stored) {
      const pending: { key: string } = JSON.parse(stored);
      if (typeof pending.key !== "string" || !/^[a-f0-9-]{36}$/i.test(pending.key)) throw new Error("上传恢复信息无法读取，请刷新并检查服务端导入记录。");
      const recovered = await request<Page<Import>>(`${base}/transfers/imports?request_key=${encodeURIComponent(pending.key)}`, { signal });
      if (!signal.aborted && recovered.items.length) { sessionStorage.removeItem(storageKey); for (const item of recovered.items) if (!i.items.some((row) => row.id === item.id)) i.items.unshift(item); }
    }
    if (!signal.aborted) { setExports(e.items); setExportCursor(e.next_cursor); setImports(i.items); setImportCursor(i.next_cursor); setArchives(a.items); setArchiveCursor(a.next_cursor); setLoading(false); }
  }
  useEffect(() => { const controller = new AbortController(); lifetime.current = controller; void load(controller.signal).catch((error) => { if (!controller.signal.aborted) { onError(error); setLoading(false); } }); return () => controller.abort(); }, [base]);
  useEffect(() => {
    setArchive(null); if (!archiveId) { setTab("tasks"); return; }
    const controller = new AbortController(); setTab("archives");
    void request<ArchiveDetail>(`${base}/archives/${archiveId}`, { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setArchive(value); }).catch((error) => { if (!controller.signal.aborted) onError(error); });
    return () => controller.abort();
  }, [base, archiveId]);
  async function act(run: (signal: AbortSignal) => Promise<void>) { const signal = lifetime.current?.signal; if (!signal || signal.aborted) return; setBusy(true); setNotice(""); try { await run(signal); } catch (error) { if (!signal.aborted) onError(error); } finally { if (!signal.aborted) setBusy(false); } }
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const file = new FormData(event.currentTarget).get("package");
    if (!(file instanceof File) || !file.size || file.size > 20 * 1048576) { onError(new Error("请选择不超过 20 MiB 的 OpenForm ZIP 包。")); return; }
    await act(async (signal) => {
      const storageKey = `openform.upload.${session.account_id}.${workspace.id}`;
      const descriptor = `${file.name}:${file.size}:${file.lastModified}`;
      const stored = sessionStorage.getItem(storageKey);
      const pending: { descriptor: string; key: string } = stored ? JSON.parse(stored) : { descriptor, key: crypto.randomUUID() };
      if (pending.descriptor !== descriptor) throw new Error("上一次上传结果尚未确认。请先刷新任务列表查看，或重新选择原文件恢复上传。");
      sessionStorage.setItem(storageKey, JSON.stringify(pending));
      const controller = new AbortController(); const cancel = () => controller.abort(); signal.addEventListener("abort", cancel, { once: true });
      const timeout = setTimeout(cancel, 90000);
      try {
        const response = await fetch(`${base}/transfers/uploads/${pending.key}`, { method: "PUT", credentials: "same-origin", signal: controller.signal, headers: { "X-CSRF-Token": session.csrf_token, "Content-Type": "application/zip" }, body: file });
        const value = await response.json();
        if (!response.ok) { if (response.status >= 400 && response.status < 500) sessionStorage.removeItem(storageKey); throw new RequestError(response.status, value.code ?? "IMPORT_FAILED", value.message ?? "预检失败，未导入。"); }
        sessionStorage.removeItem(storageKey);
        if (!signal.aborted) { setSelected(value as Import); setNotice("预检完成，尚未创建活动或档案。请核对后确认导入。"); await load(signal); }
      } catch (error) { if (error instanceof RequestError) throw error; throw new Error("上传结果尚未确认，请刷新任务列表；重试上传时沿用原文件，不会重复建立预检。"); }
      finally { clearTimeout(timeout); signal.removeEventListener("abort", cancel); }
    });
  }
  async function commit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const version = Number(new FormData(event.currentTarget).get("version"));
    await act(async (signal) => {
      const result = await request<{ id: string; kind: string }>(`${base}/transfers/imports/${selected.id}/commit`, { method: "POST", csrf: session.csrf_token, signal, body: { confirmed: true, digest: selected.digest, version_number: version } });
      if (!signal.aborted) { setSelected(null); location.hash = result.kind === "resource" ? `#T03?activity=${result.id}` : `#T12?archive=${result.id}`; }
    });
  }
  return <><div className="page-heading"><div><h1>资料迁移与历史档案</h1><p>{workspace.name} · 资源与学生记录分开迁移</p></div><button disabled={busy} onClick={() => void act(load)}>刷新任务状态</button></div>
    <div className="tab-bar"><button aria-pressed={tab === "tasks"} onClick={() => { setTab("tasks"); }}>导入导出任务</button><button aria-pressed={tab === "archives"} onClick={() => setTab("archives")}>历史档案</button></div>
    {notice && <p className="success-box" role="status">{notice}</p>}{loading && <p role="status">正在加载迁移资料…</p>}
    {tab === "tasks" ? <><section className="panel section"><h2>导入迁移包</h2><p>教学资源不含学生记录；课堂档案仅供授权查阅，不关联当前学生、不参与当前统计。</p><form className="compact-form" onSubmit={(event) => void upload(event)}><label>OpenForm ZIP 包<input name="package" type="file" accept=".zip,application/zip" required disabled={busy} /></label><p className="field-help">最多 20 MiB，仅支持 resource/1 与 archive/1；不支持未知 QuickForm 历史包。</p><button className="primary" disabled={busy}>{busy ? "正在处理…" : "上传并预检"}</button></form></section>
      {selected && <section className="panel section"><h2>确认导入 · {selected.summary.title}</h2><p>{selected.summary.format.includes("resource") ? "教学资源包" : "课堂档案包"} · {selected.summary.versions.length} 个来源版本 · {selected.summary.record_count} 份记录 · {selected.summary.image_count} 个图片引用</p><p>来源导出时间：{selected.summary.source.exported_at}</p><p>{selected.summary.effect}</p><form key={selected.id} className="compact-form" onSubmit={(event) => void commit(event)}><label>使用来源版本<select name="version" defaultValue={Math.max(...selected.summary.versions.map((version) => version.number))} disabled={busy}>{selected.summary.versions.map((version) => <option key={version.number} value={version.number}>v{version.number} · {version.title}</option>)}</select></label><label className="checkbox-label"><input type="checkbox" required disabled={busy} />已核对内容范围，确认创建独立草稿或只读档案</label><div className="row-actions"><button className="primary" disabled={busy}>确认导入</button><button type="button" disabled={busy} onClick={() => setSelected(null)}>暂不导入</button></div></form></section>}
      <section className="panel section"><h2>我的导出任务</h2><p>从活动详情或课堂结果选择导出。只有文件生成完成且仍有权限时可下载；文件保留 24 小时。</p>{exports.map((item) => <div className="list-row" key={item.id}><strong>{item.kind === "resource" ? "教学资源包" : "受限课堂档案"}</strong><span>{states[item.status] ?? item.status}</span>{item.status === "succeeded" && <a href={`${base}/transfers/exports/${item.id}/file`}>下载 ZIP（{(item.byte_size / 1024).toFixed(1)} KiB）</a>}{item.error_message && <p>{item.error_message}</p>}</div>)}{!exports.length && !loading && <p>暂无导出任务。</p>}{exportCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Export>>(`${base}/transfers/exports?cursor=${exportCursor}`, { signal }); if (!signal.aborted) { setExports((items) => [...items, ...page.items]); setExportCursor(page.next_cursor); } })}>加载更多导出</button>}</section>
      <section className="panel section"><h2>我的导入记录</h2>{imports.map((item) => <div className="list-row" key={item.id}><strong>{item.summary.title}</strong><span>{states[item.status]}</span>{item.status === "validated" && <button disabled={busy} onClick={() => void act(async (signal) => { const detail = await request<Import>(`${base}/transfers/imports/${item.id}`, { signal }); if (!signal.aborted) setSelected(detail); })}>核对预检</button>}{item.status === "committed" && <a href={item.summary.format.includes("resource") ? `#T03?activity=${item.result_id}` : `#T12?archive=${item.result_id}`}>打开导入结果</a>}</div>)}{!imports.length && !loading && <p>暂无导入记录。</p>}{importCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Import>>(`${base}/transfers/imports?cursor=${importCursor}`, { signal }); if (!signal.aborted) { setImports((items) => [...items, ...page.items]); setImportCursor(page.next_cursor); } })}>加载更多导入</button>}</section></> : <>
      <section className="panel section"><h2>受限历史档案</h2><p>姓名和原参与标识只作为来源标签，不与当前校园学生匹配。档案不能用于新课堂提交。</p>{archives.map((item) => <div className="list-row" key={item.id}><strong>{item.title}</strong><span>{item.deleted_at ? "已删除 / 保留到期" : `${item.record_count} 份历史提交`}</span>{!item.deleted_at && <a href={`#T12?archive=${item.id}`}>查看只读档案</a>}</div>)}{!archives.length && !loading && <p>暂无历史档案。导入 archive/1 包后在此查阅。</p>}{archiveCursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<Page<Archive>>(`${base}/archives?cursor=${archiveCursor}`, { signal }); if (!signal.aborted) { setArchives((items) => [...items, ...page.items]); setArchiveCursor(page.next_cursor); } })}>加载更多档案</button>}</section>
      {archive && <section className="panel section"><div className="roster-tools"><h2>{archive.title} · 只读 · v{archive.version_number}</h2><a href="#T12">返回任务列表</a></div><p>来源导出时间：{archive.source.exported_at}</p><ExportAction session={session} workspace={workspace} onError={onError} objectId={archive.id} kind="archive" epoch={0} />
        {archive.records.items.map((record) => <details key={record.id}><summary>{record.body.display_name} · 第 {record.body.attempt_number} 次尝试</summary><p>{record.body.created_at} · 回执 {record.body.receipt_id}</p><pre className="answer-data">{JSON.stringify(record.body.data, null, 2)}</pre>{record.body.images.map((image) => <a key={image.source_file_id} target="_blank" rel="noreferrer" href={`${base}/archives/${archive.id}/records/${record.id}/files/${image.source_file_id}`}><img className="evidence-image" alt="历史提交图片" src={`${base}/archives/${archive.id}/records/${record.id}/files/${image.source_file_id}`} /></a>)}</details>)}
        {archive.records.next_cursor && <button disabled={busy} onClick={() => void act(async (signal) => { const page = await request<ArchiveDetail>(`${base}/archives/${archive.id}?cursor=${archive.records.next_cursor}`, { signal }); if (!signal.aborted) setArchive((current) => current && current.id === page.id ? { ...page, records: { ...page.records, items: [...current.records.items, ...page.records.items] } } : current); })}>加载更多历史记录</button>}
        <details><summary>删除此历史档案</summary><p>删除后正文与图片不再可读；已下载和备份副本无法召回。</p><form onSubmit={(event) => { event.preventDefault(); void act(async (signal) => { await request(`${base}/archives/${archive.id}`, { method: "DELETE", csrf: session.csrf_token, signal, body: { confirmed: true, expected_data_epoch: 0 } }); if (!signal.aborted) { setArchive(null); location.hash = "#T12"; await load(signal); setNotice("历史档案已删除。"); } }); }}><label className="checkbox-label"><input type="checkbox" required disabled={busy} />确认删除此档案全部记录和图片</label><button disabled={busy}>确认删除历史档案</button></form></details></section>}
    </>}
  </>;
}
