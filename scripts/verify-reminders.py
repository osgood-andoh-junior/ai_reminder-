"""Run HTTP proxy tests with an isolated SQLite database and Next.js directory."""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
runtime = root / ".runtime"
runtime.mkdir(exist_ok=True)
for port in (8001, 3100):
    with socket.socket() as connection:
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(
                f"Port {port} is occupied; stop the old test server first."
            )
env = {
    **os.environ,
    "DATABASE_URL": f"sqlite:///{(runtime / ('reminder-check-' + uuid4().hex + '.db')).as_posix()}",
    "FRONTEND_URL": "http://localhost:3100",
    "BACKEND_URL": "http://127.0.0.1:8001",
    "ENVIRONMENT": "test",
    "AI_ENABLED": "false",
    "OPENAI_API_KEY": "",
    "EMAIL_PROVIDER": "",
    "EMAIL_FROM": "",
    "RESEND_API_KEY": "",
    "VAPID_PUBLIC_KEY": "",
    "VAPID_PRIVATE_KEY": "",
    "VAPID_SUBJECT": "",
    "COOKIE_SECURE": "false",
    "REMINDER_POLL_INTERVAL_SECONDS": "1",
    "TEMPO_E2E": "1",
}
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=root / "backend",
    env=env,
    check=True,
)
node = shutil.which("node")
if not node:
    raise SystemExit("Node.js is required")
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
processes, logs = [], []
generated = {
    path: path.read_bytes()
    for path in [root / "frontend/next-env.d.ts", root / "frontend/tsconfig.json"]
}
try:
    for name, command, folder in [
        (
            "api",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ],
            "backend",
        ),
        ("worker", [sys.executable, "-m", "app.worker"], "backend"),
        (
            "frontend",
            [
                node,
                "node_modules/next/dist/bin/next",
                "dev",
                "--hostname",
                "127.0.0.1",
                "--port",
                "3100",
            ],
            "frontend",
        ),
    ]:
        log = (runtime / f"reminder-check-{name}.log").open("w", encoding="utf-8")
        logs.append(log)
        processes.append(
            subprocess.Popen(
                command,
                cwd=root / folder,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        )
    for url in ["http://127.0.0.1:8001/api/health", "http://127.0.0.1:3100/api/health"]:
        deadline = time.monotonic() + 90
        while True:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Test server did not start; inspect .runtime/reminder-check-*.log"
                    )
                time.sleep(1)
    result = subprocess.run(
        [node, "node_modules/@playwright/test/cli.js", "test"],
        cwd=root / "frontend",
        env=env,
        check=False,
    )
    raise SystemExit(result.returncode)
finally:
    cleanup_errors = []
    for process in reversed(processes):
        if process.poll() is None:
            try:
                if os.name == "nt":
                    result = subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                    if result.returncode and process.poll() is None:
                        raise RuntimeError("Process termination was denied")
                else:
                    process.terminate()
                process.wait(timeout=15)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                cleanup_errors.append(process.pid)
    for log in logs:
        log.close()
    for path, content in generated.items():
        path.write_bytes(content)
    if cleanup_errors:
        raise RuntimeError(
            f"Could not stop test process IDs {cleanup_errors}; run with process-management permissions"
        )
