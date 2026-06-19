"""Start the SENTRI API server.

Use from the project root:
    python -m backend.run_api

Windows notes:
- Do not use `uvicorn` directly (App Control may block uvicorn.exe).
- If port 8000 is busy, this script detects an already-running API or picks the next free port.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import requests
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
DEFAULT_PORT = int(os.getenv("SENTRI_API_PORT", "8000"))


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, port)) == 0


def _api_healthy(port: int) -> bool:
    health_url = f"http://{HOST}:{port}/health"
    try:
        return requests.get(health_url, timeout=3).status_code == 200
    except Exception:
        return False


def _find_free_port(start: int, attempts: int = 20) -> int | None:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
                return port
            except OSError:
                continue
    return None


def main() -> None:
    port = DEFAULT_PORT

    if _port_in_use(port):
        if _api_healthy(port):
            print(f"SENTRI API is already running at http://{HOST}:{port}")
            print("Refresh your Streamlit dashboard — no need to start again.")
            return
        print(f"Port {port} is in use by another program.")
        alt = _find_free_port(8001)
        if alt is None:
            print("No free port found. Close the process using port 8000 and retry.")
            sys.exit(1)
        print(f"Using alternate port {alt}.")
        print("Before starting Streamlit, run one of these:")
        print(f'  PowerShell: $env:SENTRI_API_URL="http://{HOST}:{alt}"')
        print(f'  CMD: set SENTRI_API_URL=http://{HOST}:{alt}')
        port = alt

    print(f"Starting SENTRI API at http://{HOST}:{port}")
    uvicorn.run("backend.api.main:app", host=HOST, port=port, reload=False)


if __name__ == "__main__":
    main()
