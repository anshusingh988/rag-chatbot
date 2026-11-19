import { useEffect, useRef, useState } from "react";
import { Doc, api } from "./api";

export default function Admin() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [stats, setStats] = useState<Record<string, any>>({});
  const [tag, setTag] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const load = async () => {
    setDocs(await api<Doc[]>("/api/documents"));
    setStats(await api("/api/stats"));
  };
  useEffect(() => { load().catch((e) => setErr(e.message)); }, []);
  // poll while anything is still processing
  useEffect(() => {
    if (!docs.some((d) => d.status === "processing")) return;
    const t = setInterval(() => load().catch(() => {}), 1500);
    return () => clearInterval(t);
  }, [docs]);

  const upload = async (e: React.FormEvent) => {
    e.preventDefault();
    const files = file.current?.files;
    if (!files?.length) return;
    setErr(""); setBusy(true);
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", f); fd.append("tag", tag);
        await api("/api/documents", { method: "POST", body: fd });
      }
      if (file.current) file.current.value = "";
      await load();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this document and its indexed chunks?")) return;
    await api(`/api/documents/${id}`, { method: "DELETE" });
    load();
  };

  const badge = (s: Doc["status"]) =>
    ({ ready: "bg-green-100 text-green-700", processing: "bg-yellow-100 text-yellow-700", failed: "bg-red-100 text-red-700" }[s]);

  return (
    <div className="h-full overflow-y-auto p-4 max-w-4xl mx-auto space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {["documents", "chunks", "users", "conversations", "messages"].map((k) => (
          <div key={k} className="bg-white rounded-lg border p-3">
            <div className="text-2xl font-bold">{stats[k] ?? "–"}</div>
            <div className="text-xs text-slate-500 capitalize">{k}</div>
          </div>
        ))}
      </div>
      <div className="text-xs text-slate-500">LLM: {stats.llm} · Embedder: {stats.embedder}</div>

      <form onSubmit={upload} className="bg-white border rounded-lg p-4 flex flex-wrap gap-3 items-end">
        <div>
          <label className="block text-xs text-slate-500 mb-1">Files (PDF, DOCX, HTML, MD, TXT)</label>
          <input ref={file} type="file" multiple accept=".pdf,.docx,.html,.htm,.md,.markdown,.txt" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Tag (optional)</label>
          <input className="border rounded px-2 py-1" value={tag} onChange={(e) => setTag(e.target.value)} />
        </div>
        <button disabled={busy} className="bg-indigo-600 text-white rounded px-4 py-1.5 disabled:opacity-50">
          {busy ? "Uploading…" : "Upload & index"}
        </button>
      </form>
      {err && <div className="text-sm text-red-600">{err}</div>}

      <table className="w-full bg-white border rounded-lg text-sm">
        <thead className="text-left text-xs text-slate-500 border-b">
          <tr><th className="p-2">Title</th><th>Tag</th><th>Ver</th><th>Chunks</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.id} className="border-b last:border-0">
              <td className="p-2">{d.title}<div className="text-xs text-slate-400">{d.filename}</div></td>
              <td>{d.tag}</td><td>v{d.version}</td><td>{d.n_chunks}</td>
              <td><span className={`text-xs px-2 py-0.5 rounded ${badge(d.status)}`}>{d.status}</span>
                {d.error && <div className="text-xs text-red-500">{d.error}</div>}</td>
              <td><button className="text-red-600 text-xs" onClick={() => remove(d.id)}>Delete</button></td>
            </tr>
          ))}
          {docs.length === 0 && <tr><td className="p-4 text-slate-400" colSpan={6}>No documents yet. Upload some to build the knowledge base.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
