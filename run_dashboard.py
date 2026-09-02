"""Launcher do painel/CRM local da Vanessa.

Carrega o .env (mesmo DB_PATH do agente) e sobe o dashboard em
http://127.0.0.1:8777 — só acesso local.

    python run_dashboard.py
"""
import os
import pathlib

envp = pathlib.Path(__file__).parent / ".env"
if envp.exists():
    for line in envp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8777"))
    print(f"Painel da Vanessa em http://127.0.0.1:{port}")
    uvicorn.run("dashboard:app", host="127.0.0.1", port=port)
