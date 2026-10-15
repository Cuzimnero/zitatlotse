"""Run isolated regressions and produce a per-test JSON/Markdown report.

Use a Python with requirements-dev.txt installed and Node.js on PATH.
Optional --startup exercises the supplied XPI in a fresh disposable directory.
No add-on installation, existing service shutdown or cloud API calls are needed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent


class RecordingResult(unittest.TextTestResult):
    """One result per method, including setup/cleanup failures and subtest failures."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        super().startTest(test)
        self.started = time.perf_counter()
        self.current = {"id":test.id(), "status":"passed", "details":[]}

    def addError(self, test, err):
        super().addError(test, err)
        self.current["status"] = "error"
        self.current["details"].append(self._exc_info_to_string(err, test))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.current["status"] = "failed"
        self.current["details"].append(self._exc_info_to_string(err, test))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.current["status"] = "failed"
            self.current["details"].append(str(subtest) + "\n" + self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.current.update(status="skipped", details=[reason])

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.current.update(status="expected_failure", details=[self._exc_info_to_string(err, test)])

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.current.update(status="unexpected_success")

    def stopTest(self, test):
        self.current["seconds"] = round(time.perf_counter() - self.started, 4)
        self.records.append(self.current)
        super().stopTest(test)


class MemoryKeyring:
    def __init__(self): self.keys = {}
    def get_password(self, service, account): return self.keys.get((service, account))
    def set_password(self, service, account, value): self.keys[(service, account)] = value
    def delete_password(self, service, account): self.keys.pop((service, account), None)


def loopback_only(original):
    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            try:
                allowed = ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                allowed = address[0] == "localhost"
            if not allowed:
                raise RuntimeError("Tests may connect only to loopback: " + str(address[0]))
        return original(sock, address)
    return connect


def command_stage(name, command, output, timeout=120, environment=None):
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout, env=environment)
        log = result.stdout + result.stderr
        status = "passed" if result.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired) as error:
        log, status = str(error), "error"
    (output / (name + ".log")).write_text(log, encoding="utf-8")
    return {"id":name,"status":status,"seconds":round(time.perf_counter()-started, 4),
            "log":name + ".log"}


