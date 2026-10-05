import { useEffect, useRef, useState, type FormEvent } from "react";
import { request, RequestError } from "./http";
import type { Session } from "./identity";

interface PublicationState { revision: number; active: boolean; versions: { id: string; subject: string; grade: string }[] }

export function ResourcePublication({ base, activity, session, onError }: {
  base: string; activity: { id: string; versions: { id: string; number: number }[] }; session: Session; onError: (error: unknown) => void;
}) {
  const [state, setState] = useState<PublicationState | null>(null), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [versionId, setVersionId] = useState(activity.versions[0]?.id ?? "");
  const savedTags = state?.versions.find((version) => version.id === versionId);
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller; setState(null); setNotice("");
    void request<PublicationState>(`${base}/activities/${activity.id}/resource`, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setState(value); })
      .catch((error) => { if (!controller.signal.aborted && !(error instanceof RequestError && error.status === 403)) onError(error); });
    return () => controller.abort();
  }, [base, activity.id]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const signal = lifetime.current?.signal; if (!state || !signal || signal.aborted) return;
    const form = new FormData(event.currentTarget); setBusy(true); setNotice("");
    try {
      await request(`${base}/activities/${activity.id}/resource`, { method: "POST", csrf: session.csrf_token, signal,
        body: { version_id: form.get("version_id"), subject: form.get("subject"), grade: form.get("grade"), expected_revision: state.revision } });
      const current = await request<PublicationState>(`${base}/activities/${activity.id}/resource`, { signal });
      if (!signal.aborted) { setState(current); setNotice("固定版本已发布到本校资源库，同事可复制；课堂记录和学生数据不会共享。"); }
    } catch (error) {
      if (!signal.aborted) {
        onError(error);
        try { const current = await request<PublicationState>(`${base}/activities/${activity.id}/resource`, { signal }); if (!signal.aborted) setState(current); }
        catch (reloadError) { if (!signal.aborted) onError(reloadError); }
      }
    }
    finally { if (!signal.aborted) setBusy(false); }
  }
  return <details className="section"><summary>发布到校内资源库</summary>
    {state ? <form key={`${versionId}:${state.revision}`} className="compact-form" onSubmit={(event) => void submit(event)}>
      <p>{state.active ? "已有校内发布，新固定版本可加入同一资源。" : "本校有效教师可发现和复制已验证固定版本。"}标签随版本保存，副本不跟随源更新。</p>
      <label>固定版本<select name="version_id" defaultValue={versionId} onChange={(event) => setVersionId(event.target.value)} disabled={busy}>{activity.versions.map((version) => <option key={version.id} value={version.id}>v{version.number}</option>)}</select></label>
      {savedTags && <p>已有版本的标签不可变；可重新开放已撤回资源。需要新标签时请先发布新固定版本。</p>}
      <label>学科<input name="subject" maxLength={40} defaultValue={savedTags?.subject ?? ""} readOnly={Boolean(savedTags)} disabled={busy} placeholder="例如：英语" /></label><label>年级<input name="grade" maxLength={40} defaultValue={savedTags?.grade ?? ""} readOnly={Boolean(savedTags)} disabled={busy} placeholder="例如：一年级" /></label>
      <button className="primary" disabled={busy || !activity.versions.length}>{savedTags ? "重新开放该固定资源" : "发布校内资源"}</button>
    </form> : <p>需要该活动的资源发布权；先发布至少一个真实试做通过的固定版本。</p>}
    {notice && <p role="status" className="success-box">{notice}</p>}
  </details>;
}
