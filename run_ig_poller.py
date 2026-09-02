"""Launcher do poller de comentários IG: carrega o .env e roda ig_poller."""
import os, pathlib
for line in (pathlib.Path(__file__).parent/".env").read_text(encoding="utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip())
import ig_poller
ig_poller.main()
