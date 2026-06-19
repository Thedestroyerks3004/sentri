"""Run the SENTRI API and Streamlit frontend together for local development.

Usage:
    python start_both.py
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _pick_api_port(default_port: int = 8000, attempts: int = 20) -> int:
    for port in range(default_port, default_port + attempts):
        if _is_port_available(port):
            return port
    return default_port


def _run(cmd: list[str], name: str, env: dict[str, str] | None = None) -> subprocess.Popen:
    print(f"Starting {name}: {' '.join(cmd)}")
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=None,
        stderr=None,
        env=env or os.environ.copy(),
    )


def _wait_for_api(url: str, timeout: int = 45, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(interval)
    return False


if __name__ == "__main__":
    api_port = _pick_api_port()
    api_url = f"http://127.0.0.1:{api_port}"
    env = os.environ.copy()
    env["SENTRI_API_PORT"] = str(api_port)
    env["SENTRI_API_URL"] = api_url

    api_proc = _run(
        [sys.executable, "-m", "backend.run_api"],
        "API",
        env=env,
    )
    if not _wait_for_api(f"{api_url}/health"):
        print(f"API did not become ready at {api_url} in time.")

    ui_proc = _run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "frontend/app.py",
            "--server.address",
            "0.0.0.0",
        ],
        "Streamlit UI",
        env=env,
    )

    print("\nBoth services are starting...")
    print(f"API: {api_url}")
    print(f"UI:  http://127.0.0.1:8501")

    def stop_all(signum, frame):
        for proc in (api_proc, ui_proc):
            if proc.poll() is None:
                proc.terminate()
        for proc in (api_proc, ui_proc):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    try:
        api_proc.wait()
        ui_proc.wait()
    except KeyboardInterrupt:
        stop_all(None, None)
