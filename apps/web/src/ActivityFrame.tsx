import { useEffect, useRef, useState } from "react";
import { connectActivityFrame, type BridgeHandler, type BridgeMethod, type BridgeState } from "../runtime/bridge";

interface ActivityFrameProps {
  title: string;
  runtimeOrigin: string;
  runtimeUrl: string;
  capabilities: readonly BridgeMethod[];
  handler: BridgeHandler;
  interactionDisabled?: boolean;
}

export function ActivityFrame({ title, runtimeOrigin, runtimeUrl, capabilities, handler, interactionDisabled = false }: ActivityFrameProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<BridgeState>("connecting");
  useEffect(() => {
    if (!frame.current) return;
    try {
      return connectActivityFrame(frame.current, { runtimeOrigin, runtimeUrl, capabilities, handler, onState: setState });
    } catch { setState("unavailable"); }
  }, [runtimeOrigin, runtimeUrl, capabilities, handler]);
  return <section className="activity-runtime" aria-label={title} inert={interactionDisabled}>
    {state !== "connected" && <p role="status">{state === "connecting" ? "正在打开活动…" : "暂时无法打开活动，请重新进入。"}</p>}
    <iframe ref={frame} title={title} sandbox="allow-scripts" referrerPolicy="no-referrer" />
  </section>;
}
