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
        _migrate(c)


# Colunas adicionadas depois do schema original (migração idempotente).
_EXTRA_COLUMNS = {
    "email":            "TEXT",     # e-mail do lead (quando capturado)
    "channel":          "TEXT",     # whatsapp | email | ig_dm — canal principal do lead
    "followup_stage":   "INTEGER",  # 0,1,2,3 — quantos follow-ups já foram enviados
    "next_followup_at": "INTEGER",  # epoch do próximo follow-up agendado (NULL = nenhum)
    "last_inbound_at":  "INTEGER",  # epoch da última mensagem recebida do lead
    "opted_out":        "INTEGER",  # 1 = pediu para parar (nunca mais follow-up)
}


def _migrate(c) -> None:
    cols = {r[1] for r in c.execute("PRAGMA table_info(leads)").fetchall()}
    for name, decl in _EXTRA_COLUMNS.items():
        if name not in cols:
            c.execute(f"ALTER TABLE leads ADD COLUMN {name} {decl}")


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


# ───────────────────────── Follow-up / e-mail ─────────────────────────

def _today_start() -> int:
    import datetime
    return int(
        datetime.datetime.now()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )


def set_email(jid: str, email: str) -> None:
    """Guarda/atualiza o e-mail capturado de um lead."""
    if not email:
        return
    with _conn() as c:
        c.execute(
            "UPDATE leads SET email=?, updated_at=? WHERE jid=?",
            (email.strip().lower(), int(time.time()), jid),
        )


def find_lead_by_email(email: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM leads WHERE email=? ORDER BY updated_at DESC LIMIT 1",
            (email.strip().lower(),),
        ).fetchone()
    return dict(row) if row else None


def opt_out(jid: str) -> None:
    """Lead pediu para parar: cancela qualquer follow-up futuro."""
    with _conn() as c:
        c.execute(
            "UPDATE leads SET opted_out=1, next_followup_at=NULL, updated_at=? WHERE jid=?",
            (int(time.time()), jid),
        )


def record_inbound(jid: str) -> None:
    """Chame quando o lead ENVIA algo: reinicia a régua de follow-up.

    Quem respondeu não deve receber a sequência de cobrança; a cadência só
    recomeça a partir do próximo contato que a Vanessa iniciar.
    """
    with _conn() as c:
        c.execute(
            "UPDATE leads SET last_inbound_at=?, followup_stage=0, next_followup_at=NULL, updated_at=? WHERE jid=?",
            (int(time.time()), int(time.time()), jid),
        )


def schedule_followup(jid: str, next_at: int, stage: int) -> None:
    """Agenda o próximo toque de follow-up (epoch) e grava o estágio atingido."""
    with _conn() as c:
        c.execute(
            "UPDATE leads SET next_followup_at=?, followup_stage=?, updated_at=? WHERE jid=?",
            (next_at, stage, int(time.time()), jid),
        )


def clear_followup(jid: str) -> None:
    """Remove o agendamento pendente sem mexer no estágio."""
    with _conn() as c:
        c.execute(
            "UPDATE leads SET next_followup_at=NULL, updated_at=? WHERE jid=?",
            (int(time.time()), jid),
        )


def due_followups(now: int | None = None) -> list[dict]:
    """Leads com follow-up vencido: next_followup_at <= agora, não opt-out."""
    now = now or int(time.time())
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM leads
                 WHERE next_followup_at IS NOT NULL
                   AND next_followup_at <= ?
                   AND COALESCE(opted_out,0)=0
                   AND status NOT IN ('ganho','perdido','handoff')
                 ORDER BY next_followup_at ASC""",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def emails_sent_today() -> int:
    """E-mails enviados hoje (role='assistant' em jids de e-mail)."""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM messages WHERE role='assistant' AND ts>=? AND jid LIKE 'email:%'",
            (_today_start(),),
        ).fetchone()
    return int(row[0]) if row else 0
