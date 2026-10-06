"""Build an XPI and source ZIP without local indexes, keys or model weights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
TOP_LEVEL = (
    "README.md", "README.en.md", "LICENSE", "THIRD_PARTY.md", "CONTRIBUTING.md",
    "SECURITY.md", "AGENTS.md", ".gitignore", ".gitattributes", "package.py",
    "requirements-dev.txt", "Install-Zitatlotse.ps1", "Start-Zitatlotse.ps1",
    "test_plugin.js", "test_search_session.js", "smoke_service_start.js",
    "smoke_autostart.ps1",
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
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))["version"]
    # Stable file ordering makes it easy to inspect what is distributed.
    xpi = args.output / f"Zitatlotse-{version}.xpi"
    with ZipFile(xpi, "w", ZIP_DEFLATED) as archive:
        for name in PLUGIN:
            archive.write(ROOT / "plugin" / name, name)
    source = args.output / f"Zitatlotse-{version}-source.zip"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        for file in source_files():
            archive.write(file, file.relative_to(ROOT).as_posix())
    checksums = args.output / "SHA256SUMS.txt"
    checksums.write_text("".join(
        f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
        for file in (xpi, source)), encoding="utf-8")
    for file in (xpi, source, checksums):
        print(file)


if __name__ == "__main__":
    main()
