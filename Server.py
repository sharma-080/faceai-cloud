"""
Lightweight cloud relay server.
NO AI, NO CV — just receives frames/events from Mac and serves dashboard.
Deploy on Railway / Render / Fly.io (free tier).
"""
import os
import time
import base64
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

DB = "events.db"
EDGE_TOKEN = os.environ.get("EDGE_TOKEN", "changeme")  # set in Railway env vars

# Latest frame stored in memory (bytes)
_latest_frame: bytes = b""
_frame_time:   float = 0


# ── DB init ──
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        time       TEXT,
        name       TEXT,
        event_type TEXT,
        confidence REAL,
        image_url  TEXT
    )""")
    conn.commit()
    conn.close()

init_db()


def auth(token: str):
    if token != EDGE_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─────────────────────────────
# PUSH endpoints (called by Mac)
# ─────────────────────────────

@app.post("/push/frame")
async def push_frame(request: Request,
                     x_token: str = Header(None)):
    """Mac pushes latest annotated JPEG frame here."""
    auth(x_token)
    global _latest_frame, _frame_time
    _latest_frame = await request.body()
    _frame_time   = time.time()
    return {"ok": True}


@app.post("/push/event")
async def push_event(request: Request,
                     x_token: str = Header(None)):
    """Mac pushes detection events here."""
    auth(x_token)
    data = await request.json()
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT INTO events(time,name,event_type,confidence,image_url) VALUES(?,?,?,?,?)",
        (data.get("time", datetime.now().isoformat()),
         data.get("name", "Unknown"),
         data.get("event", "UNKNOWN"),
         data.get("confidence", 0),
         data.get("image_url", ""))
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ─────────────────────────────
# PULL endpoints (browser dashboard)
# ─────────────────────────────

@app.get("/api/latest-frame")
def latest_frame():
    """Returns base64 JPEG of most recent frame."""
    if not _latest_frame:
        return {"frame": None, "age": None}
    age = round(time.time() - _frame_time, 1)
    return {
        "frame": base64.b64encode(_latest_frame).decode(),
        "age": age
    }


@app.get("/api/events")
def get_events(limit: int = 50):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT time,name,event_type,confidence,image_url FROM events "
        "ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [{"time": r[0], "name": r[1], "event": r[2],
             "confidence": r[3], "image_url": r[4]} for r in rows]


@app.get("/api/status")
def status():
    age = round(time.time() - _frame_time, 1) if _frame_time else None
    online = age is not None and age < 10
    return {"online": online, "last_frame_age_sec": age}


# ─────────────────────────────
# Dashboard HTML (served at /)
# ─────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    with open("dashboard.html") as f:
        return f.read()