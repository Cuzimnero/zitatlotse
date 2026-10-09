"""Build an XPI and source ZIP without local indexes, keys or model weights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


ROOT = Path(__file__).resolve().parent
TOP_LEVEL = (
    "README.md", "LICENSE", "THIRD_PARTY.md", "CONTRIBUTING.md",
    "SECURITY.md", ".gitignore", ".gitattributes", "package.py",
    "requirements-dev.txt", "Install-Zitatlotse.ps1", "Start-Zitatlotse.ps1",
    "test_plugin.js", "test_search_session.js", "smoke_service_start.js",
    "smoke_autostart.ps1", "build_runtime.py", "test_runtime.js", "test_runtime_setup.ps1",
)
PLUGIN = (
    "manifest.json", "bootstrap.js", "search.svg",
    "locale/de-DE/zitatfinder.ftl", "locale/en-US/zitatfinder.ftl",
)


def source_files():
    """Only public source locations; never descend into backend/data or venvs."""
    files = [ROOT / name for name in TOP_LEVEL]
    files += [ROOT / "plugin" / name for name in PLUGIN]
    files += list((ROOT / "backend").glob("*.py"))
    files += [ROOT / "backend" / "requirements.txt"]
    files += [file for file in (ROOT / "docs").rglob("*")
              if file.is_file() and file.suffix.lower() in {".md", ".png", ".svg"}]
    files += [file for file in (ROOT / ".github").rglob("*")
              if file.is_file() and file.suffix.lower() in {".md", ".yml", ".yaml"}]
    files += [ROOT / "runtime" / "setup.ps1", ROOT / "runtime" / "requirements-lock.txt"]
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--runtime", type=Path, default=ROOT / "dist" / "windows-x64-runtime.zip")
    parser.add_argument("--source-only", action="store_true", help="Build source without an installable XPI")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))["version"]
    # Stable file ordering makes it easy to inspect what is distributed.
    artifacts = []
    if not args.source_only:
        if not args.runtime.is_file():
            raise SystemExit("Runtime bundle missing. Run build_runtime.py first, or use --source-only.")
        corresponding_source = args.runtime.parent / "third-party-sources.zip"
        if not corresponding_source.is_file():
            raise SystemExit("Corresponding third-party source missing. Run build_runtime.py first.")
        runtime_meta = json.loads(args.runtime.with_suffix(".json").read_text(encoding="utf-8"))
        runtime_hash = hashlib.sha256(args.runtime.read_bytes()).hexdigest()
        if runtime_hash != runtime_meta["sha256"] or runtime_meta["platform"] != "win-x64":
            raise SystemExit("Runtime bundle checksum/platform mismatch")
        backend_zip = args.output / "backend-payload.zip"
        with ZipFile(backend_zip, "w", ZIP_DEFLATED) as archive:
            for file in sorted((ROOT / "backend").glob("*.py")):
                # Diagnostics and model/provider smoke tests belong in the source archive.
                if not file.name.startswith(("test_", "smoke_", "diagnose_")):
                    archive.write(file, file.name)
            archive.write(ROOT / "backend" / "requirements.txt", "requirements.txt")
            archive.write(ROOT / "LICENSE", "LICENSE")
        metadata = {"version": version, "platform":"win-x64", "runtime_sha256":runtime_hash,
                    "backend_sha256":hashlib.sha256(backend_zip.read_bytes()).hexdigest(),
                    "python_version":runtime_meta["python_version"]}
        xpi = args.output / f"Zitatlotse-{version}.xpi"
        with ZipFile(xpi, "w", ZIP_DEFLATED) as archive:
            for name in PLUGIN:
                archive.write(ROOT / "plugin" / name, name)
            archive.write(ROOT / "runtime" / "setup.ps1", "runtime/setup.ps1")
            archive.write(args.runtime, "runtime/python.zip", compress_type=ZIP_STORED)
            archive.write(backend_zip, "runtime/backend.zip", compress_type=ZIP_STORED)
            archive.writestr("runtime/manifest.json", json.dumps(metadata, indent=2))
            archive.write(ROOT / "THIRD_PARTY.md", "THIRD_PARTY.md")
        artifacts.append(xpi)
        if corresponding_source.resolve().parent != args.output.resolve():
            import shutil
            shutil.copyfile(corresponding_source, args.output / corresponding_source.name)
        artifacts.append(args.output / corresponding_source.name)
    source = args.output / f"Zitatlotse-{version}-source.zip"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        for file in source_files():
            archive.write(file, file.relative_to(ROOT).as_posix())
    artifacts.append(source)
    checksums = args.output / "SHA256SUMS.txt"
    checksums.write_text("".join(
        f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
        for file in artifacts), encoding="utf-8")
    for file in [*artifacts, checksums]:
        print(file)


if __name__ == "__main__":
    main()
