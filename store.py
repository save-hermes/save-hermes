"""Persistência leve em SQLite: leads, histórico de mensagens e dedup."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    jid         TEXT PRIMARY KEY,     -- remoteJid do WhatsApp
    number      TEXT,                 -- só os dígitos
    name        TEXT,
    status      TEXT DEFAULT 'novo',  -- novo|abordado|respondeu|qualificado|quente|handoff|ganho|perdido
    created_at  INTEGER,
    updated_at  INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    jid         TEXT,
    role        TEXT,                 -- 'user' | 'assistant'
    content     TEXT,
    ts          INTEGER
);
CREATE TABLE IF NOT EXISTS processed (
    msg_id      TEXT PRIMARY KEY,     -- id da mensagem da Evolution (idempotência)
    ts          INTEGER
);
"""


def init() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def already_processed(msg_id: str) -> bool:
    if not msg_id:
        return False
    with _conn() as c:
        row = c.execute("SELECT 1 FROM processed WHERE msg_id=?", (msg_id,)).fetchone()
        if row:
            return True
        c.execute("INSERT INTO processed (msg_id, ts) VALUES (?,?)", (msg_id, int(time.time())))
        return False


def get_or_create_lead(jid: str, number: str, name: str) -> dict:
    now = int(time.time())
    with _conn() as c:
        row = c.execute("SELECT * FROM leads WHERE jid=?", (jid,)).fetchone()
        if row:
            # atualiza nome se veio um melhor
            if name and not row["name"]:
                c.execute("UPDATE leads SET name=?, updated_at=? WHERE jid=?", (name, now, jid))
            return dict(row)
        c.execute(
            "INSERT INTO leads (jid, number, name, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (jid, number, name, "respondeu", now, now),
        )
        return {"jid": jid, "number": number, "name": name, "status": "respondeu"}


def set_status(jid: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE leads SET status=?, updated_at=? WHERE jid=?", (status, int(time.time()), jid))


def add_message(jid: str, role: str, content: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (jid, role, content, ts) VALUES (?,?,?,?)",
            (jid, role, content, int(time.time())),
        )


def get_history(jid: str, limit: int = 20) -> list[dict]:
    """Últimas N mensagens, em ordem cronológica, no formato do Anthropic."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE jid=? ORDER BY id DESC LIMIT ?",
            (jid, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def assistant_msgs_today() -> int:
    """Quantas mensagens a Vanessa (assistant) já enviou hoje.

    Usado para respeitar o limite diário de aquecimento (warming) do número.
    """
    import datetime

    start = int(
        datetime.datetime.now()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM messages WHERE role='assistant' AND ts>=?",
            (start,),
        ).fetchone()
    return int(row[0]) if row else 0
