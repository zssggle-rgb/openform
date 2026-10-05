import { request } from "./http";

export interface Page<T> { items: T[]; next_cursor: string | null }
export interface ClassEntry { id: string; name: string; active: boolean; revision: number; student_count: number }
export interface StudentEntry { id: string; reference: string; display_name: string; class_id: string | null; class_name: string | null; active: boolean; revision: number; auth_epoch: number; has_code: boolean }
export interface Assignment { account_id: string; display_name: string; subject: string; active: boolean; revision: number; member_eligible: boolean }
export interface StudentSession { workspace_id: string; workspace_name: string; student_id: string; display_name: string; reference: string; csrf_token: string }

export async function getStudentSession(signal?: AbortSignal): Promise<StudentSession> {
  const session = await request<StudentSession>("/api/student-auth/session", { signal });
  if (!session || [session.workspace_id, session.workspace_name, session.student_id, session.display_name, session.reference].some((value) => typeof value !== "string")
    || typeof session.csrf_token !== "string" || !/^[a-f0-9]{64}$/.test(session.csrf_token)) {
    throw new Error("学生身份服务返回了无法识别的内容，请稍后重试。");
  }
  return session;
}

export function routeFromHash(hash: string): { page: string; classId: string | null } {
  const [page, query] = hash.slice(1).split("?");
  const id = new URLSearchParams(query).get("class");
  return { page: page || "T01", classId: id && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id) ? id : null };
}
