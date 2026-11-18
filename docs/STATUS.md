# Test status — 0.32.0

**18 November 2026 · Experimental release**

- All **155 Python test methods** and **four JavaScript test programs** passed.
- The release XPI passed integrity/source checks, isolated Windows setup without external Python, restart after full test-process loss, and database preservation.
- New checks cover language routing in AI, evidence and tool searches, collection boundaries, processing status and duplicate filtering.
- Two offline local search comparisons showed **38.74–41.87 s before** and **1.53–1.81 s after** the duplicate filtering change. Three further local runs verified that English documents used only the English query. See the [release notes](releases/v0.32.0.md) for benchmark scope.

Model/provider doubles verify behavior, not live API compatibility or retrieval quality. Native visual checks, a real Windows reboot, cold-start improvements and broad quality/scale benchmarks remain pending. Search uses an exact cosine scan; scanned PDFs require prior OCR. Automatic XPI updates remain disabled.

[Acceleration details](PERFORMANCE-EXPERIMENT.md) · [Repeat the tests](TESTING.md) · [Per-test catalogue](TESTPLAN.de.md) · [Project](../README.md)
