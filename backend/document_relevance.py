"""Local query/document overview: each PDF's highest chunk cosine, before filters."""
from __future__ import annotations

import json
import hashlib
import math
import re

import numpy as np

from embedding_models import encode_texts, model_compatibility
from search_scope import scope_fields


TIERS = ("lowest", "low", "medium", "high", "highest", "same", "unindexed")


def backfill_fingerprints(db, library_id, documents):
    """Hash complete indexed text once; names and titles alone are not identities.

    Reindexing resets the document's cached fingerprint when replacing its chunks.
    Embedding rebuilds keep the text and therefore keep this fingerprint.
    No PDF file is opened and nothing leaves the local database.
    """
    missing = sorted(key for key, doc in documents.items() if doc["item_key"] and not doc["content_fingerprint"])
    for start in range(0, len(missing), 400):
        keys = missing[start:start + 400]
        digests = {}
        cursor = db.execute("SELECT attachment_key,page,ordinal,text FROM chunks WHERE library_id=? "
                            "AND attachment_key IN (" + ",".join("?" for _ in keys) + ") "
                            "ORDER BY attachment_key,page,ordinal,id", (library_id, *keys))
        while rows := cursor.fetchmany(1024):
            for row in rows:
                digest = digests.setdefault(row["attachment_key"], hashlib.sha256())
                value = [row["page"], row["ordinal"], " ".join(row["text"].split())]
                digest.update(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        for key, digest in digests.items():
            fingerprint = digest.hexdigest()
            documents[key]["content_fingerprint"] = fingerprint
            db.execute("UPDATE documents SET content_fingerprint=? WHERE library_id=? AND attachment_key=?",
                       (fingerprint, library_id, key))


def unique_documents(documents):
    """Each content-equivalent PDF group contributes its highest score once."""
    groups = {}
    for doc in documents:
        identity = (doc["library_id"], doc["content_fingerprint"] or doc["attachment_key"])
        groups.setdefault(identity, []).append(doc)
    unique = []
    for copies in groups.values():
        copies.sort(key=lambda doc: (doc["similarity"] is None,
                                     -(doc["similarity"] if doc["similarity"] is not None else -1), doc["attachment_key"]))
        representative = dict(copies[0])
        representative.pop("content_fingerprint", None)
        representative["attachment_keys"] = sorted(doc["attachment_key"] for doc in copies)
        representative["duplicate_count"] = len(copies) - 1
        unique.append(representative)
    return unique


def summarize_documents(documents):
    unique = unique_documents(documents)
    return {**classify_documents(unique), "total_attachments": len(documents),
            "duplicate_attachments": len(documents) - len(unique)}


def classify_documents(documents):
    """Equal-width bands of the observed score spectrum; ties stay together."""
    scores = [doc["similarity"] for doc in documents if doc["similarity"] is not None]
    minimum, maximum = (min(scores), max(scores)) if scores else (None, None)
    uniform = bool(scores) and maximum - minimum < 1e-6
    bands = {tier: 0 for tier in TIERS}
    for doc in documents:
        score = doc["similarity"]
        if score is None:
            category = "unindexed"
        elif uniform:
            category = "same"
        else:
            index = min(4, max(0, math.floor((score - minimum) / (maximum - minimum) * 5)))
            category = TIERS[index]
        doc["category"] = category
        bands[category] += 1
    documents.sort(key=lambda doc: (doc["similarity"] is None,
                                    -(doc["similarity"] if doc["similarity"] is not None else -1),
                                    doc["attachment_key"]))
    total = len(documents)
    return {"documents": documents, "total_documents": total, "scored_documents": len(scores),
            "minimum": minimum, "maximum": maximum, "uniform": uniform,
            "categories": [{"id": tier, "count": count,
                            "percentage": round(100 * count / total, 2) if total else 0}
                           for tier, count in bands.items()]}


def document_relevance(engine, data):
    library_id = int(data["library_id"])
    query = str(data.get("query", "")).strip()
    if not query or len(query) > 5000:
        raise ValueError("Suchfrage fehlt oder ist zu lang")
    scope = scope_fields(data)
    allowed = set(scope["attachment_keys"]) if "attachment_keys" in scope else None
    additional = data.get("search_queries", [])
    if (not isinstance(additional, list) or len(additional) > 20 or
            any(not isinstance(text, str) or len(text) > 1000 for text in additional)):
        raise ValueError("Ungültige Suchvarianten")
    language_queries = data.get("language_queries", {})
    if (not isinstance(language_queries, dict) or len(language_queries) > 20 or
            any(not isinstance(lang, str) or not re.fullmatch(r"[a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]{2,8})*", lang) or
                lang.lower() in {"all", "default"} or not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000
                for lang, text in language_queries.items())):
        raise ValueError("Ungültige sprachbezogene Suchformulierungen")
    language_queries = {lang.replace("_", "-").lower().split("-")[0]: text.strip() for lang,text in language_queries.items()}
    fallback_queries = list(dict.fromkeys([query] + [text.strip() for text in additional if text.strip()]))
    queries = list(dict.fromkeys(fallback_queries + list(language_queries.values())))
    with engine.lock, engine._connect() as db:
        rows = db.execute("SELECT attachment_key,item_key,title,language,content_fingerprint FROM documents WHERE library_id=?",
                          (library_id,)).fetchall()
        documents = {row["attachment_key"]: {"library_id": library_id, **dict(row),
                       "similarity": None, "chunk_id": None, "page": None, "matched_query": ""}
                     for row in rows if allowed is None or row["attachment_key"] in allowed}
        if allowed is not None:
            for key in allowed - documents.keys():
                documents[key] = {"library_id": library_id, "attachment_key": key, "item_key": "",
                                  "title": key, "similarity": None, "chunk_id": None,
                                  "page": None, "matched_query": "", "language": "", "content_fingerprint": ""}
        model = engine.model_name
        compatibility = model_compatibility(model, engine.embedding_config)
        context = {"model": model, "query": query, "model_compatibility": compatibility,
                   "aggregation": "maximum_chunk_cosine", "classification": "relative_equal_width",
                   "queries": queries, "language_queries": language_queries,
                   "query_language_policy": "document_language_with_original_fallback",
                   "collection_id": scope.get("collection_id", 0)}
        if not documents or not any(doc["item_key"] for doc in documents.values()):
            return {**summarize_documents(list(documents.values())), **context}
        backfill_fingerprints(db, library_id, documents)
        if compatibility["status"] == "incompatible":
            # Do not present a sentiment classifier's language bias as relevance.
            return {**summarize_documents(list(documents.values())), **context}
        encoded = np.asarray(encode_texts(engine.embedder, model, queries, "query", engine.embedding_config), dtype=np.float32)
        if encoded.ndim != 2 or len(encoded) != len(queries) or not np.all(np.isfinite(encoded)):
            raise ValueError("Ungültige Suchvektoren")
        norms = np.linalg.norm(encoded, axis=1)
        if np.any(norms <= 0):
            raise ValueError("Ungültige Suchvektoren")
        query_vectors = encoded / norms[:, None]
        fallback_indices = [queries.index(text) for text in fallback_queries]
        document_query_indices = {}
        for key, doc in documents.items():
            language = (doc["language"] or "").replace("_", "-").lower().split("-")[0]
            translated = language_queries.get(language)
            document_query_indices[key] = [queries.index(translated)] if translated else fallback_indices
        # No flag filter, cosine cutoff, BERTScore or result-page limit here.
        # The overview must include every indexed PDF in the selected scope.
        keys = sorted(documents)
        for start in range(0, len(keys), 400):
            subset = keys[start:start + 400]
            cursor = db.execute(
                "SELECT id,attachment_key,page,embedding_blob,embedding FROM chunks "
                "WHERE library_id=? AND attachment_key IN (" + ",".join("?" for _ in subset) + ") ORDER BY id",
                (library_id, *subset))
            while batch := cursor.fetchmany(1024):
                usable, vectors = [], []
                for row in batch:
                    try:
                        vector = (np.frombuffer(row["embedding_blob"], dtype="<f4")
                                  if row["embedding_blob"] else np.asarray(json.loads(row["embedding"]), dtype=np.float32))
                    except (ValueError, TypeError):
                        continue
                    if vector.ndim != 1 or vector.size != query_vectors.shape[1] or not np.all(np.isfinite(vector)):
                        continue
                    norm = np.linalg.norm(vector)
                    if norm <= 0:
                        continue
                    usable.append(row)
                    vectors.append(vector / norm)
                if not usable:
                    continue
                cosine = np.clip(np.stack(vectors) @ query_vectors.T, -1, 1)
                for i, row in enumerate(usable):
                    # A high score for an unrelated language's query must not win.
                    strongest_query = max(document_query_indices[row["attachment_key"]], key=lambda j: cosine[i,j])
                    score = float(cosine[i, strongest_query])
                    doc = documents[row["attachment_key"]]
                    if doc["similarity"] is None or score > doc["similarity"]:
                        doc.update(similarity=score, chunk_id=row["id"], page=row["page"],
                                   matched_query=queries[strongest_query])
        result = summarize_documents(list(documents.values()))
        for doc in result["documents"]:
            if doc["similarity"] is not None:
                doc["similarity"] = round(doc["similarity"], 6)
        return {**result, **context}
