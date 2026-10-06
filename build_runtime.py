"""Build the application-local Windows x64 Python runtime shipped inside the XPI.

Only release builders need Python/pip. End users receive this entire runtime;
they never install packages or start a separate service themselves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
PYTHON_VERSION = "3.13.16"
PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"


def download(url: str, destination: Path, expected_hash: str):
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected_hash:
        return
    with urlopen(url, timeout=90) as response, destination.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != expected_hash:
        raise ValueError(f"Download checksum mismatch: {destination.name}")


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def corresponding_source(work: Path, packages: list[dict], mupdf_version: str):
    """Distribute the unmodified AGPL source alongside its bundled binary wheel."""
    version = next(package["version"] for package in packages if package["name"].lower() == "pymupdf")
    with urlopen(f"https://pypi.org/pypi/PyMuPDF/{version}/json", timeout=30) as response:
        data = json.load(response)
    source = next(file for file in data["urls"] if file["packagetype"] == "sdist")
    path = work / source["filename"]
    download(source["url"], path, source["digests"]["sha256"])
    request = __import__('urllib.request', fromlist=['Request']).Request(
        f"https://api.github.com/repos/ArtifexSoftware/mupdf-downloads/releases/tags/{mupdf_version}",
        headers={"User-Agent":"Zitatlotse-release-builder"})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    mupdf = next(asset for asset in release["assets"] if asset["name"] == f"mupdf-{mupdf_version}-source.tar.gz")
    digest = mupdf.get("digest", "")
    if not digest.startswith("sha256:"):
        raise ValueError("Official MuPDF source checksum missing; review distribution before release.")
    mupdf_path = work / mupdf["name"]
    download(mupdf["browser_download_url"], mupdf_path, digest.removeprefix("sha256:"))
    with tarfile.open(mupdf_path) as archive:
        names = archive.getnames()
        if not any("source/pdf/" in name for name in names) or not any("thirdparty/" in name for name in names):
            raise ValueError("MuPDF source archive is incomplete")
    output = work.parent / "third-party-sources.zip"
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.write(path, path.name)
        archive.write(mupdf_path, mupdf_path.name)
        archive.writestr("README.txt", "Unmodified PyMuPDF/MuPDF corresponding source.\n"
            f"Version: {version}\nOriginal source: {source['url']}\n"
            f"SHA256: {source['digests']['sha256']}\n"
            "License and build instructions are included in the upstream source archive.\n"
            f"MuPDF: {mupdf['browser_download_url']}\n{digest}\n"
            "MuPDF's archive includes its third-party source and notices.\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "runtime-build")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Build and verify the Windows runtime on Windows.")
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=True)
    runtime = work / "python"
    runtime.mkdir(exist_ok=True)
    embedded = work / "python-embedded.zip"
    download(PYTHON_URL, embedded, PYTHON_SHA256)
    with ZipFile(embedded) as archive:
        archive.extractall(runtime)
    # The official isolated distribution deliberately ignores PATH/PYTHONPATH.
    # Explicitly include our vendored packages; the launcher adds the backend.
    (runtime / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    site = runtime / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    python = runtime / "python.exe"
    # Bootstrap pip from its official wheel (with PyPI's SHA-256), not get-pip.py.
    with urlopen("https://pypi.org/pypi/pip/26.0.1/json", timeout=30) as response:
        pip_metadata = json.load(response)
    wheel = next(file for file in pip_metadata["urls"] if file["filename"].endswith(".whl"))
    pip_wheel = work / wheel["filename"]
    download(wheel["url"], pip_wheel, wheel["digests"]["sha256"])
    with ZipFile(pip_wheel) as archive:
        archive.extractall(site)
    # CPU builds avoid bundling CUDA libraries into a general-purpose add-on.
    lock = ROOT / "runtime" / "requirements-lock.txt"
    torch_requirement = next((line for line in lock.read_text().splitlines() if line.startswith("torch==")), "torch>=2.10,<3") if lock.exists() else "torch>=2.10,<3"
    run(python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
        "--no-compile", torch_requirement, "--index-url", "https://download.pytorch.org/whl/cpu")
    run(python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
        "--no-compile", "-r", lock if lock.exists() else ROOT / "backend" / "requirements.txt")
    run(python, "-m", "pip", "check")
    run(python, "-c", "import fitz, torch, numpy, sentence_transformers, bert_score, keyring; "
        "assert not torch.cuda.is_available(); print('Bundled runtime imports: OK')")
    packages = json.loads(subprocess.check_output([str(python), "-m", "pip", "list", "--format=json"], text=True))
    mupdf_version = subprocess.check_output([str(python), "-c", "import pymupdf; print(pymupdf.version[1])"], text=True).strip()
    corresponding_source(work, packages, mupdf_version)
    (runtime / "PACKAGES.json").write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")
    (runtime / "SOURCE-INFO.txt").write_text(
        "Python: " + PYTHON_URL + "\nSHA256: " + PYTHON_SHA256 + "\n"
        "Python license: LICENSE.txt in this directory.\n"
        "Package licenses and copyrights: Lib/site-packages/*dist-info/licenses or LICENSE* files.\n"
        "Source for exact package versions: https://pypi.org/project/<name>/<version>/#files\n"
        "PyTorch CPU source: https://github.com/pytorch/pytorch (tag matching PACKAGES.json).\n"
        "PyMuPDF/MuPDF are AGPL; see the corresponding-source release asset.\n", encoding="utf-8")
    archive_path = work.parent / "windows-x64-runtime.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(runtime.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts and "Scripts" not in file.relative_to(runtime).parts and file.suffix != ".pyc":
                archive.write(file, file.relative_to(runtime).as_posix())
    manifest = {"platform": "win-x64", "python_version": PYTHON_VERSION,
                "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(), "packages": packages}
    archive_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(archive_path, flush=True)


if __name__ == "__main__":
    main()
