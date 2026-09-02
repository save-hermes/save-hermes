"""Painel/CRM local da Vanessa — dashboard web em cima do mesmo banco (store.py).

Roda LOCAL (só você acessa). Mostra o funil, os leads, o histórico de cada
conversa, os follow-ups agendados e o que a Vanessa fez. Permite ações simples:
mudar status, pausar follow-up.

Rodar:
    python dashboard.py                 # http://127.0.0.1:8777
    DASHBOARD_PORT=9000 python dashboard.py
"""
import os
import pathlib

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import store

app = FastAPI(title="Vanessa CRM")

_HTML = pathlib.Path(__file__).parent / "dashboard.html"


@app.on_event("startup")
def _startup():
    store.init()


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML.read_text(encoding="utf-8")


@app.get("/api/stats")
def api_stats():
    return store.funnel_stats()


@app.get("/api/leads")
def api_leads(status: str = "", channel: str = "", search: str = ""):
    return {"leads": store.list_leads(status=status, channel=channel, search=search)}


@app.get("/api/lead")
def api_lead(jid: str):
    d = store.lead_detail(jid)
    if not d:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return d


@app.get("/api/activity")
def api_activity(limit: int = 40):
    return {"activity": store.recent_activity(limit=limit)}


@app.get("/api/email_metrics")
def api_email_metrics():
    return {"metrics": store.email_metrics(), "events": store.recent_email_events(limit=20)}


@app.get("/api/flows")
def api_flows():
    return {"flows": store.list_flows(), "enrollments": store.flow_stats()}


@app.post("/api/lead/status")
async def api_set_status(request: Request):
    body = await request.json()
    jid = body.get("jid"); status = body.get("status")
    if not jid or not status:
        return JSONResponse({"error": "missing"}, status_code=400)
    store.set_lead_status(jid, status)
    return {"ok": True}


@app.post("/api/lead/pause_followup")
async def api_pause(request: Request):
    body = await request.json()
    jid = body.get("jid")
    if not jid:
        return JSONResponse({"error": "missing"}, status_code=400)
    store.pause_followup(jid)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    # Carrega o .env (mesmo DB_PATH do agente) se existir.
    envp = pathlib.Path(__file__).parent / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    port = int(os.getenv("DASHBOARD_PORT", "8777"))
    uvicorn.run(app, host="127.0.0.1", port=port)
