# Test status — 0.30.0

**31 October 2026 · Experimental release**

- All **136 Python test methods** and **three JavaScript test programs** passed.
- The release XPI passed integrity/source checks, isolated Windows setup without external Python, restart after full test-process loss, and database preservation.
- New checks cover progressive pagination, empty result windows, scope boundaries, cache invalidation, memory limits, AI-call budgets and complete evidence batches.
- Offline real-model experiment: first page **2.11 → 0.66 s**; complete retrieval about **2.25 s** across 120 synthetic chunks. No private PDFs, downloads or cloud calls.

Model/provider doubles verify behavior, not live API compatibility or retrieval quality. Native visual checks, a real Windows reboot, cold-start improvements and broad quality/scale benchmarks remain pending. Search uses an exact cosine scan; scanned PDFs require prior OCR. Automatic XPI updates remain disabled.

[Acceleration details](PERFORMANCE-EXPERIMENT.md) · [Repeat the tests](TESTING.md) · [Per-test catalogue](TESTPLAN.de.md) · [Project](../README.md)
