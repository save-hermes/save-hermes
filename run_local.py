"""Launcher local: carrega o .env no ambiente e sobe o uvicorn."""
import os
import pathlib

# Carrega .env -> os.environ (antes de importar config/app)
envfile = pathlib.Path(__file__).parent / ".env"
for line in envfile.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, log_level="info")
