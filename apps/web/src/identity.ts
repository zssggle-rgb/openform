import { request } from "./http";

export interface Workspace { id: string; name: string; kind: "personal" | "campus"; active: boolean; is_teacher: boolean; is_admin: boolean }
export interface Session { account_id: string; display_name: string; csrf_token: string; workspaces: Workspace[] }
export interface Member { account_id: string; display_name: string; login: string; is_teacher: boolean; is_admin: boolean; active: boolean; auth_epoch: number }
export interface Invitation { id: string; is_teacher: boolean; is_admin: boolean; target_login: string | null; expires_at: string; active: boolean; accepted: boolean }

export async function getSession(signal?: AbortSignal): Promise<Session> {
  const session = await request<Session>("/api/auth/session", { signal });
  if (!session || typeof session.account_id !== "string" || typeof session.display_name !== "string"
    || typeof session.csrf_token !== "string" || !/^[a-f0-9]{64}$/.test(session.csrf_token)
    || !Array.isArray(session.workspaces) || session.workspaces.some((workspace) => !workspace
      || typeof workspace.id !== "string" || typeof workspace.name !== "string"
      || !["personal", "campus"].includes(workspace.kind) || typeof workspace.active !== "boolean"
      || typeof workspace.is_teacher !== "boolean" || typeof workspace.is_admin !== "boolean")) {
    throw new Error("账号服务返回了无法识别的内容，请稍后重试。");
  }
  return session;
}

export function invitationFromHash(hash: string): string | null {
  const token = new URLSearchParams(hash.split("?")[1] ?? "").get("invite");
  return token && /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
}
