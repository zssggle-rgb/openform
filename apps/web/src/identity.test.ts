import { afterEach, expect, it, vi } from "vitest";
import { getSession, invitationFromHash } from "./identity";

afterEach(() => vi.unstubAllGlobals());

it("accepts only the actual session shape and validates workspace privileges", async () => {
  const session = { account_id: "synthetic-id", display_name: "合成老师", csrf_token: "a".repeat(64),
    workspaces: [{ id: "space", name: "个人空间", kind: "personal", active: true, is_teacher: true, is_admin: true }] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(session))));
  await expect(getSession()).resolves.toEqual(session);
  for (const body of [null, {}, { ...session, csrf_token: "bad" }, { ...session, workspaces: [{}] }, { ...session, workspaces: null }]) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
    await expect(getSession()).rejects.toThrow("无法识别");
  }
});

it("reads invitations only from fragment parameters and rejects malformed credentials", () => {
  const token = "A".repeat(43);
  expect(invitationFromHash(`#G01?invite=${token}`)).toBe(token);
  expect(invitationFromHash("#G01")).toBeNull();
  expect(invitationFromHash("#G01?invite=short")).toBeNull();
  expect(invitationFromHash("#G01?invite=" + "!".repeat(43))).toBeNull();
});
