import { useEffect, useRef, useState } from "react";
import { request } from "./http";

interface Summary { shared_text: string; captured_at: string; shared_at: string; coverage: { included: number; total_completed: number; omitted: number } }

export function SharedSummary({ base, classroomId, onError }: { base: string; classroomId: string; onError: (error: unknown) => void }) {
  const [items, setItems] = useState<Summary[]>([]), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const lifetime = useRef<AbortController | null>(null);
  async function load(signal: AbortSignal) { const value = await request<{ items: Summary[] }>(`${base}/classrooms/${classroomId}/shared-summary`, { signal }); if (!signal.aborted) setItems(value.items); }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    void load(controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, classroomId]);
  async function refresh() { const signal = lifetime.current?.signal; if (!signal || signal.aborted) return; setBusy(true); try { await load(signal); } catch (error) { if (!signal.aborted) onError(error); } finally { if (!signal.aborted) setBusy(false); } }
  return <section className="section"><h2>教师共享的课堂摘要</h2>{items.length > 0 && <p><a href={`#S05?classroom=${classroomId}`}>打开共享结果</a></p>}<button disabled={busy} onClick={() => void refresh()}>刷新摘要</button>{loading ? <p>正在读取摘要…</p> : items.length ? items.map((item, index) => <article key={index}><p className="answer-data">{item.shared_text}</p><p className="field-help">快照截至 {new Date(item.captured_at).toLocaleString()} · 覆盖 {item.coverage.included}/{item.coverage.total_completed}，遗漏 {item.coverage.omitted} · 已经教师复核</p></article>) : <p>教师尚未发布共享摘要，个人作答不会自动公开。</p>}</section>;
}
