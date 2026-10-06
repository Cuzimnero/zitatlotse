# Abhängigkeiten und Modelle

Die MIT-Lizenz dieses Repositorys gilt für den eigenen Quellcode und die eigenen Dokumentationsgrafiken. Sie ersetzt keine Lizenz einer Abhängigkeit, eines Modells oder eines Dokuments. Pakete und Modellgewichte werden separat geladen; sie sind nicht Bestandteil des Quellcode-Archivs oder der XPI.

## Bibliotheken

| Projekt | Verwendung | Offizielle Quelle |
| --- | --- | --- |
| Zotero | Bibliotheken, Metadaten, Reader, CSL-Zitierstile und Add-on-Oberfläche | [Zotero](https://www.zotero.org/support/dev/start) |
| PyMuPDF / MuPDF | PDF-Text, Seiten und Koordinaten | [Lizenz und Copyright](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) |
| SentenceTransformers | Lokale dichte Text-Embeddings | [Repository](https://github.com/huggingface/sentence-transformers) |
| Transformers | Modellarchitekturen und Tokenizer | [Repository](https://github.com/huggingface/transformers) |
| BERTScore | Nachbewertung der Chunk-Kandidaten | [Repository](https://github.com/Tiiiger/bert_score) |
| NumPy | Vektoren und Cosinus-Vergleich | [Repository](https://github.com/numpy/numpy) |
| keyring | Anmeldeinformationsspeicher des Betriebssystems | [Repository](https://github.com/jaraco/keyring) |

**PyMuPDF und MuPDF stehen unter AGPL oder kommerziellen Lizenzbedingungen.** Diese Bedingungen sind bei Verwendung und Weitergabe der Gesamtanwendung zu beachten. Die Veröffentlichung des eigenen Quellcodes unter MIT ist keine Zusage, dass das gesamte Abhängigkeitspaket ausschließlich MIT ist. Dieses Repository liefert keine Kopie dieser Pakete mit.

Die tatsächlich installierten Paketversionen hängen von `backend/requirements.txt` ab. Für eine fertige Distribution müssen deren Lizenzdateien und gegebenenfalls die transitiven Abhängigkeiten berücksichtigt werden.

## Modelle

Die integrierten Profile referenzieren Modelle der jeweiligen Herausgeber auf Hugging Face. Der voreingestellte Encoder ist `intfloat/multilingual-e5-small`; für BERTScore wird standardmäßig `bert-base-multilingual-cased` verwendet. Die vollständige Profilliste steht in [Funktionen](docs/FEATURES.md).

Hugging-Face-Modellkarten enthalten die jeweiligen Lizenzen und Nutzungsvoraussetzungen. Auch bei eigenen Modellkennungen gelten diese Bedingungen. Zitatlotse übernimmt keine Modellgewichte ins Repository und re-lizenziert sie nicht.

## Marken und Anbieter

Zotero, Hugging Face, OpenAI, Anthropic, DeepSeek und Ollama werden zur Beschreibung der Integration genannt. Zitatlotse wird von diesen Projekten nicht als offizielles Produkt angeboten. Cloud-APIs unterliegen den Bedingungen und Preisen des gewählten Anbieters.
