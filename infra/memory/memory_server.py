#!/usr/bin/env python3
import os
import sys
import json
import time
import sqlite3
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP
import chromadb
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

CHROMA_PATH = os.environ.get("MEMORY_PATH", os.path.expanduser("~/bot/memory"))
OPENCODE_DB = os.environ.get(
    "OPENCODE_DB",
    str(Path.home() / ".local/share/opencode/opencode.db"),
)
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-ai/nomic-embed-text-v1")
EMBED_DEVICE = os.environ.get("EMBED_DEVICE", "cuda")

os.makedirs(CHROMA_PATH, exist_ok=True)
_chroma = chromadb.PersistentClient(path=CHROMA_PATH)
_collection = _chroma.get_or_create_collection("sessions")

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL, trust_remote_code=True, device=EMBED_DEVICE)
    return _model


def embed(text: str) -> list[float]:
    return get_model().encode(text).tolist()


mcp_app = FastMCP("opencode-memory")


@mcp_app.tool()
def search_memory(query: str) -> str:
    """Search past OpenCode conversations and sessions by semantic similarity.
    Use this to recall previous work, find how something was done before,
    or retrieve context from earlier sessions. Returns the most relevant
    past conversation snippets."""
    if _collection.count() == 0:
        return "Memory is empty — no sessions indexed yet."
    q_vec = embed(query)
    k = min(5, _collection.count())
    results = _collection.query(query_embeddings=[q_vec], n_results=k)
    if not results["ids"][0]:
        return "No relevant memories found."
    parts = []
    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        title = meta.get("title", "Untitled")
        doc = results["documents"][0][i][:600]
        dist = results["distances"][0][i] if results.get("distances") else ""
        parts.append(f"### {title}\n{doc}")
    return "\n\n---\n\n".join(parts)


@mcp_app.tool()
def save_to_memory(title: str, text: str) -> str:
    """Save a piece of information or conversation summary to long-term memory.
    Use this to remember important decisions, solutions, or context for later."""
    session_id = f"manual_{int(time.time())}"
    _collection.upsert(
        ids=[session_id],
        embeddings=[embed(text[:8000])],
        documents=[text[:8000]],
        metadatas=[{"title": title, "stored_at": str(int(time.time())), "source": "manual"}],
    )
    return f"Saved to memory as '{title}'. Total memories: {_collection.count()}"


@mcp_app.tool()
def memory_stats() -> str:
    """Show how many sessions/memories are stored."""
    return f"Total memories indexed: {_collection.count()}"


@mcp_app.tool()
def ingest_sessions() -> str:
    """Ingest all OpenCode sessions from the local database into vector memory.
    Run this to update memory with recent sessions."""
    if not os.path.exists(OPENCODE_DB):
        return f"OpenCode DB not found at {OPENCODE_DB}"

    conn = sqlite3.connect(OPENCODE_DB)
    sessions = conn.execute(
        "SELECT id, title, time_created FROM session ORDER BY time_created DESC"
    ).fetchall()

    count = 0
    for session_id, title, ts in sessions:
        rows = conn.execute("""
            SELECT p.data FROM part p
            JOIN message m ON p.message_id = m.id
            WHERE m.session_id = ?
        """, (session_id,)).fetchall()

        chunks = []
        for (data_json,) in rows:
            try:
                data = json.loads(data_json)
                if data.get("type") == "text" and data.get("text", "").strip():
                    chunks.append(data["text"].strip())
            except (json.JSONDecodeError, TypeError):
                continue

        text = "\n\n".join(chunks)
        if len(text) < 50:
            continue

        _collection.upsert(
            ids=[session_id],
            embeddings=[embed(text[:8000])],
            documents=[text[:8000]],
            metadatas=[{"title": title or "Untitled", "time_created": str(ts), "source": "opencode"}],
        )
        count += 1

    conn.close()
    return f"Ingested {count} sessions. Total memories: {_collection.count()}"


