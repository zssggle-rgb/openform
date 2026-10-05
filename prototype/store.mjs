import { SCHEMA, seedState, command } from './model.mjs';

export const STATE_KEY = 'openform-integrated-v1';
const ACTOR_KEY = 'openform-integrated-actor';
const listeners = new Set();

export function readState() {
  const raw = localStorage.getItem(STATE_KEY);
  if (!raw) {
    const initial = seedState();
    localStorage.setItem(STATE_KEY, JSON.stringify(initial));
    return initial;
  }
  const value = JSON.parse(raw);
  if (value.schema !== SCHEMA) throw new Error('演示数据版本不兼容，请在演示入口重置数据。');
  return value;
}

export function readActor() {
  try { return JSON.parse(sessionStorage.getItem(ACTOR_KEY) || 'null'); }
  catch { return null; }
}

export function setActor(actor) {
  if (actor) sessionStorage.setItem(ACTOR_KEY,JSON.stringify(actor));
  else sessionStorage.removeItem(ACTOR_KEY);
}

export async function transact(actor, type, data = {}) {
  const run = () => {
    const { state, result } = command(readState(),actor,type,data,{ id: crypto.randomUUID(), now: new Date().toISOString() });
    try { localStorage.setItem(STATE_KEY,JSON.stringify(state)); }
    catch { throw new Error('本机存储未完成，尚未确认成功。请减少图片或清理浏览器空间后重试。'); }
    listeners.forEach(listener => listener(state));
    return result;
  };
  if (!navigator.locks) throw new Error('当前浏览器不支持此原型的多窗口保存，请使用本机 Chrome 或 Edge。');
  return navigator.locks.request(STATE_KEY,run);
}

export async function resetDemo() {
  await navigator.locks.request(STATE_KEY,() => localStorage.setItem(STATE_KEY,JSON.stringify(seedState())));
  setActor(null);
  listeners.forEach(listener => listener(readState()));
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

window.addEventListener('storage',event => {
  if (event.key === STATE_KEY) {
    try { listeners.forEach(listener => listener(readState())); }
    catch { location.reload(); }
  }
});
