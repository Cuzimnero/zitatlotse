# Dependencies and models

The MIT license in this repository applies to original project code and documentation graphics. It does not replace the license of a dependency, model or document. The Windows release XPI includes Python and the required CPU libraries with their license files. Model weights are not included and are downloaded separately.

## Libraries

| Project | Use | Official source |
| --- | --- | --- |
| Zotero | Libraries, metadata, reader, CSL styles and add-on interface | [Zotero](https://www.zotero.org/support/dev/start) |
| PyMuPDF / MuPDF | PDF text, pages and coordinates | [License and copyright](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) |
| SentenceTransformers | Local dense text embeddings | [Repository](https://github.com/huggingface/sentence-transformers) |
| Transformers | Model architectures and tokenizers | [Repository](https://github.com/huggingface/transformers) |
| BERTScore | Reranking chunk candidates | [Repository](https://github.com/Tiiiger/bert_score) |
| NumPy | Vectors and cosine comparison | [Repository](https://github.com/numpy/numpy) |
| keyring | Operating system credential storage | [Repository](https://github.com/jaraco/keyring) |

**PyMuPDF and MuPDF are available under AGPL or commercial license terms.** The free distribution uses AGPL builds. Their license texts are in the bundled runtime; the corresponding unmodified source is also provided as a release asset. The MIT license for original project code does not remove AGPL rights or obligations. The complete distribution is therefore not exclusively MIT licensed.

Exact versions of bundled packages are listed in `PACKAGES.json` inside `runtime/python.zip`. License texts and copyright notices for transitive dependencies remain in `Lib/site-packages/*dist-info/licenses` or the relevant `LICENSE` files. The source build references `backend/requirements.txt`; review future runtime builds separately.

## Models

Built-in profiles refer to models hosted by their respective publishers on Hugging Face. The default encoder is `intfloat/multilingual-e5-small`; the default BERTScore model is `bert-base-multilingual-cased`. See the [feature catalog](docs/FEATURES.md) for the complete profile list.

Hugging Face model cards describe each model's license and terms of use. Those terms also apply to custom model IDs. Zitatlotse does not include model weights in the repository or relicense them.

## Trademarks and providers

Zotero, Hugging Face, OpenAI, Anthropic, DeepSeek and Ollama are named to describe integrations. These projects do not offer Zitatlotse as an official product. Cloud APIs are subject to the selected provider's terms and prices.
