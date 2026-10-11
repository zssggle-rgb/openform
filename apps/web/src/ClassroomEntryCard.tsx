import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

export function ClassroomEntryCard({ title, code }: { title: string; code: string }) {
  const url = `${location.origin}/#S01?code=${encodeURIComponent(code)}`;
  const canvas = useRef<HTMLCanvasElement>(null), link = useRef<HTMLInputElement>(null), card = useRef<HTMLElement>(null);
  const [ready, setReady] = useState(false), [notice, setNotice] = useState("");
  useEffect(() => {
    let cancelled = false; setReady(false); setNotice("");
    if (canvas.current) void QRCode.toCanvas(canvas.current, url, { width: 176, margin: 4, errorCorrectionLevel: "M" })
      .then(() => { if (!cancelled) setReady(true); }).catch(() => { if (!cancelled) setNotice("二维码暂未生成，可以使用下方链接。请重新打开课堂后重试。"); });
    return () => { cancelled = true; };
  }, [url]);
  async function copy() {
    try { await navigator.clipboard.writeText(url); setNotice("链接已复制。"); }
    catch { link.current?.focus(); link.current?.select(); setNotice("请选择链接并复制。也可以打开链接或扫描二维码。"); }
  }
  function print() {
    const target = card.current; if (!target || !ready) return;
    const parents: HTMLElement[] = []; let parent = target.parentElement;
    while (parent) { parents.push(parent); parent.classList.add("print-path"); parent = parent.parentElement; }
    target.classList.add("print-target");
    try { window.print(); } finally { target.classList.remove("print-target"); parents.forEach((item) => item.classList.remove("print-path")); }
  }
  return <section ref={card} className="classroom-entry-card"><h2>学生进入课堂</h2><h3>{title}</h3>
    <div className="entry-layout"><canvas ref={canvas} role="img" aria-label={`${title} 的课堂二维码`} />
      <div><p>课堂码 <strong className="classroom-code">{code}</strong></p><p>扫描二维码或打开链接进入课堂。</p><p>快速课堂填写称呼；名单课堂使用教师给你的个人进入码。</p>
        <label>课堂链接<input ref={link} readOnly value={url} onFocus={(event) => event.currentTarget.select()} /></label>
        <div className="row-actions no-print"><button onClick={() => void copy()}>复制链接</button><a href={url} target="_blank" rel="noreferrer">打开学生入口</a><button disabled={!ready} onClick={print}>打印指引卡</button></div>
      </div></div>{notice && <p className="no-print" role="status">{notice}</p>}
  </section>;
}
