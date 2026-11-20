export interface User { id: number; email: string; role: "admin" | "user" }
export interface Citation {
  n: number; doc_id: number; doc_title: string; page: number | null; heading: string; snippet: string;
}
export interface Msg { role: "user" | "assistant"; content: string; citations: Citation[] }
export interface Doc {
  id: number; title: string; filename: string; tag: string; version: number;
  status: "processing" | "ready" | "failed"; error: string; n_chunks: number; created_at: string;
}

const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

const LS = "rag_auth";
export interface Auth { access_token: string; refresh_token: string; user: User }

export const getAuth = (): Auth | null => {
  try { return JSON.parse(localStorage.getItem(LS) || "null"); } catch { return null; }
};
export const setAuth = (a: Auth | null) =>
  a ? localStorage.setItem(LS, JSON.stringify(a)) : localStorage.removeItem(LS);

async function refresh(): Promise<boolean> {
  const a = getAuth();
  if (!a) return false;
  const r = await fetch(`${BASE}/api/auth/refresh`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: a.refresh_token }),
  });
  if (!r.ok) { setAuth(null); return false; }
  setAuth(await r.json());
  return true;
}

export async function api<T = any>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const a = getAuth();
  const headers: Record<string, string> = { ...(init.headers as any) };
  if (a) headers.Authorization = `Bearer ${a.access_token}`;
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const r = await fetch(`${BASE}${path}`, { ...init, headers });
  if (r.status === 401 && retry && a && (await refresh())) return api<T>(path, init, false);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export const login = (email: string, password: string, register: boolean) =>
  api<Auth>(`/api/auth/${register ? "register" : "login"}`, {
    method: "POST", body: JSON.stringify({ email, password }),
  });

/** Streams a chat answer over WebSocket. Resolves when the server sends `done`/`error`. */
export function streamChat(
  message: string, conversationId: number | null,
  on: { token: (t: string) => void; start: (id: number) => void; done: (c: Citation[], text: string) => void },
): Promise<void> {
  return new Promise(async (resolve, reject) => {
    await refresh().catch(() => {}); // fresh access token before opening the socket
    const a = getAuth();
    if (!a) return reject(new Error("Not signed in"));
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const wsBase = BASE ? BASE.replace(/^http/, "ws") : `${proto}://${location.host}`;
    const ws = new WebSocket(`${wsBase}/ws/chat?token=${encodeURIComponent(a.access_token)}`);
    ws.onopen = () => ws.send(JSON.stringify({ message, conversation_id: conversationId }));
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "start") on.start(ev.conversation_id);
      else if (ev.type === "token") on.token(ev.text);
      else if (ev.type === "done") { on.done(ev.citations, ev.text); ws.close(); resolve(); }
      else if (ev.type === "error") { ws.close(); reject(new Error(ev.message)); }
    };
    ws.onerror = () => reject(new Error("Connection failed"));
    ws.onclose = (e) => { if (e.code === 4401) reject(new Error("Session expired")); };
  });
}