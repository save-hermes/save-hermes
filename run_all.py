"""Inicializador único da Vanessa — sobe TUDO num comando.

Sobe, em processos separados (mesmo .env, mesmo banco):
  1. Agente web (app:app)      — webhooks WhatsApp/Instagram/Resend + /reply + /email/*
  2. Worker de e-mail+follow-up — lê a caixa (IMAP) e dispara os follow-ups
  3. Painel/CRM local          — dashboard em http://127.0.0.1:8777

Uso:
    python run_all.py

Ctrl+C encerra todos. Cada serviço também pode ser rodado sozinho:
    python run_local.py          (só o agente)
    python email_worker.py       (só o worker)
    python run_dashboard.py      (só o painel)
"""
import os
import pathlib
import signal
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).parent
PY = sys.executable

# Carrega o .env para o ambiente dos filhos.
envp = ROOT / ".env"
env = os.environ.copy()
if envp.exists():
    for line in envp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())

AGENT_PORT = env.get("PORT", "8000")
DASH_PORT = env.get("DASHBOARD_PORT", "8777")

SERVICES = [
    ("agente",  [PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", AGENT_PORT]),
    ("worker",  [PY, "email_worker.py"]),
    ("painel",  [PY, "-m", "uvicorn", "dashboard:app", "--host", "127.0.0.1", "--port", DASH_PORT]),
]

procs = []


def _shutdown(*_):
    print("\nEncerrando serviços…")
    for name, p in procs:
        if p.poll() is None:
            p.terminate()
    time.sleep(1.5)
    for name, p in procs:
        if p.poll() is None:
            p.kill()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    print("Iniciando a Vanessa (agente + worker + painel)…")
    for name, cmd in SERVICES:
        p = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
        procs.append((name, p))
        print(f"  ✓ {name} (pid {p.pid})")
    print(f"\nAgente:  http://127.0.0.1:{AGENT_PORT}/")
    print(f"Painel:  http://127.0.0.1:{DASH_PORT}/")
    print("Ctrl+C para encerrar todos.\n")
    # Se algum morrer, derruba todos (fail-fast).
    try:
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    print(f"[{name}] saiu com código {p.returncode} — encerrando os demais.")
                    _shutdown()
            time.sleep(2)
    except KeyboardInterrupt:
        _shutdown()
