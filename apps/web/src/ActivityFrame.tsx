import { useEffect, useRef, useState } from "react";
import { connectActivityFrame, type BridgeHandler, type BridgeMethod, type BridgeState } from "../runtime/bridge";

interface ActivityFrameProps {
  title: string;
  runtimeOrigin: string;
  runtimeUrl: string;
  capabilities: readonly BridgeMethod[];
  handler: BridgeHandler;
}

export function ActivityFrame({ title, runtimeOrigin, runtimeUrl, capabilities, handler }: ActivityFrameProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<BridgeState>("connecting");
  useEffect(() => {
    if (!frame.current) return;
    try {
      return connectActivityFrame(frame.current, { runtimeOrigin, runtimeUrl, capabilities, handler, onState: setState });
    } catch { setState("unavailable"); }
  }, [runtimeOrigin, runtimeUrl, capabilities, handler]);
  return <section className="activity-runtime" aria-label={title}>
    <p role="status">{state === "connecting" ? "正在连接活动页面…" : state === "connected" ? "活动页面通信已建立" : "活动页面连接已中断，请重新打开活动。"}</p>
    <iframe ref={frame} title={title} sandbox="allow-scripts" referrerPolicy="no-referrer" />
  </section>;
}
