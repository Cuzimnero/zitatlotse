# Feature catalog

[Project page](../README.md)

As of **0.27.0**. This list describes implemented features. Their presence does not mean that every combination of PDFs, models and Zotero versions has been tested reliably. See [test status](STATUS.md).

## 1. Zotero interface

- A purple quotation-mark button in the right sidebar opens AI search.
- A dedicated Zitatlotse menu provides access to search, connections and PDF processing.
- Central views for AI search, direct search, saved quotations, connections and settings.
- German and English; the add-on follows Zotero's selected language and defaults to English.
- A centered search window that adapts to the available space.
- Opening animation from the sidebar button and a reversed closing animation when clicked again.
- Close using the top-right X, Escape or the background.
- Highlighted border around the AI chat area with the purple product theme.
- Animated progress indicators for search, processing and connections; animated page-turning PDF pages below the question field.

## 2. Process PDFs

- **Process this PDF:** index the selected PDF attachment.
- **Process this item:** index PDFs attached to the selected library item.
- **Process all new or changed PDFs:** scan the selected library and process missing or changed attachments.
- Automatically queue newly added PDF attachments for processing.
- Associate the library, item and attachment IDs, title, authors, year, language, collections and PDF locations with the local index.
- Read language from Zotero metadata, or estimate it from the text.
- Report files that are unavailable locally or cannot be read.
- Show the number of processed PDFs and created chunks, plus library scan progress.

## 3. Chunks and automatic topic features

- Extract PDF pages individually and normalize whitespace.
- Create chunks of up to 100 words with up to 20 words of overlap.
- Prefer sentence boundaries; split a long sentence internally when needed.
- Never let a chunk cross a PDF page boundary.
- Generate up to 16 document topic features from content words, word pairs and the Zotero title.
- Store the normalized mean of chunk vectors as the topic vector.
- Store features, metadata, text, normalized vectors and later saved quotations in a dedicated SQLite database.

Topic features are an automatically generated local search aid. They are not an LLM-verified content summary.

## 4. Search scope

- Every search uses exactly one Zotero library.
- Select a collection and include its subcollections.
- Read the current PDF attachments for the selected scope from Zotero and validate the fixed selection in the service.
- An explicitly empty selection stays empty; it does not expand to the whole library.
- Direct search, AI search, tool calls and the document chart use the same selected scope.
- Cancel in-flight queries or discard late responses when the scope changes.
- Search state must not be reused for a different library or a different file selection.

## 5. Direct search

- Runs without a cloud LLM: coarse topic prefilter, cosine comparison across all remaining chunks, then BERTScore reranking.
- Match short terms, acronyms and literal queries regardless of capitalization.
- Keep distinct real locations where a word occurs.
- Deduplicate repeated original passages caused by overlapping chunks.
- Discard hits that score too weakly locally.
- Show quotations with paper title, PDF page, original text and search scores.
- Paginate results with up to 20 quotations per page.
- Reopen already loaded pages; the service retains search state for up to 15 minutes.

## 6. AI search

- Accept a question in natural language, such as a German question about English papers.
- Formulate one search query per document language and retain the original question as an additional variant.
- Use the local search pipeline for the formulated queries.
- Let the selected model assess retrieved original passages.
- Generate a short answer with numbered references to checked passages.
- Display only valid source references.
- By default, show quotations selected by the AI.
- **Show all results** switches to other already retrieved candidates.
- If no reliable evidence is found, do not mark any quotations as selected.
- If AI is unavailable, show a notice and fall back to stricter local search where possible.

The AI sees a limited set of retrieved candidates. **All results** does not mean every possible passage in the whole library.

## 7. Multi-step search / agentic calls

- Use the real `search_library` and `finish_search` tools when the provider and model support them.
- Formulate follow-up queries after a search, return results and refine the search.
- Stay within the library and collection scope set by the service.
- Merge results from different steps and deduplicate passages.
- Reuse identical queries already run for the current question.
- Enable or disable the feature; set a limit of 1–6 search steps, default 3.
- Limit agent steps with a time budget; an ongoing local computation may outlast this budget.
- If tool calls are unsupported or the response is invalid, show a notice and fall back to the one-step flow.
- Optional activity view shows events such as query planned, model called, local search started, results returned, another tool call and completion.

The activity view shows technical search events and queries, not private model reasoning.

## 8. Find evidence: supporting and opposing

- Enter a claim rather than an open question.
- Search for supporting and opposing aspects; use multi-step search when enabled and available.
- Ask the AI to assess retrieved candidates in groups.
- Distinguish supporting, opposing and neutral/unclear evidence.
- Distinguish direct evidence from evidence about a related aspect.
- Show concise findings and reasons with original quotations and paper references.
- Make neutral candidates available through the all-results view.
- Calculate the red/green bar from the count of supporting and opposing passages; count neutral passages separately.

