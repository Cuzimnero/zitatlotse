"""Curated local models and an atomic rebuild of all stored chunk vectors."""
from __future__ import annotations

import json
import hashlib
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np


MODELS = [
    {"id": "intfloat/multilingual-e5-small", "label": "Multilingual E5 Small",
     "dimensions": 384, "input_format": "e5", "batch_size": 32,
     "de": "100 Sprachen, einschließlich Deutsch und Englisch. Kompakter Standard für mehrsprachige Textstellensuche.",
     "en": "100 languages, including German and English. Compact default for multilingual passage retrieval."},
    {"id": "intfloat/multilingual-e5-base", "label": "Multilingual E5 Base",
     "dimensions": 768, "input_format": "e5", "batch_size": 16,
     "de": "Mehrsprachige Textstellensuche mit größerem Modell. Benötigt mehr Arbeitsspeicher und Rechenzeit; Qualität hängt von den Dokumenten ab.",
     "en": "Multilingual passage retrieval with a larger model. Requires more memory and computation; quality depends on your documents."},
    {"id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "label": "Multilingual MiniLM",
     "dimensions": 384, "input_format": "plain", "batch_size": 32,
     "de": "50 Sprachen, einschließlich Deutsch und Englisch. Kompakt, für Satzähnlichkeit und sprachübergreifende Formulierungen trainiert.",
     "en": "50 languages, including German and English. Compact model trained for sentence similarity across languages."},
    {"id": "sentence-transformers/all-MiniLM-L6-v2", "label": "English MiniLM L6",
     "dimensions": 384, "input_format": "plain", "batch_size": 32,
     "de": "Kleines englisches Modell mit geringem Rechenbedarf. Für überwiegend englische Dokumente und englische Suchanfragen.",
     "en": "Small English model with low computational requirements. For predominantly English documents and English queries."},
    {"id": "mixedbread-ai/deepset-mxbai-embed-de-large-v1", "label": "Mixedbread / deepset German-English",
     "dimensions": 1024, "input_format": "e5", "batch_size": 8,
     "de": "Für Deutsch und Englisch auf Textstellensuche spezialisiert; mit über 30 Millionen deutschen Textpaaren nachtrainiert. Großer Speicher- und Rechenbedarf, langsamer auf CPU. Ein sinnvoller Vergleichskandidat für deutschsprachige Fachliteratur.",
     "en": "Specialized German/English passage retrieval, fine-tuned on over 30 million German text pairs. High memory and compute requirements, slower on CPU. A useful comparison candidate for German academic literature."},
    {"id": "BAAI/bge-m3", "label": "BGE M3 Multilingual",
     "dimensions": 1024, "input_format": "plain", "batch_size": 8,
     "de": "Über 100 Sprachen und sprachübergreifende Suche. Geeignet als Vergleichskandidat für gemischte Bibliotheken; großer Speicher- und Rechenbedarf. Zitatlotse verwendet die dichten Vektoren dieses Modells.",
     "en": "Over 100 languages and cross-language retrieval. A comparison candidate for mixed-language libraries; high memory and compute requirements. Zitatlotse uses this model's dense vectors."},
    {"id": "Qwen/Qwen3-Embedding-0.6B", "label": "Qwen3 Embedding 0.6B",
     "dimensions": 1024, "input_format": "qwen", "batch_size": 4,
     "de": "Über 100 Sprachen; berücksichtigt eine Aufgabenbeschreibung bei der Suche. 600 Millionen Parameter: hoher Speicherbedarf, auf CPU deutlich langsamer als MiniLM. Für Vergleiche bei anspruchsvollen mehrsprachigen Fragen.",
     "en": "Over 100 languages; uses a task instruction for retrieval. 600 million parameters: high memory requirements, substantially slower than MiniLM on CPU. A comparison option for complex multilingual questions."},
    {"id": "BAAI/bge-small-en-v1.5", "label": "BGE Small English v1.5",
     "dimensions": 384, "input_format": "bge", "batch_size": 32,
     "de": "Kompaktes Modell für englische Textstellensuche. Geringer Rechenbedarf und kleine Vektoren. Für englische Paper; deutsche Fragen sollten von der KI ins Englische übertragen werden.",
     "en": "Compact model for English passage retrieval. Low computational requirements and small vectors. For English papers; AI should translate queries from other languages into English."},
    {"id": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1", "label": "Multi-QA MiniLM English",
     "dimensions": 384, "input_format": "plain", "batch_size": 32,
     "de": "Kompakt und für englische Frage-Antwort-Suche trainiert, mit 215 Millionen Textpaaren. Für kurze Fragen und Absätze bei geringem Rechenbedarf. Kein mehrsprachiges Modell.",
     "en": "Compact model trained for English question-answer retrieval on 215 million text pairs. For short questions and paragraphs with low computational requirements. Not a multilingual model."},
]
for _model in MODELS:
    _model["url"] = "https://huggingface.co/" + _model["id"]
