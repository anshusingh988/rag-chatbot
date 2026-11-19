import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .auth import (current_user, decode_access_token, hash_password, issue_refresh_token,
                   make_access_token, require_admin, rotate_refresh_token, verify_password)
from .chat import answer_question
from .db import get_db
from .embeddings import make_embedder
from .ingest import chunk_sections, parse_file
from .llm import get_llm
from .retrieval import HybridIndex

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    state["index"] = HybridIndex(db, make_embedder())
    print(f"[startup] LLM provider: {get_llm().name} | embedder: {state['index'].embedder.name}")
    yield


app = FastAPI(title="Full-Stack RAG Chatbot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ---------------- auth ----------------
class Creds(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str


def _token_response(user, refresh=None):
    return {
        "access_token": make_access_token(user),
        "refresh_token": refresh or issue_refresh_token(user["id"]),
        "user": {"id": user["id"], "email": user["email"], "role": user["role"]},
    }


@app.post("/api/auth/register")
def register(c: Creds):
    db = get_db()
    email = c.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "Invalid email")
    if db.one("SELECT 1 FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "Email already registered")
    first = db.one("SELECT COUNT(*) n FROM users")["n"] == 0
    uid = db.run("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)",
                 (email, hash_password(c.password), "admin" if first else "user"))
    return _token_response(db.one("SELECT * FROM users WHERE id=?", (uid,)))


@app.post("/api/auth/login")
def login(c: Creds):
    user = get_db().one("SELECT * FROM users WHERE email=?", (c.email.strip().lower(),))
    if not user or not verify_password(c.password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return _token_response(user)


@app.post("/api/auth/refresh")
def refresh(r: RefreshIn):
    user, new_refresh = rotate_refresh_token(r.refresh_token)
    return _token_response(user, new_refresh)


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/health")
def health():
    return {"ok": True, "llm": get_llm().name, "embedder": state["index"].embedder.name}


# ---------------- documents (admin) ----------------
def _ingest(doc_id: int, filename: str, data: bytes):
    db, index = get_db(), state["index"]
    try:
        chunks = chunk_sections(parse_file(filename, data))
        if not chunks:
            raise ValueError("Document produced no usable chunks")
        n = index.add_document_chunks(doc_id, chunks)  # chunks inserted while status != ready
        db.run("UPDATE documents SET status='ready', n_chunks=? WHERE id=?", (n, doc_id))
        index.rebuild()  # now that status=ready, include it
    except Exception as e:
        db.run("UPDATE documents SET status='failed', error=? WHERE id=?", (str(e)[:300], doc_id))
        db.run("DELETE FROM chunks WHERE doc_id=?", (doc_id,))


@app.post("/api/documents")
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...),
                          tag: str = Form(""), user=Depends(require_admin)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported type {ext}. Allowed: {sorted(config.ALLOWED_EXT)}")
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File larger than {config.MAX_UPLOAD_MB} MB")
    db = get_db()
    title = Path(file.filename).stem
    prev = db.one("SELECT MAX(version) v FROM documents WHERE filename=?", (file.filename,))["v"] or 0
    doc_id = db.run(
        "INSERT INTO documents(title,filename,tag,version,status,uploaded_by) VALUES(?,?,?,?,?,?)",
        (title, file.filename, tag.strip(), prev + 1, "processing", user["id"]))
    (config.DATA_DIR / "uploads" / f"{doc_id}{ext}").write_bytes(data)
    background.add_task(_ingest, doc_id, file.filename, data)
    return {"id": doc_id, "status": "processing", "version": prev + 1}


@app.get("/api/documents")
def list_documents(user=Depends(current_user)):
    rows = get_db().all(
        "SELECT id,title,filename,tag,version,status,error,n_chunks,created_at FROM documents ORDER BY id DESC")
    return [dict(r) for r in rows]


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, user=Depends(require_admin)):
    db = get_db()
    if not db.one("SELECT 1 FROM documents WHERE id=?", (doc_id,)):
        raise HTTPException(404, "Not found")
    db.run("DELETE FROM documents WHERE id=?", (doc_id,))  # chunks cascade
    for f in (config.DATA_DIR / "uploads").glob(f"{doc_id}.*"):
        f.unlink(missing_ok=True)
    state["index"].rebuild()
    return {"ok": True}


@app.get("/api/stats")
def stats(user=Depends(require_admin)):
    db = get_db()
    return {
        "documents": db.one("SELECT COUNT(*) n FROM documents WHERE status='ready'")["n"],
        "chunks": db.one("SELECT COUNT(*) n FROM chunks")["n"],
        "users": db.one("SELECT COUNT(*) n FROM users")["n"],
        "conversations": db.one("SELECT COUNT(*) n FROM conversations")["n"],
        "messages": db.one("SELECT COUNT(*) n FROM messages")["n"],
        "llm": get_llm().name,
        "embedder": state["index"].embedder.name,
    }


# ---------------- conversations ----------------
@app.get("/api/conversations")
def list_conversations(user=Depends(current_user)):
    rows = get_db().all("SELECT id,title,created_at FROM conversations WHERE user_id=? ORDER BY id DESC",
                        (user["id"],))
    return [dict(r) for r in rows]


@app.get("/api/conversations/{cid}")
def get_conversation(cid: int, user=Depends(current_user)):
    db = get_db()
    if not db.one("SELECT 1 FROM conversations WHERE id=? AND user_id=?", (cid, user["id"])):
        raise HTTPException(404, "Not found")
    msgs = db.all("SELECT role,content,citations FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    return [{"role": m["role"], "content": m["content"], "citations": json.loads(m["citations"])} for m in msgs]


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: int, user=Depends(current_user)):
    db = get_db()
    if not db.one("SELECT 1 FROM conversations WHERE id=? AND user_id=?", (cid, user["id"])):
        raise HTTPException(404, "Not found")
    db.run("DELETE FROM conversations WHERE id=?", (cid,))
    return {"ok": True}


# ---------------- streaming chat ----------------
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str = ""):
    try:
        claims = decode_access_token(token)
    except HTTPException:
        await ws.close(code=4401)
        return
    user = {"id": int(claims["sub"]), "email": claims["email"], "role": claims["role"]}
    await ws.accept()

    async def send(event: dict):
        await ws.send_json(event)

    try:
        while True:
            data = await ws.receive_json()
            await answer_question(user, data.get("conversation_id"), data.get("message", ""),
                                  state["index"], send)
    except WebSocketDisconnect:
        pass


# ---------------- serve built frontend (single-container deploy) ----------------
DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
