import { useEffect, useRef, useState } from "react";
import { request } from "./http";

interface Summary { shared_text: string; captured_at: string; shared_at: string; coverage: { included: number; total_completed: number; omitted: number } }

export function SharedSummary({ base, classroomId, onError }: { base: string; classroomId: string; onError: (error: unknown) => void }) {
  const [items, setItems] = useState<Summary[]>([]), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const lifetime = useRef<AbortController | null>(null);
  async function load(signal: AbortSignal) {
    try { const value = await request<{ items: Summary[] }>(`${base}/classrooms/${classroomId}/shared-summary`, { signal }); if (!signal.aborted) { setItems(value.items); setFailed(false); } }
    catch (error) { if (!signal.aborted) setFailed(true); throw error; }
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    setLoading(true); setFailed(false); setItems([]);
    void load(controller.signal).catch((error) => { if (!controller.signal.aborted) onError(error); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, classroomId]);
  async function refresh() { const signal = lifetime.current?.signal; if (!signal || signal.aborted) return; setBusy(true); try { await load(signal); } catch (error) { if (!signal.aborted) onError(error); } finally { if (!signal.aborted) setBusy(false); } }
  return <section className="section"><h2>课堂总结</h2><button disabled={busy || loading} onClick={() => void refresh()}>刷新总结</button>{loading ? <p role="status">正在读取总结…</p> : failed ? <p>总结暂时未能读取，请重试。</p> : items.length ? items.map((item, index) => <article key={index}><p className="answer-data">{item.shared_text}</p><p className="field-help">教师发布于 {new Date(item.shared_at).toLocaleString()}</p></article>) : <p>老师还没有发布课堂总结。</p>}</section>;
}
