import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Citation, Msg, api, streamChat } from "./api";

interface Conv { id: number; title: string }

function Answer({ m }: { m: Msg }) {
  const [open, setOpen] = useState<number | null>(null);
  // turn [n] into a link we render as a badge
  const text = m.content.replace(/\[(\d+)\]/g, "[$1](#cite-$1)");
  return (
    <div>
      <div className="prose prose-sm max-w-none [&_p]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:bg-slate-100 [&_pre]:p-2 [&_pre]:rounded [&_code]:text-xs">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) =>
              href?.startsWith("#cite-") ? (
                <button
                  onClick={() => setOpen(open === Number(href.slice(6)) ? null : Number(href.slice(6)))}
                  className="align-super text-[10px] bg-indigo-100 text-indigo-700 rounded px-1 mx-0.5 hover:bg-indigo-200">
                  {String(children)}
                </button>
              ) : <a href={href} target="_blank" rel="noreferrer" className="text-indigo-600 underline">{children}</a>,
          }}>
          {text}
        </ReactMarkdown>
      </div>
      {m.citations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {m.citations.map((c) => (
            <button key={c.n} onClick={() => setOpen(open === c.n ? null : c.n)}
                    className="text-xs border rounded px-2 py-0.5 bg-white hover:bg-slate-50">
              [{c.n}] {c.doc_title}{c.page ? ` · p.${c.page}` : ""}
            </button>
          ))}
        </div>
      )}
      {open !== null && (() => {
        const c = m.citations.find((x: Citation) => x.n === open);
        return c ? (
          <div className="mt-2 text-xs bg-amber-50 border border-amber-200 rounded p-2">
            <div className="font-medium mb-1">
              {c.doc_title}{c.page ? ` · page ${c.page}` : ""}{c.heading ? ` · ${c.heading}` : ""}
            </div>
            <div className="text-slate-700 whitespace-pre-wrap">{c.snippet}…</div>
          </div>
        ) : null;
      })()}
    </div>
  );
}

export default function Chat() {
  const [convs, setConvs] = useState<Conv[]>([]);
  const [cid, setCid] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConvs = () => api<Conv[]>("/api/conversations").then(setConvs).catch(() => {});
  useEffect(() => { loadConvs(); }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const open = async (id: number | null) => {
    setCid(id); setErr(""); setSidebar(false);
    setMsgs(id ? await api<Msg[]>(`/api/conversations/${id}`) : []);
  };

  const del = async (id: number) => {
    await api(`/api/conversations/${id}`, { method: "DELETE" });
    if (cid === id) open(null);
    loadConvs();
  };

  const send = async () => {
    const q = input.trim();
    if (!q || busy) return;
    setInput(""); setErr(""); setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: q, citations: [] }, { role: "assistant", content: "", citations: [] }]);
    try {
      await streamChat(q, cid, {
        start: (id) => setCid(id),
        token: (t) => setMsgs((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, content: last.content + t };
          return copy;
        }),
        done: (citations, text) => setMsgs((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { role: "assistant", content: text, citations };
          return copy;
        }),
      });
      loadConvs();
    } catch (e: any) {
      setErr(e.message);
      setMsgs((m) => (m[m.length - 1]?.content === "" ? m.slice(0, -1) : m));
    } finally { setBusy(false); }
  };

  return (
    <div className="h-full flex">
      <aside className={`${sidebar ? "block" : "hidden"} md:block w-64 bg-white border-r overflow-y-auto absolute md:static z-10 h-full`}>
        <button onClick={() => open(null)} className="m-3 w-[calc(100%-1.5rem)] bg-indigo-600 text-white rounded py-2 text-sm">+ New chat</button>
        {convs.map((c) => (
          <div key={c.id} className={`group flex items-center px-3 py-2 text-sm cursor-pointer hover:bg-slate-50 ${c.id === cid ? "bg-indigo-50" : ""}`}>
            <span className="flex-1 truncate" onClick={() => open(c.id)}>{c.title}</span>
            <button className="text-slate-400 hover:text-red-600 text-xs" onClick={() => del(c.id)}>✕</button>
          </div>
        ))}
      </aside>

      <section className="flex-1 flex flex-col min-w-0">
        <button className="md:hidden text-left px-4 py-1 text-sm text-indigo-600" onClick={() => setSidebar(!sidebar)}>☰ History</button>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {msgs.length === 0 && (
            <div className="text-center text-slate-400 mt-20">Ask a question about your documents.</div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] md:max-w-2xl rounded-xl px-4 py-2 ${m.role === "user" ? "bg-indigo-600 text-white" : "bg-white border"}`}>
                {m.role === "user" ? m.content : m.content ? <Answer m={m} /> : <span className="animate-pulse text-slate-400">Thinking…</span>}
              </div>
            </div>
          ))}
          <div ref={bottom} />
        </div>
        {err && <div className="px-4 text-sm text-red-600">{err}</div>}
        <form className="p-3 border-t bg-white flex gap-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input className="flex-1 border rounded px-3 py-2" placeholder="Ask something…" value={input}
                 onChange={(e) => setInput(e.target.value)} />
          <button disabled={busy || !input.trim()} className="bg-indigo-600 text-white rounded px-4 disabled:opacity-50">Send</button>
        </form>
      </section>
    </div>
  );
}
