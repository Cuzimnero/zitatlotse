# Data and privacy

[Project page](../README.md)

## What stays local

PDF files are read from their local Zotero paths. Zitatlotse stores text chunks, metadata, language, topic features, vectors and saved quotations in its own SQLite database. The search service does not write directly to Zotero's database.

Embedding generation, BERTScore and the document chart run locally. Direct search does not require a cloud provider. Initial downloads of packages or model weights still require an internet connection; the query is not sent to a Zitatlotse server for search evaluation.

The database also contains extracted document text and local file paths. Zitatlotse does not add database encryption. Access control and backups depend on your operating system and environment.

## What may be sent to an AI provider

With OpenAI, Anthropic or DeepSeek, your question, generated search queries and retrieved original passages are sent to the selected provider. Single-step search sends a limited selection. Multi-step search may include additional passages and previous tool results in each step's context. Evidence mode may ask the model to assess many retrieved candidates in several groups.

A connection test also uses the selected API. Model catalogs are fetched from the provider. Privacy terms and API costs depend on that provider.

Ollama is accessed as a local HTTP server. Its models must already be installed. Zitatlotse does not operate a cloud search service and does not require an account.

## Keys and sessions

- API keys: stored through `keyring` in the operating system's credential store.
- Connection settings without keys: local `settings.json`.
- Search and chat views: held in the Zotero session, separately for each library. Reset or restart Zotero to clear them.
- Saved quotations and notes: stored persistently in SQLite.
- Search states on the service: expire after a limited period and cannot be reused after a service restart.
- Activity view: shows concrete search events and queries, not private model reasoning.

## Local HTTP interface

The server binds to `127.0.0.1:8765`. Write and search requests use the client header `X-Zitatlotse-Client: 1`; this is **not a secret authentication token**. The interface is intended for the local user and must not be exposed to a network.

## Public bug reports

Do not attach databases, PDFs, model weights, keys, full provider responses or unredacted logs. Prefer a small synthetic test case with the version, models, question, search mode, scope and an anonymized error message. Test output may itself contain document text and must be reviewed before sharing.
