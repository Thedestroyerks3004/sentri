"""Run the SENTRI API and Streamlit frontend together for local development.

Usage:
    python start_both.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str], name: str) -> subprocess.Popen:
    print(f"Starting {name}: {' '.join(cmd)}")
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=None,
        stderr=None,
        env=os.environ.copy(),
    )


if __name__ == "__main__":
    api_proc = _run([sys.executable, "run_api.py"], "API")
    time.sleep(1.5)
    ui_proc = _run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.address",
            "0.0.0.0",
        ],
        "Streamlit UI",
    )

    print("\nBoth services are starting...")
    print("API: http://127.0.0.1:8000")
    print("UI:  http://127.0.0.1:8501")

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