def verify_xpi(path, version):
    with ZipFile(path) as archive:
        if archive.testzip() is not None: raise ValueError("XPI CRC failure")
        manifest = json.loads(archive.read("manifest.json"))
        meta = json.loads(archive.read("runtime/manifest.json"))
        if manifest["version"] != version or meta["version"] != version:
            raise ValueError("XPI and working tree version mismatch")
        # Git normalizes text line endings; the already-tested release archive
        # may contain CRLF. Accept that difference, but still compare all code.
        normalize = lambda content: content.replace(b"\r\n", b"\n")
        if normalize(archive.read("bootstrap.js")) != normalize((ROOT/"plugin/bootstrap.js").read_bytes()):
            raise ValueError("XPI UI differs from tested working tree")
        for entry, key in (("runtime/backend.zip","backend_sha256"),("runtime/python.zip","runtime_sha256")):
            if hashlib.sha256(archive.read(entry)).hexdigest() != meta[key]:
                raise ValueError("Payload checksum mismatch: " + entry)
        with ZipFile(io.BytesIO(archive.read("runtime/backend.zip"))) as backend:
            for source in (ROOT / "backend").glob("*.py"):
                if not source.name.startswith(("test_", "smoke_", "diagnose_")):
                    if normalize(backend.read(source.name)) != normalize(source.read_bytes()):
                        raise ValueError("XPI backend differs from source: " + source.name)
    return {"id":"xpi_integrity","status":"passed","sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--xpi", type=Path, help="Also verify this exact candidate against tested sources")
    parser.add_argument("--startup", action="store_true", help="Exercise XPI setup and process-loss restart")
    parser.add_argument("--port", type=int, default=19765, help="Separate test service port")
    args = parser.parse_args()
    if args.startup and (not args.xpi or os.name != "nt"):
        parser.error("--startup requires Windows and --xpi")
    output = (args.output or ROOT / "outputs/test-runs" / datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    output.mkdir(parents=True, exist_ok=False)
    version = json.loads((ROOT / "plugin/manifest.json").read_text(encoding="utf-8"))["version"]
    env_before = {key:os.environ.get(key) for key in ("ZQS_DB","HF_HUB_OFFLINE","TRANSFORMERS_OFFLINE","ZQS_LLM_PROVIDER","ZQS_LLM_MODEL")}
    report = {"version":version,"started_utc":datetime.now(timezone.utc).isoformat(),
        "model_mode":"deterministic doubles; real PDFs, SQLite and loopback HTTP",
        "cloud_calls":0,"model_downloads":False,"native_zotero_visual_test":"not performed",
        "real_windows_reboot":"not performed", "python":sys.version.split()[0],"tests":[],"stages":[]}
    try:
        with tempfile.TemporaryDirectory(prefix="zitatlotse-regressions-") as temporary:
            folder = Path(temporary)
            os.environ.update(ZQS_DB=str(folder/"import.sqlite"),HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",
                              ZQS_LLM_PROVIDER="none", ZQS_LLM_MODEL="")
            # Embedded Windows Python does not always include the script folder.
            sys.path.insert(0, str(ROOT))
            sys.path.insert(0, str(ROOT / "backend"))
            import settings
            with patch.object(settings,"DATA_DIR",folder), patch.object(settings,"SETTINGS_PATH",folder/"settings.json"), \
                    patch.object(settings,"_keyring",return_value=MemoryKeyring()), \
                    patch.object(socket.socket,"connect",loopback_only(socket.socket.connect)):
                suite = unittest.TestSuite([
                    unittest.defaultTestLoader.discover(str(ROOT/"backend"), pattern="test_*.py"),
                    unittest.defaultTestLoader.loadTestsFromName("test_package")])
                with (output/"python.log").open("w",encoding="utf-8") as log:
                    result = unittest.TextTestRunner(stream=log,verbosity=2,resultclass=RecordingResult).run(suite)
                report["tests"] = result.records
                report["python_success"] = result.wasSuccessful()
        for script in ("test_plugin.js", "test_search_session.js", "test_runtime.js"):
            report["stages"].append(command_stage(script.removesuffix(".js"), ["node",script], output))
        if args.xpi:
            try: report["stages"].append(verify_xpi(args.xpi.resolve(), version))
            except Exception as error:
                report["stages"].append({"id":"xpi_integrity","status":"failed","details":str(error)})
        if args.startup:
            # No existing directory is accepted: the setup belongs only to this test run.
            startup_env = dict(os.environ, ZQS_DB=str(output/"startup/backend/data/quotes.sqlite"),
                               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ZQS_LLM_PROVIDER="none")
            report["stages"].append(command_stage("startup_process_loss", ["powershell.exe","-NoProfile",
                "-NonInteractive","-ExecutionPolicy","Bypass","-File",str(ROOT/"test_runtime_setup.ps1"),
                "-Xpi",str(args.xpi.resolve()),"-TestRoot",str(output/"startup"),"-Port",str(args.port)],output,timeout=300,environment=startup_env))
    except Exception as error:
        report["stages"].append({"id":"test_setup","status":"error","details":repr(error)})
    finally:
        for key,value in env_before.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key] = value
    catalogue = (ROOT/"docs/TESTPLAN.de.md").read_text(encoding="utf-8")
    descriptions = dict(re.findall(r"^\| `(test_[\w]+)` \| (.+?) \|$", catalogue, re.M))
    for test in report["tests"]:
        test["explanation"] = descriptions.get(test["id"].rsplit(".",1)[-1], "Explanation missing from test catalogue")
    missing = [t["id"] for t in report["tests"] if t["id"].rsplit(".",1)[-1] not in descriptions]
    report["stages"].append({"id":"catalogue_completeness", "status":"failed" if missing else "passed", "missing":missing})
    report["passed"] = report.get("python_success",False) and all(s["status"] == "passed" for s in report["stages"])
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (output/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    counts = {status:sum(t["status"] == status for t in report["tests"]) for status in {"passed","failed","error","skipped"}}
    lines = [f"# Zitatlotse {version}: Testergebnis", "",f"Gesamtergebnis: **{'BESTANDEN' if report['passed'] else 'FEHLGESCHLAGEN'}**", "",
        f"Python-Testmethoden: {len(report['tests'])}; bestanden: {counts['passed']}; fehlgeschlagen: {counts['failed']}; Fehler: {counts['error']}; übersprungen: {counts['skipped']}.", "",
        "Echte PDFs, SQLite und lokales HTTP; kontrollierte Embeddings und KI-Antworten. Keine Cloud-Abfragen oder Modelldownloads. Kein echter Windows-Neustart und keine visuelle Zotero-Prüfung.", "",
        "## Zusätzliche Prüfblöcke", "", "| Block | Ergebnis |", "|---|---|"]
    lines += [f"| {s['id']} | {s['status']} |" for s in report["stages"]]
    lines += ["", "## Jede einzelne Testmethode", "", "Untertests zählen nicht als zusätzliche Methoden. Die JavaScript-Dateien sind jeweils ein Prüfblock, nicht eine gezählte Einzelmethode.", "",
              "| Test | Ergebnis | Dauer | Was wird geprüft? |", "|---|---|---:|---|"]
    lines += [f"| `{t['id']}` | {t['status']} | {t['seconds']:.3f} s | {t['explanation']} |" for t in report["tests"]]
    lines += ["", "## Testplan und noch offene Prüfungen", "", catalogue]
    (output/"Testbericht.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"python_methods":len(report["tests"]),"counts":counts,
                      "stages":report["stages"],"report":str(output/"Testbericht.md")},ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
