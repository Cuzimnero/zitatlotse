"""One background supervisor per installation; restart failed local workers."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
# Embeddable Python ignores the script directory unless we include it explicitly.
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
HEALTH = "http://127.0.0.1:" + os.environ.get("ZQS_PORT", "8765") + "/health"


def service_healthy():
    try:
        with urlopen(HEALTH, timeout=2) as response:
            data = json.load(response)
        return isinstance(data, dict) and data.get("ok") is True and (data.get("service") == "zitatlotse" or
            isinstance(data.get("version"), str) and "models_cached" in data)
    except (OSError, ValueError, TypeError):
        return False


def instance_lock(path):
    """An OS lock releases on crashes/reboots; a stale file never blocks startup."""
    file = path.open("a+b")
    if file.tell() == 0:
        file.write(b"\0")
        file.flush()
    file.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return file
    except OSError:
        file.close()
        return None


def write_state(**state):
    path = DATA / "supervisor.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "updated_at": datetime.now().isoformat(timespec="seconds"),
                                    **state}), encoding="utf-8")
    os.replace(temporary, path)


def supervise():
    lock = instance_lock(DATA / "service.lock")
    if lock is None:
        return 0
    try:
        if service_healthy():
            return 0
        delay = 2
        while True:
            started = time.monotonic()
            # Absolute paths and cwd work without PATH or an activated virtualenv.
            worker = subprocess.Popen([sys.executable, "-u", str(ROOT / "launcher.py"), "--worker"],
                cwd=ROOT, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                stdout=sys.stdout, stderr=sys.stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            write_state(state="running", worker_pid=worker.pid)
            code = worker.wait()
            print(f"[{datetime.now().isoformat(timespec='seconds')}] Worker exited ({code}); retry in {delay}s", flush=True)
            write_state(state="retrying", exit_code=code, retry_in=delay)
            if service_healthy():
                return 0
            time.sleep(delay)
            delay = 2 if time.monotonic() - started >= 60 else min(delay * 2, 30)
    finally:
        lock.close()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(DATA / "models")
    os.environ["MPLCONFIGDIR"] = str(DATA / "matplotlib")
    # A PowerShell transcript must never lock the worker's log. pythonw has no
    # standard streams, so redirect both before importing any backend modules.
    with (DATA / "service.log").open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            if "--worker" in sys.argv:
                import server
                server.run()
                return 0
            return supervise()
        except Exception:
            print(f"[{datetime.now().isoformat(timespec='seconds')}] Startup failed", flush=True)
            traceback.print_exc(file=log)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
