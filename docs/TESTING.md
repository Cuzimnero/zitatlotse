# Run tests

[Project page](../README.md) · [Current test status](STATUS.md)

## 1. Isolated tests with no AI costs

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s backend -p "test_*.py"
node test_plugin.js
node test_search_session.js
node test_runtime.js
python package.py --source-only
```

These tests use temporary/synthetic data and simulated encoders or provider responses. They test logic and failure cases, not real model quality. Node.js is required for plugin tests. Windows CI runs the same checks and does not download model weights. No CI result has been published in advance.

## Set up the XPI without Python on `PATH`

```powershell
python build_runtime.py
python package.py
.\test_runtime_setup.ps1 -Xpi .\dist\Zitatlotse-0.27.0.xpi -TestRoot .\outputs\runtime-test -Port 18765
```

The check installs the bundled runtime in a separate test folder, removes Python from `PATH` and blocks model downloads. It checks actual service availability, progress, recovery after complete process loss and preservation of the test database. It does not use the regular installation on port 8765 or make cloud requests. It does not reboot the operating system.

## 2. Real local models with synthetic PDFs

Install the full backend dependencies:

```powershell
python -m pip install -r backend\requirements.txt
python backend\smoke_model_catalog.py intfloat/multilingual-e5-small
```

The script creates synthetic PDFs and a temporary index. It checks actual model inference, passage location, library boundaries, an unrelated query and reloading the index. Missing model weights are downloaded. `HF_HOME` can point to an existing cache; set `HF_HUB_OFFLINE=1` to prevent downloads if all required weights are already cached.

To test a custom embedding model with a synthetic database:

```powershell
python backend\smoke_custom_embedding.py --cache .\outputs\model-cache --output .\outputs\custom-model.json
```

This script uses a fixed small Hugging Face test encoder and an isolated database. It does not replace a model change against a real user library.

## 3. Live AI search runs

`backend/smoke_ai_search.py` uses the **configured provider** of the running service. It may transmit document text and incur costs. Use only deliberately selected test documents. The `--live` flag is required.

```powershell
python backend\smoke_ai_search.py --live --library 1 --case dino_teacher --case unrelated --attachment-key YOUR_DINO_KEY --output .\outputs\ai-search.json
```

Replace `YOUR_DINO_KEY` with the attachment key for your processed DINO PDF. The example queries expect relevant DINO/MiVOLO/distillation papers and are not valid positive tests for an arbitrary library. Create new verified cases for other documents.

To replay a real result through the UI logic:

```powershell
$env:ZITATLOTSE_LIVE_REPORT = '.\outputs\ai-search.json'
node test_search_session.js
Remove-Item Env:\ZITATLOTSE_LIVE_REPORT
```

The report may contain original text and source identifiers. It is intentionally excluded from Git and must not be published without review. The replay uses the shipped UI logic in a simulated document tree, not a real Zotero window.

## 4. Windows cold starts and failures

These tests **interrupt the installed Zitatlotse service** and restore it afterward. They may take several minutes. Do not run them during your own processing.

```powershell
.\smoke_autostart.ps1 -ColdCycles 3 -TestEarlyCrash -Output .\outputs\cold-start.json
```

Test complete process loss after an automatic scheduled start:

```powershell
.\smoke_autostart.ps1 -SupplementaryOnly -TestSchedulerRecovery -TestScheduledTrigger -Output .\outputs\whole-service-failure.json
```

**The current version does not pass the automatic recovery portion of this test.** A temporary one-time scheduled task is created for the test and removed afterward. The actual PC is not rebooted.

Optional direct search after a cold start using your own test PDFs:

```powershell
.\smoke_autostart.ps1 -SupplementaryOnly -TestLocalSearch -LibraryId 1 -DinoAttachmentKey YOUR_DINO_KEY -TestAttachmentKeys YOUR_DINO_KEY,YOUR_MIVOLO_KEY,YOUR_DISTILLATION_KEY -Output .\outputs\cold-search.json
```

The keys refer to **your own** indexed Zotero attachments. No personal keys are stored in the script. `Average` must occur in the test corpus; the unrelated clinical negative case must not match relevant literature there.

## 5. Native Zotero checks

Also check manually:

- Install the XPI and restart Zotero.
- Verify that only one working sidebar icon appears; test open/close and a small window.
- Confirm that mode, collection and model dropdowns do not accidentally close the window.
- Process one PDF, one item and all new/changed PDFs.
- Test direct, AI and supporting/opposing searches in the correct scope.
- Double-click an original passage; verify the page and highlight.
- Test citation style, save, note, search and copy.
- Closing/reopening preserves history; reset and restarting Zotero clear temporary views.
- Confirm a model change, successful activation and error fallback to the previous index.
- Perform a real Windows reboot and sign-in; measure service readiness separately from the first search.

This checklist describes required checks; it does not claim that all native tests have passed.
