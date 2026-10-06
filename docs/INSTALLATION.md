# Installation and updates

[Project page](../README.md)

## Requirements

- Zotero **10.0.x** on **Windows x64**.
- PDFs available locally with extractable text. Zitatlotse does not perform OCR.
- Disk space for the bundled CPU runtime and selected models.
- Internet access for the first download of a search model.
- Optional: Ollama with a model installed, or an API key.

## Standard installation: the XPI only

1. Download **Zitatlotse-0.27.0.xpi** from [Releases](https://github.com/Cuzimnero/zitatlotse/releases). The first public release is still being prepared.
2. In Zotero, choose **Tools → Add-ons → Install Add-on From File** and select the XPI.
3. Restart Zotero. The add-on installs its bundled local runtime in your user profile and starts the search service automatically.
4. Open the purple button. A progress bar shows setup, checks and startup. If setup fails, choose **Check search service** to retry.
5. Process a PDF or library item. The selected embedding model and BERTScore model are downloaded on first use.

**No separate Python installation, extra installer script or manual service launch is needed.** The XPI contains Python, CPU libraries and backend code. The runtime is extracted from the installed add-on. Model weights remain separate downloads because of their size and the user's choice of model.

Direct search does not need an AI key. For AI search, choose a provider and model under **Connections**. Ollama itself is an optional external program.

## Updates

Install the new XPI and restart Zotero. The add-on detects the new backend version and updates its code automatically. The database, settings, model cache and saved quotations remain at their existing data path. Changing the embedding model offers a separate, confirmed index rebuild.

During a code update, the add-on restarts its own service. Do not start an update while processing or an AI request is running.

## Startup and recovery

- Start when the add-on loads in Zotero.
- Check again when the search window opens or the connection is interrupted.
- A shared startup promise prevents duplicate launches from simultaneous UI requests.
- While Zotero is open, check service availability every 30 seconds and restart a lost process tree.
- The supervisor restarts a crashed worker.
- A failed setup is reported in the UI; **Check search service** starts another attempt.

The standard installation needs no Windows scheduled task or administrator rights. The old manual installer remains in the source as a developer/legacy path. The XPI does not automatically remove a Windows task created by an earlier installation.

## Paths and diagnostics

| Contents | Location under `%USERPROFILE%\.zitatlotse` |
| --- | --- |
| Bundled Python runtime | `runtime\<package-id>` |
| Installed version and startup paths | `installation.json` |
| Setup progress | `setup-state-0.27.0.json` |
| Index and saved quotations | `backend\data\quotes.sqlite` |
| Model cache | `backend\data\models` |
| Settings without keys | `backend\data\settings.json` |
| Runtime checks | `runtime-check.log`, `runtime-error.log` |
| Service log | `backend\data\service.log` |

Keys are stored in the operating system's credential store. Do not share diagnostic logs or databases publicly without reviewing them.

A successful health check confirms that the service is running. Models load on demand afterward, so the first search can take longer.

## Build a release locally

Only developers need Python and Node.js:

```powershell
python build_runtime.py
python package.py
```

The Windows build downloads the official embedded Python, verifies its SHA-256, checks library imports and builds the complete XPI. Package versions and license files are included in the runtime. `python package.py --source-only` creates only the source archive. A UI-only package is not built as a finished release XPI.

Other operating systems are not yet supported as complete installation distributions.
