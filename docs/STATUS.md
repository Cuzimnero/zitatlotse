# Test status and known limitations

[Project page](../README.md)

**As of 9 October 2026 · Version 0.27.0 · Experimental prototype**

## New standard XPI installation

- Official embedded Python 3.13.16 runtime, CPU PyTorch and backend are bundled in the XPI.
- Successfully set up the real runtime from the XPI archive in an isolated test folder, with Python removed from `PATH` and model downloads disabled.
- Health check of the actual service, empty library and progress completion: successful.
- Complete loss of supervisor and worker followed by restart from the same package; the database and an additional test file were preserved: successful.
- Simulated Zotero startup: first install, cached runtime, older service version, concurrent requests, setup failure and retry, and a foreign process on the port: successful.
- 104 backend tests on the newly bundled Python runtime: successful; plugin and session checks also passed.
- Real E5/BERTScore check with a synthetic PDF: processing, positive hit, location and library boundary worked. An unrelated negative query still returns a hit. The same issue occurs with the previous runtime; the new installer does not fix this existing relevance weakness. The complete model smoke test is therefore considered failed.

Zotero handles setup and startup and checks the service every 30 seconds. The standard path does not need a separate Python installation, manually launched service or Windows task.

An actual PC reboot and complete first installation through Zotero's native add-on manager have not yet been confirmed by these isolated tests. The startup measurements below relate to the previous 0.26.3 version.

## What was tested

| Check | Observation |
| --- | --- |
| Isolated backend tests | 104 tests for search, scope, models, provider responses, evidence tally, jobs, document chart, storage and launcher. |
| Plugin tests | Processing, locale, reader calls, libraries/collections, model selection and startup function in a simulated Zotero environment. |
| Session/display tests | Chat, reset, filters, pagination, document chart and reopen in a simulated document tree. |
| Real local search pipeline | Model and PDF smoke tests plus direct queries against an existing index. |
| Earlier live AI runs | Positive DINO/distillation questions and an unrelated negative case tested with the configured provider; actual results replayed through UI logic. No automated cloud-based CI. |

Some isolated tests use simulated vectors and provider responses. They do not measure real retrieval quality. The simulated Zotero environment does not replace manual checks in the native client. The [Windows GitHub Actions run](https://github.com/Cuzimnero/zitatlotse/actions/runs/37955567562) passed backend, plugin, session, startup/provisioning and source packaging checks on 9 October 2026 after adding the missing Hugging Face metadata dependency to the isolated test requirements. The [screenshot gallery](SCREENSHOTS.md) records the actual installed interface, without claiming full native workflow coverage.

## Earlier Windows cold-start and failure tests (0.26.3)

The tests stopped only the installed Zitatlotse processes, started the Windows task or the shipped menu-start function and checked actual HTTP availability.

| Case | Last observation |
| --- | --- |
| Three additional full cold starts | 3/3 succeeded; about 2.87–2.90 seconds to HTTP availability. |
| Another registered startup check | Succeeded; about 5.16 seconds. |
| Two simultaneous menu startup requests | Succeeded; one launcher process started. |
| Stale lock file | Did not prevent a new start when no old process was alive. |
| Worker-only crash | Recovered under the same supervisor in about 4.84–5.22 seconds. |
| Database temporarily locked at startup | Worker exited early; after the lock was released, it recovered under the same supervisor. |
| Actual scheduled time trigger | Startup succeeded about 4.01 seconds after task execution. |
| Complete loss of supervisor and worker | **Failed: Windows did not automatically recover within 100 seconds.** |

The full loss was also observed with explicit exit code 1 and after an automatic scheduled start. Task retry settings were present; the reason automatic recovery failed has not been isolated. The regular service was restored after testing and the temporary task was removed.

**Not performed:** actual PC reboot, sign-out/sign-in, clearing the Windows file cache and changing network conditions during boot. The time trigger checks scheduled execution, not the actual logon trigger.

## Real direct search after a process restart

Measurements from a small local library with 11 PDF attachments, 1,611 chunks and Multilingual E5 Small. These are examples from one PC, not a general benchmark.

| Query / scope | Total hits | Duration |
| --- | ---: | ---: |
| `Average`, entire test library | 44 | 83.02 s |
| DINO momentum teacher, matching test PDF | 22 | 3.67 s |
| Unrelated clinical migraine question, restricted paper selection | 0 | 26.16 s |

The first query includes model initialization and search; those durations were not measured separately. A fast health check does not mean the first search will be fast. Index and quotation counts remained intact during the failure test.

## Known limitations

- **Service loss:** verify recovery on real boots and during longer sessions.
- **Cold start:** a visible model loading state and targeted preloading could make the first search easier to understand.
- **Retrieval:** thresholds depend on model, language and query. There is no broad recall/precision benchmark yet.
- **Large libraries:** exact cosine scan is linear, BERTScore adds cost, and there is no ANN index.
- **PDFs:** no built-in OCR; tables, formulas, columns and unusual text extraction can affect quotations or coordinates.
- **Pages:** PDF page locators may differ from printed page numbering.
- **AI:** candidate context is limited; a model can miss evidence or classify it incorrectly. Tool support depends on provider and model.
- **Charts:** relative similarity groups and passage counts are not probabilities or quality ratings.
- **UI:** native checks in small Zotero windows, dropdowns, reader navigation and animations remain necessary.
- **Installation:** complete distribution targets Windows; other platforms are not verified as finished distributions.
- **Updates:** no automatic add-on updates.
- **Reproducibility:** release runtime records exact package versions in `PACKAGES.json`; changes to the runtime build need separate verification.

## Recommended next steps

1. Make supervisor recovery and actual Windows restarts reliable.
2. Build a small reference library with verified expected passages, missing-evidence cases and language variants.
3. Measure retrieval quality and runtime per model and library size; derive thresholds from those measurements.
4. Automate PDF navigation and window operation in native Zotero.
5. Choose an ANN index and batching/cache improvements based on measured bottlenecks.
6. For a stable release, reproducibly record dependencies, model data, installation paths and license notices.
