# Search acceleration — 0.30.0

Enabled by default. Toggle **Settings → Search speed → Try search acceleration** to compare with the previous workflow. No index rebuild is required.

- **Fewer AI calls:** normal AI search starts with planning and review. Native follow-up runs only when evidence is missing and multi-step search is enabled. Planning, retries and tool turns share a five-request ceiling per chat job. DeepSeek planning disables thinking; review retains it.
- **Earlier results:** Normal mode initially BERT-scores up to 40 candidates. Remaining candidates stay available through pagination. Published pages keep their order; initial results are provisional rather than a complete global ranking. Extra pages are locally checked, not automatically AI-selected.
- **Caching:** reuse query embeddings (128-entry LRU) and document matrices (64 MiB budget). Larger libraries stream from SQLite. Database/model changes invalidate matrix snapshots; scope filters remain enforced.
- **Evidence:** classify all retrieved passages in batches of up to 24, reduced for longer text. Full evidence classification is exempt from the chat call ceiling. Native evidence follow-up is limited to three calls.

## Verification

136 Python methods, three JavaScript programs, XPI integrity and isolated Windows setup/process-loss restart passed. No cloud calls or private PDFs were used.

In three paired warm runs with 120 synthetic chunks, E5 Small and multilingual BERTScore, median first-page time fell from **2.11 s to 0.66 s**. Full retrieval remained about **2.25 s**, with all 120 locations reachable. This measures earlier delivery, not improved search quality or cold-start speed. Live provider timing and native visual checks remain separate.