For example, 6 supporting, 4 opposing and 3 neutral passages produce 60% supporting and 40% opposing in the bar, plus 3 neutral passages. This says nothing about completeness, study quality or truth.

## 9. Estimated document relevance

- For each processed document, find the **highest chunk cosine similarity** to the query.
- Consider every chunk in the selected scope, regardless of quotation filters or AI selection.
- Reuse available language-specific AI query variants for their corresponding document languages.
- Divide the observed score range into relative color groups; handle equal or missing values separately.
- Show an animated ring chart with the document count and group shares.
- Select a group to view its documents, scores and best PDF pages.
- Group identical indexed content using text, page and chunk fingerprints.
- Paginate the document list and open PDFs from it.
- Show the active model and model/language notices.

A group containing 28% can have lower scores than a group containing 14%: the percentages count documents. Each document shows its own similarity value.

## 10. PDF location and citation

- **Open in PDF** or double-click the quotation text to open the Zotero reader.
- Pass the PDF page and, where available, rectangles for the text passage.
- Temporarily highlight the passage; do not create a persistent Zotero annotation automatically.
- If matching text coordinates cannot be found, open the PDF page instead.
- Copy the original text with an in-text citation and PDF page locator.
- Choose installed Zotero CSL citation styles in settings.

## 11. Saved quotations and sessions

- Save a quotation to the local database and reopen it later.
- Search saved quotations in the selected library.
- Add or edit a note, copy a quotation or remove it.
- Saved data persists when the window closes or Zotero restarts.
- Keep chat messages, drafts, direct search queries and displayed results when the window closes.
- Keep separate session state for each library.
- Reset the chat or direct-search view; restarting Zotero clears these temporary views.
- Do not restore stale responses that arrive after a reset.

## 12. Embedding models

| Profile | Focus |
| --- | --- |
| `intfloat/multilingual-e5-small` | Compact multilingual default. |
| `intfloat/multilingual-e5-base` | Larger multilingual alternative with higher compute requirements. |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Compact multilingual sentence similarity. |
| `sentence-transformers/all-MiniLM-L6-v2` | Small English model. |
| `mixedbread-ai/deepset-mxbai-embed-de-large-v1` | Large German/English encoder for passage search. |
| `BAAI/bge-m3` | Multilingual; Zitatlotse uses its dense vectors. |
| `Qwen/Qwen3-Embedding-0.6B` | Multilingual search with task instructions; higher resource requirements. |
| `BAAI/bge-small-en-v1.5` | Compact English passage search. |
| `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` | Compact English question-answer search. |

- Show a brief description of each model's benefits and resource requirements.
- Enter a custom model using its Hugging Face `organization/model` ID or model page URL.
- Choose automatic, Plain, E5, BGE, Qwen or custom query/passage prefixes.
- Configure model revision and batch size.
- Check compatibility from model metadata; a supported dense text encoder is required, not an arbitrary chat, classification or QA architecture.
- Never activate remote model code through `trust_remote_code`.
- Explain that the encoder and search formulation must support the languages in the documents.
- Confirm model changes, then recalculate all stored chunk and topic vectors across libraries.
- Keep the previous index active until the rebuild succeeds; roll back if it fails.
- Preserve saved quotations and notes when changing models.

The profiles are comparison candidates, not a ranking that guarantees search quality. Model descriptions are in code and should be checked against each model card.

## 13. AI providers and model lists

- Connect **OpenAI**, **Anthropic**, **DeepSeek** or **Ollama**.
- Store cloud provider API keys in the operating system's credential store.
- Suggest a suitable default model identifier when the provider changes.
- Fetch and refresh the model list from the selected provider.
- Select installed Ollama models.
- If the catalog cannot be retrieved, show suggestions and still allow manual model IDs.
- Save and test the connection; cloud tests call the API and can incur costs.
- Store agentic search and the activity view independently from the connection.
- Do not assume every model in a catalog supports the required text or tool features.

## 14. Local service on Windows

- Standard XPI installation with bundled Python, CPU libraries and backend under `%USERPROFILE%\.zitatlotse`.
- Bind the search server only to `127.0.0.1:8765`.
- Zotero automatically sets up the runtime and starts it when the add-on loads or the search window opens.
- Show setup progress and retry failed setup.
- Check service availability every 30 seconds while Zotero is open.
- Coalesce concurrent start requests and use an operating-system lock to prevent duplicate supervisors.
- Restart a crashed search worker with increasing delays.
- Keep separate setup and service logs.
- Preserve the index and models across updates; retain the previous installation as a migration backup.

The old manual installer and its Windows startup task remain as legacy/developer paths. A real Windows reboot still needs testing. See [status](STATUS.md).
