# Zitatlotse

**Your library. Your models. Evidence inside Zotero.**

An experimental Zotero 10 add-on for finding original PDF passages, checking claims against supporting and opposing evidence, and keeping quotations with notes and citation styles.

![Actual AI chat in Zotero](docs/assets/screenshots/ai-chat-example.png)

*Crop of an actual previously captured Zotero view. [Screenshot gallery and capture status](docs/SCREENSHOTS.md).* 

## Features

- Direct local search: conservative topic prefilter → cosine over remaining chunks → BERTScore reranking.
- Library and collection scopes, including subcollections; results stay in the selected library.
- AI chat that formulates queries for the PDF languages, selects original passages and writes a short cited answer.
- Optional agentic retrieval with real tool calls, a step limit and an activity view.
- Claim checking with supporting, opposing and neutral passages and a proportional evidence bar.
- Animated document overview based on each PDF's highest chunk cosine similarity; duplicate indexed content is grouped.
- Double-click or open a quotation in the Zotero PDF reader, with a temporary text highlight when its position can be resolved.
- Persistent saved quotations, search, notes, copying and Zotero CSL citation styles.
- Nine curated embedding profiles and compatible custom Hugging Face dense text encoders; confirmed atomic index rebuilds when changing models.
- OpenAI, Anthropic, DeepSeek or local Ollama; provider model catalogs and manual model identifiers.
- Individual and library-wide PDF processing, automatic indexing of new PDFs, progress indicators and German/English UI following Zotero's locale.
- Chat and direct-search state survive closing the panel; reset buttons or restarting Zotero clear these views. Saved quotations remain.

## Install on Windows

Requires Zotero 10 on Windows x64, locally available text PDFs, and disk space for the bundled runtime and models.

Download **Zitatlotse-0.27.0.xpi** from the [release page](https://github.com/Cuzimnero/zitatlotse/releases) (public release currently in preparation), install it through Zotero's add-on manager and restart Zotero. Python, CPU libraries and backend are included. Zotero sets up and starts local search automatically with visible progress. No separate installer, Python installation or manual service launch is required.

Process a PDF or item, then open the purple quotation button. Search model weights download on first use. Cloud AI is optional. For local AI, run Ollama and select an installed model.

## Status and data

Version **0.27.0 is experimental**. Bundled-runtime setup without Python on PATH, real service availability, complete process loss/restart and database preservation were tested. Zotero starts the service and checks every 30 seconds while open. The earlier Windows-task startup had a known recovery gap. A real Windows reboot remains necessary. The first post-restart query took about 83 seconds in an earlier local run. There is no ANN index, integrated OCR or automatic XPI update.

Embeddings, BERTScore and the SQLite index are local. Cloud providers receive your question and retrieved PDF passages; their API usage may cost money. Keys use the OS credential store. The local database is not encrypted by the add-on.

Document chart percentages represent the number of documents in relative score groups, not a relevance probability. Pro/contra percentages represent retrieved passage counts, not truth or study quality.

## Documentation

The detailed documentation is currently in German:

- [Complete feature catalog](docs/FEATURES.md)
- [Installation](docs/INSTALLATION.md)
- [Workflows](docs/WORKFLOWS.md) and [architecture](docs/ARCHITECTURE.md)
- [Test status and limitations](docs/STATUS.md)
- [Data handling](docs/DATA.md) and [testing](docs/TESTING.md)
- [Contributing](CONTRIBUTING.md)

## License

The project's own source is [MIT licensed](LICENSE). Dependencies and model weights have their own terms, including PyMuPDF's AGPL/commercial options. See [third-party notices](THIRD_PARTY.md). This is an independent project, not an official Zotero product.