@mcp_app.tool()
def ingest_chat_log() -> str:
    """Ingest new Telegram chat history lines from the JSONL log into vector memory."""
    chat_log = os.environ.get("CHAT_LOG", os.path.expanduser("~/bot/chat_history.jsonl"))
    offset_file = os.path.join(CHROMA_PATH, ".jsonl_offset")

    if not os.path.exists(chat_log):
        return f"Chat log not found at {chat_log}"

    last_offset = 0
    if os.path.exists(offset_file):
        with open(offset_file) as f:
            last_offset = int(f.read().strip() or "0")

    count = 0
    batch_text = []
    batch_meta = []
    current_offset = 0

    with open(chat_log) as f:
        for i, line in enumerate(f):
            current_offset = i + 1
            if i < last_offset:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = entry.get("text", "").strip()
            if len(text) < 20:
                continue

            role = entry.get("role", "unknown")
            name = entry.get("name", "unknown")
            ts = entry.get("ts", "")
            title = f"{name} ({role}): {text[:80]}"

            batch_text.append(text)
            batch_meta.append({
                "title": title,
                "role": role,
                "name": name,
                "ts": ts,
                "source": "chat_log",
            })
            count += 1

    for j, text in enumerate(batch_text):
        sid = f"chat_{hash(text) % 999999}_{j}"
        _collection.upsert(
            ids=[sid],
            embeddings=[embed(text[:8000])],
            documents=[text[:8000]],
            metadatas=[batch_meta[j]],
        )

    with open(offset_file, "w") as f:
        f.write(str(current_offset))

    return f"Ingested {count} new chat log entries. Total memories: {_collection.count()}"


import urllib.request
import urllib.parse

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_IDS = os.environ.get("ALLOWED_CHAT_IDS", "").split(",")
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"
TG_LOG = os.environ.get("CHAT_LOG", os.path.expanduser("~/bot/chat_history.jsonl"))


def _tg_log(text):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "role": "assistant", "name": "bot", "text": text}
    with open(TG_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@mcp_app.tool()
def send_telegram_message(text: str) -> str:
    """Send a text message to the user(s) on Telegram."""
    _tg_log(text)
    for cid in TG_CHAT_IDS:
        data = urllib.parse.urlencode({"chat_id": cid.strip(), "text": text}).encode()
        urllib.request.urlopen(f"{TG_API}/sendMessage", data, timeout=15)
    return "Message sent."


@mcp_app.tool()
def send_telegram_photo(file_path: str, caption: str = "") -> str:
    """Send a photo/image file to the user(s) on Telegram. file_path must be an absolute path to the image."""
    import mimetypes, random
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"
    _tg_log(f"[Photo: {file_path}] {caption}")
    boundary = f"----Boundary{random.randint(100000,999999)}"
    for cid in TG_CHAT_IDS:
        body = bytearray()
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{cid.strip()}\r\n".encode()
        if caption:
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode()
        mime = mimetypes.guess_type(file_path)[0] or "image/png"
        fname = os.path.basename(file_path)
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{fname}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        with open(file_path, "rb") as f:
            body += f.read()
        body += f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{TG_API}/sendPhoto", data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req, timeout=30)
    return "Photo sent."


@mcp_app.tool()
def send_telegram_file(file_path: str, caption: str = "") -> str:
    """Send any file (PDF, zip, etc.) to the user(s) on Telegram. file_path must be an absolute path."""
    import mimetypes, random
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"
    _tg_log(f"[File: {file_path}] {caption}")
    boundary = f"----Boundary{random.randint(100000,999999)}"
    for cid in TG_CHAT_IDS:
        body = bytearray()
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{cid.strip()}\r\n".encode()
        if caption:
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode()
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        fname = os.path.basename(file_path)
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{fname}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        with open(file_path, "rb") as f:
            body += f.read()
        body += f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{TG_API}/sendDocument", data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req, timeout=30)
    return "File sent."


if __name__ == "__main__":
    mcp_app.run()
