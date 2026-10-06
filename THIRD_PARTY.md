# Abhängigkeiten und Modelle

Die MIT-Lizenz dieses Repositorys gilt für den eigenen Quellcode und die eigenen Dokumentationsgrafiken. Sie ersetzt keine Lizenz einer Abhängigkeit, eines Modells oder eines Dokuments. Die Windows-Release-XPI enthält Python und die benötigten CPU-Bibliotheken samt deren Lizenzdateien. Modellgewichte sind nicht enthalten und werden separat geladen.

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

**PyMuPDF und MuPDF stehen unter AGPL oder kommerziellen Lizenzbedingungen.** Die freie Distribution verwendet die AGPL-Ausgaben. Deren Lizenztexte liegen in der enthaltenen Laufzeit; der entsprechende unveränderte Quellcode wird zusätzlich als Release-Asset bereitgestellt. Die MIT-Freigabe des eigenen Codes schränkt die Rechte und Pflichten aus der AGPL nicht ein. Die komplette Distribution ist deshalb kein ausschließlich unter MIT stehendes Paket.

Die exakten Versionen des mitgelieferten Pakets stehen in `PACKAGES.json` innerhalb von `runtime/python.zip`. Die Lizenztexte und Copyright-Hinweise der transitiven Abhängigkeiten bleiben in `Lib/site-packages/*dist-info/licenses` beziehungsweise den jeweiligen `LICENSE`-Dateien erhalten. Der Quellcode-Build referenziert `backend/requirements.txt`; neue Laufzeit-Builds separat prüfen.

## Modelle

Die integrierten Profile referenzieren Modelle der jeweiligen Herausgeber auf Hugging Face. Der voreingestellte Encoder ist `intfloat/multilingual-e5-small`; für BERTScore wird standardmäßig `bert-base-multilingual-cased` verwendet. Die vollständige Profilliste steht in [Funktionen](docs/FEATURES.md).

Hugging-Face-Modellkarten enthalten die jeweiligen Lizenzen und Nutzungsvoraussetzungen. Auch bei eigenen Modellkennungen gelten diese Bedingungen. Zitatlotse übernimmt keine Modellgewichte ins Repository und re-lizenziert sie nicht.

## Marken und Anbieter

Zotero, Hugging Face, OpenAI, Anthropic, DeepSeek und Ollama werden zur Beschreibung der Integration genannt. Zitatlotse wird von diesen Projekten nicht als offizielles Produkt angeboten. Cloud-APIs unterliegen den Bedingungen und Preisen des gewählten Anbieters.