MODEL_BY_ID = {model["id"]: model for model in MODELS}

# Publisher model cards specify different asymmetric retrieval inputs. These
# formats apply consistently to initial indexing, rebuilding and searching.
QWEN_INSTRUCTION = "Given a search query, retrieve relevant passages from research papers that answer the query"


def custom_config(data: dict) -> dict:
    """Accept Hub repositories, never filesystem paths or arbitrary download URLs."""
    name = str(data.get("id", "")).strip().rstrip("/")
    if name.startswith("https://huggingface.co/"):
        parsed = urlsplit(name)
        if parsed.query or parsed.fragment or parsed.netloc != "huggingface.co":
            raise ValueError("Bitte die Hugging-Face-Modellseite ohne Zusatzparameter angeben")
        name = parsed.path.lstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", name) or ".." in name or len(name) > 180:
        raise ValueError("Hugging-Face-Modell als Organisation/Modellname angeben")
    style = str(data.get("input_format", "auto"))
    if style not in {"auto", "plain", "e5", "bge", "qwen", "custom"}:
        raise ValueError("Unbekanntes Eingabeprofil")
    revision = str(data.get("revision", "")).strip()
    if revision and (len(revision) > 100 or ".." in revision or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", revision)):
        raise ValueError("Ungültige Modellversion")
    try:
        batch = int(data.get("batch_size", 8))
    except (TypeError, ValueError):
        raise ValueError("Batchgröße muss zwischen 1 und 64 liegen") from None
    if not 1 <= batch <= 64:
        raise ValueError("Batchgröße muss zwischen 1 und 64 liegen")
    prefixes = {key: str(data.get(key, "")) for key in ("query_prefix", "passage_prefix")}
    if any(len(value) > 1000 for value in prefixes.values()):
        raise ValueError("Präfixe dürfen höchstens 1000 Zeichen enthalten")
    return {"id": name, "input_format": style, "revision": revision, "batch_size": batch, **prefixes}


def model_signature(name, config=None):
    return name + ":" + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def input_text(model: str, text: str, kind: str, config=None) -> str:
    if kind not in {"query", "passage"}:
        raise ValueError("Unknown embedding input kind")
    settings = config if config is not None else MODEL_BY_ID.get(model, {})
    style = settings.get("input_format", "plain")
    if style == "custom":
        return settings.get("query_prefix" if kind == "query" else "passage_prefix", "") + text
    if style == "e5":
        return kind + ": " + text
    if style == "bge" and kind == "query":
        return "Represent this sentence for searching relevant passages: " + text
    if style == "qwen" and kind == "query":
        return "Instruct: " + QWEN_INSTRUCTION + "\nQuery:" + text
    return text


def encode_texts(embedder, name: str, texts: list[str], kind: str, config=None):
    # Explicit empty prompt avoids adding a repository's default prompt twice.
    # Larger encoders use smaller inference batches to reduce peak RAM/VRAM.
    if kind not in {"query", "passage"}:
        raise ValueError("Unknown embedding input kind")
    settings = config if config is not None else MODEL_BY_ID.get(name, {})
    if settings.get("input_format") == "auto":
        method = getattr(embedder, "encode_query" if kind == "query" else "encode_document", None)
        if not callable(method):
            raise ValueError("Automatisches Profil benötigt SentenceTransformers mit encode_query/encode_document")
        return method(texts, normalize_embeddings=True, batch_size=settings.get("batch_size", 8))
    return embedder.encode([input_text(name, text, kind, config) for text in texts],
                           normalize_embeddings=True, prompt="",
                           batch_size=settings.get("batch_size", 32))


def compatibility_from_metadata(metadata, modules):
    """Finite pooled vectors alone do not make a classifier a retrieval model."""
    architectures = metadata.get("architectures", []) if isinstance(metadata, dict) else []
    heads = ("ForSequenceClassification", "ForTokenClassification", "ForQuestionAnswering")
    if any(any(head in architecture for head in heads) for architecture in architectures if isinstance(architecture, str)):
        return {"status": "incompatible", "reason": "task_head",
                "de": "Dieses Modell ist für Klassifikation oder Fragebeantwortung trainiert, nicht für die Ähnlichkeitssuche. Bitte ein Text-Embedding-Modell wählen und den Index neu berechnen.",
                "en": "This model is trained for classification or question answering, not similarity retrieval. Choose a text embedding model and rebuild the index."}
    if isinstance(modules, list) and modules:
        return {"status": "supported", "reason": "sentence_transformer"}
    return {"status": "unverified", "reason": "automatic_pooling",
            "de": "Kein gespeichertes SentenceTransformers-Embedding-Profil erkannt. Automatisch erzeugte Textvektoren garantieren keine Suchqualität; bitte Trainingsziel und Sprachen in der Modellbeschreibung prüfen.",
            "en": "No saved SentenceTransformers embedding profile detected. Automatically pooled text vectors do not guarantee retrieval quality; check the training objective and languages in the model card."}


def model_compatibility(name: str, config=None, *, download=False):
    """Read cached public metadata; only a confirmed model load may download it."""
    if name in MODEL_BY_ID:
        return {"status": "supported", "reason": "catalog"}
    from huggingface_hub import try_to_load_from_cache, hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError
    revision = (config or {}).get("revision") or "main"
    files = {}
    for filename in ("config.json", "modules.json"):
        path = try_to_load_from_cache(name, filename, revision=revision)
        if not isinstance(path, str) and download:
            try:
                path = hf_hub_download(name, filename, revision=revision)
            except EntryNotFoundError:
                path = None
        if isinstance(path, str):
            try:
                files[filename] = json.loads(Path(path).read_text(encoding="utf-8"))
            except (ValueError, OSError):
                if download:
                    raise ValueError("Ungültige Modellmetadaten: " + filename) from None
    return compatibility_from_metadata(files.get("config.json", {}), files.get("modules.json"))


def load_model(name: str, config=None):
    suitability = model_compatibility(name, config, download=True)
    if suitability["status"] == "incompatible":
        raise ValueError(name + ": " + suitability["de"])
    from sentence_transformers import SentenceTransformer
    options = {"trust_remote_code": False}
    if config and config.get("revision"):
        options["revision"] = config["revision"]
    try:
        return SentenceTransformer(name, local_files_only=True, **options)
    except (OSError, ValueError):
        return SentenceTransformer(name, local_files_only=False, **options)


class EmbeddingManager:
    def __init__(self, engine, factory=load_model):
        self.engine = engine
        self.factory = factory
        self.guard = threading.RLock()
        self.job = {"state": "idle", "completed": 0, "total": 0, "model": engine.model_name}
        # A crash during staging never changed the active embeddings. Discard staging.
        with engine._connect() as db:
            db.execute("DROP TABLE IF EXISTS embedding_rebuild")
            db.execute("CREATE TABLE IF NOT EXISTS custom_embedding_models (id TEXT PRIMARY KEY, config TEXT NOT NULL)")

    def status(self):
        with self.guard:
            with self.engine._connect() as db:
                custom = [json.loads(row[0]) for row in db.execute("SELECT config FROM custom_embedding_models ORDER BY id")]
            entries = [{**config, "custom": True, "label": config["id"], "url": "https://huggingface.co/" + config["id"],
                        "compatibility": model_compatibility(config["id"], config),
                        "de": "Eigenes Hugging-Face-Modell · Eingabeprofil: " + config["input_format"],
                        "en": "Custom Hugging Face model · input profile: " + config["input_format"]} for config in custom]
            return {"models": MODELS + entries, "active_model": self.engine.model_name,
                    "active_compatibility": model_compatibility(self.engine.model_name, self.engine.embedding_config),
                    "active_signature": model_signature(self.engine.model_name, self.engine.embedding_config), "job": dict(self.job)}

    def start(self, data: dict):
        name = str(data.get("model", ""))
        if data.get("confirmed") is not True:
            raise ValueError("Bitte die Neuberechnung der Datenbank bestätigen")
        config = None
        if "custom_model" in data:
            if not isinstance(data["custom_model"], dict):
                raise ValueError("Ungültige Modellkonfiguration")
            config = custom_config(data["custom_model"])
            name = config["id"]
            if name in MODEL_BY_ID:
                raise ValueError("Dieses Modell ist bereits in der Modellliste enthalten. Bitte dort auswählen.")
        elif name not in MODEL_BY_ID:
            with self.engine._connect() as db:
                row = db.execute("SELECT config FROM custom_embedding_models WHERE id=?", (name,)).fetchone()
            if not row:
                raise ValueError("Unbekanntes Embedding-Modell")
            config = custom_config(json.loads(row[0]))
        with self.guard, self.engine.lock:
            if self.engine.rebuilding:
                raise ValueError("Eine Neuberechnung läuft bereits")
            if name == self.engine.model_name and config == self.engine.embedding_config:
                return self.status()
            with self.engine._connect() as db:
                if config:
                    db.execute("INSERT OR REPLACE INTO custom_embedding_models VALUES (?,?)", (name, json.dumps(config)))
                total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            self.engine.rebuilding = True
            self.job = {"state": "loading", "completed": 0, "total": total, "model": name}
            threading.Thread(target=self._rebuild, args=(name, config), daemon=True).start()
            return self.status()

    def _update(self, **changes):
        with self.guard:
            self.job.update(changes)

    def _rebuild(self, name, config=None):
        try:
            embedder = self.factory(name, config) if self.factory is load_model and config else self.factory(name)
            dimensions = None
            if config:
                # Validate both routes even for an empty database. A generative,
                # image-only or incompatible repository must not replace the index.
                probe = [np.asarray(encode_texts(embedder, name, ["Research evidence"], kind, config), dtype="<f4")
                         for kind in ("query", "passage")]
                if any(vector.ndim != 2 or len(vector) != 1 or vector.shape[1] < 1 or
                       not np.isfinite(vector).all() or np.linalg.norm(vector[0]) < 1e-12 for vector in probe) or probe[0].shape != probe[1].shape:
                    raise ValueError("Das Modell muss gleich große, gültige Textvektoren für Fragen und Dokumente liefern")
                dimensions = probe[0].shape[1]
                # Pin the actually downloaded weights when the publisher provides
                # a commit hash, so a restart cannot silently load changed weights.
                modules = getattr(embedder, "_modules", {})
                if isinstance(modules, dict) and modules:
                    transformer = next(iter(modules.values()))
                    commit = getattr(getattr(getattr(transformer, "auto_model", None), "config", None), "_commit_hash", None)
                    if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
                        config = {**config, "revision": commit}
            self._update(state="rebuilding")
            with self.engine._connect() as db:
                db.execute("CREATE TABLE embedding_rebuild (id INTEGER PRIMARY KEY, vector BLOB NOT NULL)")
                db.commit()
                last = completed = 0
                while rows := db.execute("SELECT id,text FROM chunks WHERE id>? ORDER BY id LIMIT 128", (last,)).fetchall():
                    vectors = np.asarray(encode_texts(embedder, name, [row["text"] for row in rows], "passage", config), dtype="<f4")
                    if vectors.ndim != 2 or len(vectors) != len(rows) or not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) < 1e-12):
                        raise ValueError("Das Modell lieferte ungültige Embeddings")
                    dimensions = dimensions or vectors.shape[1]
                    if vectors.shape[1] != dimensions or dimensions < 1:
                        raise ValueError("Embedding-Dimensionen stimmen nicht überein")
                    db.executemany("INSERT INTO embedding_rebuild VALUES (?,?)",
                                   [(row["id"], vector.tobytes()) for row, vector in zip(rows, vectors)])
                    db.commit()
                    last = rows[-1]["id"]
                    completed += len(rows)
                    self._update(completed=completed)
                # Only this transaction changes the active index; all libraries switch together.
                with self.engine.lock:
                    missing = db.execute("SELECT COUNT(*) FROM chunks WHERE id NOT IN (SELECT id FROM embedding_rebuild)").fetchone()[0]
                    if missing or completed != self.job["total"]:
                        raise ValueError("Index wurde während der Neuberechnung verändert")
                    db.execute("UPDATE chunks SET embedding_blob=(SELECT vector FROM embedding_rebuild WHERE embedding_rebuild.id=chunks.id),embedding='[]'")
                    for doc in db.execute("SELECT library_id,attachment_key,title FROM documents").fetchall():
                        self.engine._refresh_topic(db, doc["library_id"], doc["attachment_key"], doc["title"])
                    db.execute("INSERT OR REPLACE INTO index_metadata VALUES ('embedding_model',?)", (name,))
                    db.execute("INSERT OR REPLACE INTO index_metadata VALUES ('embedding_config',?)", (json.dumps(config),))
                    if config:
                        db.execute("INSERT OR REPLACE INTO custom_embedding_models VALUES (?,?)", (name, json.dumps(config)))
                    db.execute("DROP TABLE embedding_rebuild")
                    db.commit()
                    self.engine.model_name = name
                    self.engine.embedding_config = config
                    self.engine._embedder = embedder
                    self.engine._search_sessions.clear()
                    self.engine.rebuilding = False
            self._update(state="complete")
        except Exception as exc:
            with self.engine.lock, self.engine._connect() as db:
                db.execute("DROP TABLE IF EXISTS embedding_rebuild")
                self.engine.rebuilding = False
            message = str(exc)
            if config:
                message = "Hugging-Face-Modell konnte nicht als lokales Text-Embedding geladen werden. Modell-ID, Zugriff, Speicher und Eingabeprofil prüfen. Repositories mit eigenem Python-Code werden nicht ausgeführt. " + message[:600]
            self._update(state="failed", error=message)
