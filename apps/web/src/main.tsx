import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import logo from "../../../assets/brand/svg/openform-logo-primary.svg";
import { checkReady, type Readiness } from "./api";
import "./styles.css";

function App() {
  const [status, setStatus] = useState<Readiness | "loading">("loading");
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    void checkReady(controller.signal).then((result) => {
      clearTimeout(timeout);
      if (active) setStatus(result);
    });
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, []);
  return <>
    <header><img src={logo} width="152" alt="OpenForm" /></header>
    <main className="setup-panel">
      <h1>OpenForm 开发环境</h1>
      <p>教师与校园共用的课堂活动平台。账号和课堂功能正在开发中。</p>
      <p role="status">{status === "loading" ? "正在检查服务…" : status === "ready" ? "API 与数据库已就绪" : "服务暂未就绪，请稍后重试。"}</p>
    </main>
  </>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
