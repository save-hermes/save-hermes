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
CREATE TABLE IF NOT EXISTS email_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id    TEXT,                 -- id do e-mail no Resend
    type        TEXT,                 -- sent|delivered|opened|clicked|bounced|complained|delivery_delayed
    recipient   TEXT,                 -- destinatário (lower)
    jid         TEXT,                 -- lead vinculado (se encontrado por e-mail)
    subject     TEXT,
    ts          INTEGER,
    raw         TEXT                  -- payload bruto (json) para depuração
);
CREATE TABLE IF NOT EXISTS email_sends (
    email_id    TEXT PRIMARY KEY,     -- id do e-mail no Resend (1 por envio)
    recipient   TEXT,
    jid         TEXT,
    subject     TEXT,
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


# ───────────────────────── Consultas p/ o painel (CRM) ─────────────────────────

def _channel_of_jid(jid: str) -> str:
    if jid.startswith("email:"):
        return "email"
    if jid.startswith("ig_dm:") or jid.startswith("ig_comment:"):
        return "instagram"
    return "whatsapp"


def funnel_stats() -> dict:
    """Contagem de leads por status + totais úteis para os cards do painel."""
    with _conn() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM leads GROUP BY status").fetchall()
        total = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        due = c.execute(
            "SELECT COUNT(*) FROM leads WHERE next_followup_at IS NOT NULL AND COALESCE(opted_out,0)=0"
        ).fetchone()[0]
        msgs_today = c.execute(
            "SELECT COUNT(*) FROM messages WHERE role='assistant' AND ts>=?",
            (_today_start(),),
        ).fetchone()[0]
    by_status = {r["status"] or "—": r["n"] for r in rows}
    return {
        "total": total,
        "by_status": by_status,
        "followups_pending": due,
        "msgs_sent_today": msgs_today,
    }


def list_leads(status: str = "", channel: str = "", search: str = "", limit: int = 200) -> list[dict]:
    """Lista leads com filtros opcionais (status, canal, busca por nome/número/e-mail)."""
    q = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if status:
        q += " AND status=?"; params.append(status)
    if search:
        q += " AND (name LIKE ? OR number LIKE ? OR email LIKE ?)"
        like = f"%{search}%"; params += [like, like, like]
    q += " ORDER BY updated_at DESC LIMIT ?"; params.append(limit)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(q, params).fetchall()]
    out = []
    for r in rows:
        ch = r.get("channel") or _channel_of_jid(r["jid"])
        if channel and ch != channel:
            continue
        r["channel_derived"] = ch
        out.append(r)
    return out


def lead_detail(jid: str) -> dict | None:
    """Um lead + histórico completo da conversa (ordem cronológica)."""
    with _conn() as c:
        row = c.execute("SELECT * FROM leads WHERE jid=?", (jid,)).fetchone()
        if not row:
            return None
        msgs = c.execute(
            "SELECT role, content, ts FROM messages WHERE jid=? ORDER BY id ASC",
            (jid,),
        ).fetchall()
    d = dict(row)
    d["channel_derived"] = d.get("channel") or _channel_of_jid(jid)
    d["messages"] = [dict(m) for m in msgs]
    return d


def recent_activity(limit: int = 40) -> list[dict]:
    """Últimas mensagens (de todos os leads) para o feed 'o que a Vanessa fez'."""
    with _conn() as c:
        rows = c.execute(
            """SELECT m.jid, m.role, m.content, m.ts, l.name
                 FROM messages m LEFT JOIN leads l ON l.jid=m.jid
                 ORDER BY m.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["channel_derived"] = _channel_of_jid(d["jid"])
        out.append(d)
    return out


def pause_followup(jid: str) -> None:
    clear_followup(jid)


def set_lead_status(jid: str, status: str) -> None:
    set_status(jid, status)


# ───────────────────────── Métricas de e-mail (Resend webhook) ─────────────────────────

def record_email_send(email_id: str, recipient: str, jid: str = "", subject: str = "") -> None:
    """Registra um envio (chamado quando a Vanessa envia via Resend)."""
    if not email_id:
        return
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO email_sends (email_id, recipient, jid, subject, ts) VALUES (?,?,?,?,?)",
            (email_id, (recipient or "").lower(), jid, subject, int(time.time())),
        )


def record_email_event(email_id: str, etype: str, recipient: str = "", subject: str = "", raw: str = "") -> bool:
    """Registra um evento do webhook do Resend. Idempotente por (email_id,type).
    Vincula ao lead pelo e-mail do destinatário, se existir. Retorna False se dup.
    """
    recipient = (recipient or "").lower()
    with _conn() as c:
        # dedup: mesmo email_id+type só conta uma vez (opened pode repetir, mas
        # para métricas de "abriu?" basta a primeira).
        dup = c.execute(
            "SELECT 1 FROM email_events WHERE email_id=? AND type=? LIMIT 1",
            (email_id, etype),
        ).fetchone()
        if dup:
            return False
        # tenta vincular ao lead
        jid = ""
        if recipient:
            row = c.execute(
                "SELECT jid FROM leads WHERE email=? ORDER BY updated_at DESC LIMIT 1",
                (recipient,),
            ).fetchone()
            if row:
                jid = row["jid"]
        c.execute(
            "INSERT INTO email_events (email_id, type, recipient, jid, subject, ts, raw) VALUES (?,?,?,?,?,?,?)",
            (email_id, etype, recipient, jid, subject, int(time.time()), raw[:4000]),
        )
    return True


def email_metrics(since_ts: int | None = None) -> dict:
    """Agrega métricas de desempenho de e-mail para o painel.

    Taxa de abertura/clique é calculada sobre os ENVIOS (email_sends) que têm ao
    menos um evento 'delivered' (base de entregues), como manda a boa prática.
    """
    where = "WHERE ts>=?" if since_ts else ""
    args = (since_ts,) if since_ts else ()
    with _conn() as c:
        sends = c.execute(f"SELECT COUNT(*) FROM email_sends {where}", args).fetchone()[0]

        def cnt(t):
            w = "WHERE type=?" + (" AND ts>=?" if since_ts else "")
            a = (t, since_ts) if since_ts else (t,)
            return c.execute(f"SELECT COUNT(DISTINCT email_id) FROM email_events {w}", a).fetchone()[0]

        delivered = cnt("delivered")
        opened = cnt("opened")
        clicked = cnt("clicked")
        bounced = cnt("bounced")
        complained = cnt("complained")

    base = delivered or sends or 0
    pct = lambda n: round(100 * n / base, 1) if base else 0.0
    return {
        "sends": sends,
        "delivered": delivered,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "complained": complained,
        "open_rate": pct(opened),
        "click_rate": pct(clicked),
        "bounce_rate": round(100 * bounced / sends, 1) if sends else 0.0,
    }


def recent_email_events(limit: int = 30) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT e.type, e.recipient, e.subject, e.ts, l.name
                 FROM email_events e LEFT JOIN leads l ON l.jid=e.jid
                 ORDER BY e.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
