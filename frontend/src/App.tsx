import { useState } from "react";
import { Auth, getAuth, login, setAuth } from "./api";
import Chat from "./Chat";
import Admin from "./Admin";

function Login({ onAuth }: { onAuth: (a: Auth) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [register, setRegister] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const a = await login(email, password, register);
      setAuth(a); onAuth(a);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={submit} className="bg-white w-full max-w-sm p-6 rounded-xl shadow space-y-4">
        <h1 className="text-2xl font-bold">RAG Chatbot</h1>
        <p className="text-sm text-slate-500">
          {register ? "Create an account (the very first account becomes admin)." : "Sign in to continue."}
        </p>
        <input className="w-full border rounded px-3 py-2" type="email" placeholder="Email" required
               value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="w-full border rounded px-3 py-2" type="password" placeholder="Password (min 8 chars)"
               required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
        {err && <div className="text-sm text-red-600">{err}</div>}
        <button disabled={busy} className="w-full bg-indigo-600 text-white rounded py-2 font-medium disabled:opacity-50">
          {register ? "Register" : "Sign in"}
        </button>
        <button type="button" className="text-sm text-indigo-600 w-full" onClick={() => setRegister(!register)}>
          {register ? "Have an account? Sign in" : "New here? Register"}
        </button>
      </form>
    </div>
  );
}

export default function App() {
  const [auth, setA] = useState<Auth | null>(getAuth());
  const [view, setView] = useState<"chat" | "admin">("chat");
  if (!auth) return <Login onAuth={setA} />;

  const logout = () => { setAuth(null); setA(null); };
  return (
    <div className="h-screen flex flex-col">
      <header className="bg-white border-b px-4 py-2 flex items-center gap-4">
        <span className="font-bold">RAG Chatbot</span>
        <button className={`text-sm ${view === "chat" ? "font-semibold text-indigo-600" : ""}`}
                onClick={() => setView("chat")}>Chat</button>
        {auth.user.role === "admin" && (
          <button className={`text-sm ${view === "admin" ? "font-semibold text-indigo-600" : ""}`}
                  onClick={() => setView("admin")}>Knowledge base</button>
        )}
        <span className="ml-auto text-xs text-slate-500">{auth.user.email} ({auth.user.role})</span>
        <button className="text-sm text-red-600" onClick={logout}>Logout</button>
      </header>
      <main className="flex-1 min-h-0">{view === "chat" ? <Chat /> : <Admin />}</main>
    </div>
  );
}
