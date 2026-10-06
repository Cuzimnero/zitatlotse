"""Local PDF index and quote retrieval. No Zotero database access."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections import Counter
from difflib import SequenceMatcher
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from embedding_models import encode_texts, load_model
from search_scope import scope_fields, scope_matches


EMBED_MODEL = os.environ.get("ZQS_EMBED_MODEL", "intfloat/multilingual-e5-small")
BERT_MODEL = os.environ.get("ZQS_BERT_MODEL", "bert-base-multilingual-cased")
DB_PATH = Path(os.environ.get("ZQS_DB", Path(__file__).parent / "data" / "quotes.sqlite"))
RERANK_BATCH = 64
SEARCH_SESSION_SECONDS = 900
MIN_RELEVANCE = 0.69
LEXICAL_RELEVANCE = 0.665
FLAG_PREFILTER_MIN_DOCS = 20
FLAG_PREFILTER_FRACTION = 0.85
FLAG_PREFILTER_MAX_GAP = 0.25
COSINE_MAX_GAP = 0.06
EVIDENCE_COSINE_MAX_GAP = 0.15
EVIDENCE_BERT_MIN = 0.60
# Direct semantic retrieval must respect each embedding family's score range.
# Qwen's relevant local test passages scored below the old mixed .69 gate.
DIRECT_MODEL_THRESHOLDS = {"Qwen/Qwen3-Embedding-0.6B": {"cosine":0.50, "bert":0.60}}

TOPIC_STOPWORDS = set("""
    der die das des dem den ein eine einer eines und oder aber mit von für auf aus bei über
    unter nach vor durch ohne als auch ist sind war waren wird werden wurde wurden nicht
    diese dieser dieses diesem sowie ihre ihren sein seine im am zum zur zu in es wir sie
    the and for with from into that this these those are was were been have has had
    not but its their our using use used results result study studies paper article
    introduction conclusion discussion figure table et al of on in to by as at is it
    a an be or de la le les des du un une et en dans pour sur aux que qui los las el
    del y con una uno por para los le di da il la gli delle dei che per nel nella
""".split())


def topic_terms(text: str) -> list[str]:
    """Content words for local topic flags and conservative lexical matching."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [word for word in re.findall(r"[^\W\d_]{3,}", normalized, re.UNICODE)
            if word not in TOPIC_STOPWORDS]


def lexical_keys(text: str) -> set[str]:
    """Match PDF ligatures and simple inflections such as overfit/overfitting."""
    return {word[:5] if len(word) >= 6 else word for word in topic_terms(text)}


def short_search_term(query: str) -> str:
    """A short standalone term needs literal, case-insensitive retrieval."""
    match = re.fullmatch(r"\W*([^\W\d_]{3,5})\W*", query.strip(), re.UNICODE)
    return match.group(1).casefold() if match and topic_terms(match.group(1)) else ""


def direct_literal_pattern(query: str):
    """Exact words/short phrases, with Unicode and whitespace normalization."""
    text = unicodedata.normalize("NFKC", query).strip().strip('"“”„\'')
    words = text.split()
    if not 1 <= len(words) <= 6 or len(text) > 120 or any(
            not re.fullmatch(r"[^\W_]+(?:[-'][^\W_]+)*", word) for word in words):
        return None
    if len(words) == 1 and len(words[0]) < 2:
        return None
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(word) for word in words) + r"(?!\w)", re.IGNORECASE)


def literal_contains(pattern, text: str) -> bool:
    return bool(pattern and pattern.search(unicodedata.normalize("NFKC", text)))


def canonical_acronym_query(db, library_id: int, query: str, attachment_keys=None) -> str:
    """Use the corpus's uppercase acronym for either query spelling."""
    term = short_search_term(query)
    if not term:
        return query
    uppercase = term.upper()
    pattern = re.compile(r"(?<!\w)" + re.escape(uppercase) + r"(?!\w)")
    rows = db.execute("SELECT text,attachment_key FROM chunks WHERE library_id=? AND text GLOB ?",
                      (library_id, "*" + uppercase + "*"))
    allowed = set(attachment_keys) if attachment_keys is not None else None
    return uppercase if any(pattern.search(row[0]) for row in rows
                            if allowed is None or row[1] in allowed) else query


def topic_flags(title: str, passages: list[str], limit: int = 16) -> list[str]:
    """Extract readable terms and repeated phrases without a remote model."""
    counts = Counter()
    phrases = Counter()
    title_words = topic_terms(title)
    counts.update({word: 5 for word in title_words})
    for passage in passages:
        words = topic_terms(passage)
        counts.update(words)
        phrases.update(a + " " + b for a, b in zip(words, words[1:]) if a != b)
    singles = [word for word, _ in counts.most_common(limit)]
    repeated = [phrase for phrase, count in phrases.most_common(5) if count >= 2]
    return (repeated[:4] + singles)[:limit]


def topic_vector(vectors) -> list[float]:
    """Normalized centroid of existing chunk embeddings."""
    vectors = [list(map(float, vector)) for vector in vectors]
    if not vectors:
        return []
    sums = [sum(column) for column in zip(*vectors)]
    norm = math.sqrt(sum(value * value for value in sums))
    return [round(value / norm, 7) for value in sums] if norm else []


def sentences(text: str) -> list[str]:
    """Normalize PDF whitespace and split at likely sentence boundaries."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=\S)", text) if s.strip()]


def chunks(text: str, target_words: int = 100, overlap_words: int = 20) -> list[str]:
    """Page-local chunks with a 20-word overlap; prefer sentence boundaries."""
    if target_words <= overlap_words or overlap_words < 0:
        raise ValueError("Ungültige Chunk-Größe")
    units = []
    for sentence in sentences(text):
        words = sentence.split()
        if len(words) <= target_words:
            units.append(sentence)
        else:
            # A single long sentence must still fit the model's token limit.
            step = target_words - overlap_words
            units.extend(" ".join(words[i:i + target_words]) for i in range(0, len(words), step))
    result = []
    current = []
    word_count = 0
    for sentence in units:
        count = len(sentence.split())
        if current and word_count + count > target_words:
            result.append(" ".join(current))
            available_overlap = min(overlap_words, target_words - count)
            trailing = " ".join(current).split()[-available_overlap:] if available_overlap else []
            current = [" ".join(trailing)] if trailing else []
            word_count = len(trailing)
        current.append(sentence)
        word_count += count
    if current:
        result.append(" ".join(current))
    return [chunk for chunk in result if len(chunk) >= 25]


def same_quote(a: str, b: str) -> bool:
    """Treat small overlap-related variants of a quote as one passage."""
    a = re.sub(r"\W+", " ", a.casefold()).strip()
    b = re.sub(r"\W+", " ", b.casefold()).strip()
    return (a == b or (min(len(a), len(b)) >= 20 and (a in b or b in a))
            or SequenceMatcher(None, a, b).ratio() >= 0.88)


def quote_position(page, quote: str) -> dict:
    """Find the quote in PDF text and return Zotero Reader PDF coordinates."""
    import pymupdf
    position = {"pageIndex": page.number}
    canonical = lambda value: re.sub(r"\W+", "", unicodedata.normalize("NFKC", value).casefold())
    target = canonical(quote)
    words = page.get_text("words", sort=False)
    text, spans, offset = [], [], 0
    for word in words:
        normalized = canonical(word[4])
        if normalized:
            text.append(normalized)
            spans.append((offset, offset + len(normalized), word))
            offset += len(normalized)
    match = "".join(text).find(target) if target else -1
    found = []
    if match >= 0:
        # Match the whole passage, including ligatures and line-end hyphenation.
        lines = {}
        for begin, end, word in spans:
            if begin < match + len(target) and end > match:
                key = tuple(word[5:7])
                rect = pymupdf.Rect(*word[:4])
                if key in lines:
                    lines[key] |= rect
                else:
                    lines[key] = rect
        found = list(lines.values())
    if not found:
        found = page.search_for(quote)
    if found:
        inverse = ~page.transformation_matrix
        position["rects"] = []
        for rect in found:
            pdf_rect = pymupdf.Rect(rect) * inverse
            position["rects"].append([round(pdf_rect.x0, 2), round(pdf_rect.y0, 2),
                                      round(pdf_rect.x1, 2), round(pdf_rect.y1, 2)])
    return position


def normalize_language(value: str) -> str:
    """Normalize Zotero's free-text language field to a short code."""
    value = str(value or "").strip().casefold().replace("_", "-")
    names = {"deutsch": "de", "german": "de", "englisch": "en", "english": "en",
             "français": "fr", "french": "fr", "französisch": "fr",
             "español": "es", "spanish": "es", "spanisch": "es",
             "italiano": "it", "italian": "it", "italienisch": "it"}
    if value in names:
        return names[value]
    match = re.match(r"^([a-z]{2})(?:-[a-z0-9]+)*$", value)
    return match.group(1) if match else ""


def detect_language(text: str) -> str:
    """Conservative text fallback when Zotero has no language metadata."""
    words = re.findall(r"[a-zäöüßéèàáíóúñ]+", text[:6000].casefold())
    markers = {
        "de": {"der", "die", "das", "und", "ist", "mit", "von", "für", "den", "eine", "nicht"},
        "en": {"the", "and", "of", "in", "for", "with", "this", "that", "are", "from", "not"},
        "fr": {"le", "la", "les", "des", "et", "pour", "avec", "dans", "une", "est", "pas"},
        "es": {"el", "la", "los", "las", "de", "y", "para", "con", "una", "en", "que"},
    }
    scores = {code: sum(word in stopwords for word in words) for code, stopwords in markers.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 and scores[best] > sorted(scores.values())[-2] else "und"


class Engine:
    def __init__(self, db_path: Path = DB_PATH, embedder=None, scorer=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._embedder = embedder
        self._scorer = scorer
        self._search_sessions: dict[str, dict] = {}
        self.rebuilding = False
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                  library_id INTEGER NOT NULL, item_key TEXT NOT NULL,
                  attachment_key TEXT NOT NULL, collection_ids TEXT NOT NULL,
                  title TEXT NOT NULL, creators TEXT NOT NULL, year TEXT NOT NULL,
                  zotero_uri TEXT NOT NULL, pdf_path TEXT NOT NULL,
                  language TEXT NOT NULL DEFAULT '',
                  topic_flags TEXT NOT NULL DEFAULT '[]',
                  topic_embedding TEXT NOT NULL DEFAULT '[]',
                  file_mtime REAL NOT NULL, file_size INTEGER NOT NULL,
                  PRIMARY KEY (library_id, attachment_key)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  library_id INTEGER NOT NULL, attachment_key TEXT NOT NULL,
                  page INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                  text TEXT NOT NULL, embedding TEXT NOT NULL,
                  embedding_blob BLOB,
                  FOREIGN KEY (library_id, attachment_key)
                    REFERENCES documents(library_id, attachment_key) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_doc
                  ON chunks(library_id, attachment_key);
                CREATE TABLE IF NOT EXISTS saved_quotes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  library_id INTEGER NOT NULL, item_key TEXT NOT NULL,
                  attachment_key TEXT NOT NULL, page INTEGER NOT NULL,
                  quote TEXT NOT NULL, title TEXT NOT NULL, creators TEXT NOT NULL,
                  year TEXT NOT NULL, zotero_uri TEXT NOT NULL,
                  position TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(library_id, attachment_key, page, quote)
                );
                CREATE INDEX IF NOT EXISTS idx_saved_quotes_library
                  ON saved_quotes(library_id, created_at);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
            if "language" not in columns:
                db.execute("ALTER TABLE documents ADD COLUMN language TEXT NOT NULL DEFAULT ''")
            if "topic_flags" not in columns:
                db.execute("ALTER TABLE documents ADD COLUMN topic_flags TEXT NOT NULL DEFAULT '[]'")
            if "topic_embedding" not in columns:
                db.execute("ALTER TABLE documents ADD COLUMN topic_embedding TEXT NOT NULL DEFAULT '[]'")
            if "content_fingerprint" not in columns:
                db.execute("ALTER TABLE documents ADD COLUMN content_fingerprint TEXT NOT NULL DEFAULT ''")
            chunk_columns = {row[1] for row in db.execute("PRAGMA table_info(chunks)")}
            if "embedding_blob" not in chunk_columns:
                db.execute("ALTER TABLE chunks ADD COLUMN embedding_blob BLOB")
            db.execute("INSERT OR IGNORE INTO index_metadata VALUES ('embedding_model',?)", (EMBED_MODEL,))
            self.model_name = db.execute("SELECT value FROM index_metadata WHERE key='embedding_model'").fetchone()[0]
            config = db.execute("SELECT value FROM index_metadata WHERE key='embedding_config'").fetchone()
            self.embedding_config = json.loads(config[0]) if config else None

    def _refresh_topic(self, db, library_id: int, attachment_key: str, title: str) -> None:
        """Backfill an existing PDF's flags and centroid from its stored chunks."""
        rows = db.execute("SELECT text,embedding,embedding_blob FROM chunks WHERE library_id=? AND attachment_key=?",
                          (library_id, attachment_key)).fetchall()
        flags = topic_flags(title, [row["text"] for row in rows])
        centroid = topic_vector(np.frombuffer(row["embedding_blob"], dtype="<f4")
                                if row["embedding_blob"] else json.loads(row["embedding"])
                                for row in rows)
        db.execute("UPDATE documents SET topic_flags=?,topic_embedding=? "
                   "WHERE library_id=? AND attachment_key=?",
                   (json.dumps(flags, ensure_ascii=False), json.dumps(centroid),
                    library_id, attachment_key))

    def _backfill_topics(self, db, library_id: int) -> None:
        missing = db.execute("SELECT attachment_key,title FROM documents "
                             "WHERE library_id=? AND (topic_flags='[]' OR topic_embedding='[]') "
                             "AND EXISTS (SELECT 1 FROM chunks WHERE chunks.library_id=documents.library_id "
                             "AND chunks.attachment_key=documents.attachment_key)",
                             (library_id,)).fetchall()
        for row in missing:
            self._refresh_topic(db, library_id, row["attachment_key"], row["title"])

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = load_model(self.model_name, self.embedding_config) if self.embedding_config else load_model(self.model_name)
        return self._embedder

    @property
    def scorer(self):
        if self._scorer is None:
            from bert_score import BERTScorer
            self._scorer = BERTScorer(model_type=BERT_MODEL, num_layers=9, batch_size=8)
        return self._scorer

    def index_pdf(self, data: dict) -> dict:
        import pymupdf
        library_id = int(data["library_id"])
        attachment_key = str(data["attachment_key"])
        path = Path(data["pdf_path"])
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise ValueError("PDF-Datei nicht gefunden")
        stat = path.stat()
        collection_ids = sorted({int(x) for x in data.get("collection_ids", [])})
        language = normalize_language(data.get("language", ""))
        title = str(data.get("title", ""))
        with self.lock, self._connect() as db:
            if self.rebuilding:
                raise ValueError("Embedding-Modell wird neu berechnet. PDF-Verarbeitung danach erneut starten.")
            previous = db.execute("SELECT file_mtime,file_size,language,title,topic_flags,topic_embedding "
                                  "FROM documents WHERE library_id=? AND attachment_key=?",
                                  (library_id, attachment_key)).fetchone()
            prior_chunks = db.execute("SELECT COUNT(*) FROM chunks WHERE library_id=? AND attachment_key=?",
                                      (library_id, attachment_key)).fetchone()[0]
            if previous and prior_chunks and previous["file_mtime"] == stat.st_mtime and previous["file_size"] == stat.st_size:
                if not language and previous["language"] in {"", "und"}:
                    with pymupdf.open(path) as pdf:
                        first_page = next(iter(pdf), None)
                        language = detect_language(first_page.get_text("text")) if first_page else "und"
                language = language or previous["language"]
                db.execute("UPDATE documents SET collection_ids=?, title=?, creators=?, year=?, zotero_uri=?, language=? WHERE library_id=? AND attachment_key=?",
                           (json.dumps(collection_ids), title, str(data.get("creators", "")),
                            str(data.get("year", "")), str(data.get("zotero_uri", "")), language,
                            library_id, attachment_key))
                if (previous["topic_flags"] == "[]" or previous["topic_embedding"] == "[]"
                        or previous["title"] != title):
                    self._refresh_topic(db, library_id, attachment_key, title)
                return {"status": "unchanged", "chunks": 0}
            page_chunks = []
            sample = ""
            with pymupdf.open(path) as pdf:
                for page_number, page in enumerate(pdf, start=1):
                    page_text = page.get_text("text")
                    if len(sample) < 6000:
                        sample += " " + page_text[:6000 - len(sample)]
                    for ordinal, chunk in enumerate(chunks(page_text)):
                        page_chunks.append((page_number, ordinal, chunk))
            language = language or detect_language(sample)
            vectors = []
            if page_chunks:
                vectors = encode_texts(self.embedder, self.model_name, [row[2] for row in page_chunks], "passage", self.embedding_config)
            flags = topic_flags(title, [row[2] for row in page_chunks])
            centroid = topic_vector(vectors)
            db.execute("DELETE FROM chunks WHERE library_id=? AND attachment_key=?", (library_id, attachment_key))
            db.execute("""INSERT INTO documents
                (library_id,item_key,attachment_key,collection_ids,title,creators,year,zotero_uri,pdf_path,
                 language,topic_flags,topic_embedding,file_mtime,file_size)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(library_id,attachment_key) DO UPDATE SET
                item_key=excluded.item_key,collection_ids=excluded.collection_ids,
                title=excluded.title,creators=excluded.creators,year=excluded.year,
                zotero_uri=excluded.zotero_uri,pdf_path=excluded.pdf_path,language=excluded.language,
                topic_flags=excluded.topic_flags,topic_embedding=excluded.topic_embedding,
                file_mtime=excluded.file_mtime,file_size=excluded.file_size,content_fingerprint=''""",
                (library_id, str(data["item_key"]), attachment_key, json.dumps(collection_ids),
                 title, str(data.get("creators", "")), str(data.get("year", "")),
                 str(data.get("zotero_uri", "")), str(path), language,
                 json.dumps(flags, ensure_ascii=False), json.dumps(centroid), stat.st_mtime, stat.st_size))
            db.executemany("""INSERT INTO chunks
                (library_id,attachment_key,page,ordinal,text,embedding,embedding_blob)
                VALUES (?,?,?,?,?,?,?)""",
                [(library_id, attachment_key, page, ordinal, chunk,
                  json.dumps([float(x) for x in vector]),
                  np.asarray(list(vector), dtype="<f4").tobytes())
                 for (page, ordinal, chunk), vector in zip(page_chunks, vectors)])
            self._search_sessions = {token: session for token, session in self._search_sessions.items()
                                     if session["library_id"] != library_id}
            return {"status": "indexed", "chunks": len(page_chunks)}

    def _backfill_vector_blobs(self, db, library_id: int) -> None:
        # Existing installations already have JSON vectors. Convert in bounded batches.
        last_id = 0
        while True:
            rows = db.execute("SELECT id,embedding FROM chunks WHERE library_id=? "
                              "AND embedding_blob IS NULL AND id>? ORDER BY id LIMIT 1000",
                              (library_id, last_id)).fetchall()
            if not rows:
                return
            updates = [(np.asarray(json.loads(row["embedding"]), dtype="<f4").tobytes(), row["id"])
                       for row in rows]
            db.executemany("UPDATE chunks SET embedding_blob=? WHERE id=?", updates)
            last_id = rows[-1]["id"]

    def _vector_rank(self, db, library_id: int, query: str, queries: dict,
                     evidence_mode: bool = False, attachment_keys=None, ai_mode: bool = False) -> list[tuple]:
        """Very broad document filter, then cosine on every remaining chunk."""
        self._backfill_topics(db, library_id)
        self._backfill_vector_blobs(db, library_id)
        docs = db.execute("SELECT attachment_key,language,topic_flags,topic_embedding "
                          "FROM documents WHERE library_id=?", (library_id,)).fetchall()
        if attachment_keys is not None:
            allowed = set(attachment_keys)
            docs = [doc for doc in docs if doc["attachment_key"] in allowed]
        if not docs:
            return []
        target_queries = lambda language: list(dict.fromkeys(filter(None, (
            queries.get(language or "und") or queries.get("default") or query, query))))
        query_vectors = {text: np.asarray(list(encode_texts(self.embedder, self.model_name,
            [text], "query", self.embedding_config)[0]), dtype=np.float32)
            for text in {text for doc in docs for text in target_queries(doc["language"])}}
        document_info = {}
        document_scores = []
        for doc in docs:
            vector = np.asarray(json.loads(doc["topic_embedding"]), dtype=np.float32)
            flags = {word for flag in json.loads(doc["topic_flags"]) for word in topic_terms(flag)}
            variants = []
            best_document_score = -1.0
            has_flag_match = False
            for priority, current_query in enumerate(target_queries(doc["language"])):
                query_vector = query_vectors[current_query]
                similarity = float(vector @ query_vector) if vector.size == query_vector.size else 0.0
                overlap = len(set(topic_terms(current_query)) & flags)
                has_flag_match |= overlap > 0
                variants.append((current_query, priority))
                best_document_score = max(best_document_score, similarity)
            document_info[doc["attachment_key"]] = variants
            document_scores.append((best_document_score, has_flag_match, doc["attachment_key"]))
        literal_term = short_search_term(query)
        literal_pattern = (re.compile(r"(?<!\w)" + re.escape(literal_term) + r"(?!\w)", re.IGNORECASE)
                           if literal_term else None) if evidence_mode else direct_literal_pattern(query)
        if literal_pattern or len(docs) <= FLAG_PREFILTER_MIN_DOCS:
            # Exact words/phrases can occur without reaching a PDF's top-16 flags.
            selected = set(document_info)
        else:
            keep = min(len(docs), max(FLAG_PREFILTER_MIN_DOCS,
                                      math.ceil(len(docs) * FLAG_PREFILTER_FRACTION)))
            ordered = sorted(document_scores, key=lambda item: (-item[0], item[2]))
            selected = {key for _, _, key in ordered[:keep]}
            selected.update(key for _, matched, key in ordered if matched)
            best_score = ordered[0][0]
            selected.update(key for score, _, key in ordered
                            if score >= best_score - FLAG_PREFILTER_MAX_GAP)
        ranked = []
        selected_keys = sorted(selected & document_info.keys())
        for start in range(0, len(selected_keys), 400):
            keys = selected_keys[start:start + 400]
            placeholders = ",".join("?" for _ in keys)
            columns = "id,attachment_key,embedding_blob" + (",text" if literal_pattern else "")
            cursor = db.execute("SELECT " + columns + " FROM chunks WHERE library_id=? "
                                "AND attachment_key IN (" + placeholders + ")",
                                (library_id, *keys))
            while batch := cursor.fetchmany(1024):
                groups = {}
                for row in batch:
                    variants = document_info.get(row["attachment_key"])
                    if not variants or not row["embedding_blob"]:
                        continue
                    vector = np.frombuffer(row["embedding_blob"], dtype="<f4")
                    literal = literal_contains(literal_pattern, row["text"]) if literal_pattern else False
                    for current_query, priority in variants:
                        if vector.size == query_vectors[current_query].size:
                            groups.setdefault(current_query, []).append(
                                (row["id"], vector, priority, literal))
                best = {}
                for current_query, entries in groups.items():
                    matrix = np.stack([entry[1] for entry in entries])
                    scores = matrix @ query_vectors[current_query]
                    for score, (item_id, _, priority, literal) in zip(scores, entries):
                        candidate = (float(score), item_id, current_query, literal)
                        if evidence_mode:
                            ranked.append(candidate)
                            continue
                        previous = best.get(item_id)
                        if (previous is None or candidate[0] > previous[0][0] + 0.005
                                or (abs(candidate[0] - previous[0][0]) <= 0.005
                                    and priority < previous[1])):
                            best[item_id] = (candidate, priority)
                ranked.extend(candidate for candidate, _ in best.values())
        if not ranked:
            return []
        if evidence_mode:
            # Translated/aspect queries must not be suppressed by a higher score
            # distribution from the original claim. Qualify each query separately,
            # then pick each chunk's best relative match for BERTScore.
            maxima = {}
            for score, _, current_query, _ in ranked:
                maxima[current_query] = max(maxima.get(current_query, -1), score)
            best = {}
            for entry in ranked:
                gap = maxima[entry[2]] - entry[0]
                if gap > EVIDENCE_COSINE_MAX_GAP:
                    continue
                # Retain the embedding model's absolute relevance floor even
                # when AI reviews the broader relative candidate window.
                profile = DIRECT_MODEL_THRESHOLDS.get(self.model_name) if ai_mode else None
                if profile and entry[0] < profile["cosine"]:
                    continue
                previous = best.get(entry[1])
                if previous is None or gap < previous[0] - .005:
                    best[entry[1]] = (gap, entry)
            ranked = [entry for _, entry in best.values()]
        else:
            cutoff = max(score for score, _, _, _ in ranked) - COSINE_MAX_GAP
            profile = DIRECT_MODEL_THRESHOLDS.get(self.model_name)
            if profile:
                cutoff = max(cutoff, profile["cosine"])
            # Exact occurrences qualify even if a one-word query has low cosine.
            ranked = [entry for entry in ranked if entry[3] or entry[0] >= cutoff]
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        return ranked

    def _fill_search_session(self, db, session: dict) -> None:
        """Rerank every cosine candidate in bounded BERTScore batches."""
        while session["cursor"] < len(session["ranked"]):
            if session["cursor"] >= len(session["ranked"]):
                break
            window = session["ranked"][session["cursor"]:session["cursor"] + RERANK_BATCH]
            session["cursor"] += len(window)
            ids = [entry[1] for entry in window]
            placeholders = ",".join("?" for _ in ids)
            rows = db.execute("SELECT p.id,p.page,p.text,p.attachment_key,d.library_id,d.item_key,"
                              "d.title,d.creators,d.year,d.zotero_uri,d.language,d.pdf_path "
                              "FROM chunks p JOIN documents d ON p.library_id=d.library_id "
                              "AND p.attachment_key=d.attachment_key "
                              "WHERE p.library_id=? AND p.id IN (" + placeholders + ")",
                              (session["library_id"], *ids)).fetchall()
            by_id = {row["id"]: row for row in rows}
            groups = {}
            for cosine, item_id, current_query, _literal in window:
                if item_id in by_id:
                    groups.setdefault(current_query, []).append((cosine, by_id[item_id]))
            scored = []
            for current_query, entries in groups.items():
                candidates = [row["text"] for _, row in entries]
                _, _, f1 = self.scorer.score(candidates, [current_query] * len(entries), batch_size=8)
                for (cosine, row), bert in zip(entries, f1.tolist()):
                    scored.append((0.65 * float(bert) + 0.35 * cosine, float(bert),
                                   row, current_query, cosine))
            scored.sort(key=lambda entry: (-entry[0], entry[2]["id"]))
            if session["term_frequency"] is None:
                session["term_frequency"] = Counter(key for _, _, row, _, _ in scored
                                                    for key in lexical_keys(row["text"]))
                session["term_sample_size"] = len(scored)
            term_frequency = session["term_frequency"]
            term_weight = lambda key: 1.0 + math.log(
                (session["term_sample_size"] + 1) / (term_frequency[key] + 1))
            for score, bert, row, current_query, cosine in scored:
                def record_quote(part: str, literal: bool = False) -> bool:
                    fingerprint = re.sub(r"\W+", " ", part.casefold()).strip()
                    if literal:
                        location = (row["attachment_key"], row["page"], fingerprint)
                        if location in session["seen_locations"]:
                            return False
                        session["seen_locations"].add(location)
                    elif (fingerprint in session["seen"] or
                          any(same_quote(part, previous) for previous in session["recent"][-100:])):
                        return False
                    session["seen"].add(fingerprint)
                    session["recent"].append(part)
                    session["hits"].append({"id": row["id"], "page": row["page"], "quote": part,
                                            "attachment_key": row["attachment_key"],
                                            "library_id": row["library_id"], "item_key": row["item_key"],
                                            "language": row["language"] or "und", "query_used": current_query,
                                            "title": row["title"], "creators": row["creators"],
                                            "year": row["year"], "zotero_uri": row["zotero_uri"],
                                            "score": round(score, 4), "bert_score": round(bert, 4),
                                            "context": row["text"],
                                            "_pdf_path": row["pdf_path"],
                                            "match_type": "literal" if literal else "semantic"})
                    return True

                literal_pattern = session["literal_pattern"]
                if literal_pattern:
                    literal_options = [part for part in sentences(row["text"])
                                       if literal_contains(literal_pattern, part)]
                    for part in literal_options:
                        record_quote(part, literal=True)
                    if literal_options or session["literal_only"]:
                        continue
                options = [part for part in sentences(row["text"]) if len(part) >= 25]
                if not options:
                    options = [row["text"]]
                query_words = lexical_keys(current_query)
                option_weight = lambda part: sum(term_weight(key)
                                                 for key in query_words & lexical_keys(part))
                options.sort(key=lambda part: (option_weight(part),
                                               -abs(len(part) - 180)), reverse=True)
                best_overlap = len(query_words & lexical_keys(options[0])) if query_words else 0
                best_weight = option_weight(options[0])
                active_words = query_words & term_frequency.keys()
                if not session.get("evidence_mode") and 2 <= len(active_words) <= 4:
                    # A passage can cover the query across several sentences.
                    covered = active_words & lexical_keys(row["text"])
                    coverage = sum(term_weight(key) for key in covered) / sum(term_weight(key) for key in active_words)
                    if coverage < 0.55:
                        continue
                lexical_evidence = (best_overlap >= max(1, math.ceil(len(query_words) * 0.6))
                                    and bert >= 0.58)
                if session.get("evidence_mode"):
                    # This is candidate retrieval, not a verdict on the whole
                    # claim. Raw cosine ranges vary by embedding family; the old
                    # fixed mixed-score gate discarded relevant Qwen passages.
                    if bert < EVIDENCE_BERT_MIN and not (bert >= .58 and lexical_evidence):
                        continue
                else:
                    profile = DIRECT_MODEL_THRESHOLDS.get(self.model_name)
                    if profile:
                        if cosine < profile["cosine"] - 1e-6 or bert < profile["bert"]:
                            continue
                    elif score < MIN_RELEVANCE and not (score >= LEXICAL_RELEVANCE and lexical_evidence):
                        continue
                quote = None
                for part in options:
                    if part != options[0] and (not best_overlap or
                            option_weight(part) < best_weight - 0.05):
                        break
                    if record_quote(part):
                        quote = part
                        break
                if quote is None:
                    continue
        session["hits"].sort(key=lambda hit: (-hit["score"], hit["id"], hit["quote"]))

    def search_page(self, data: dict) -> dict:
        import pymupdf
        library_id = int(data["library_id"])
        limit = min(max(int(data.get("limit", 20)), 1), 30)
        scope = scope_fields(data) if not data.get("search_id") else {}
        offset = int(data.get("offset", 0))
        if offset < 0:
            raise ValueError("Ungültige Trefferposition")
        with self.lock, self._connect() as db:
            now = time.monotonic()
            self._search_sessions = {token: item for token, item in self._search_sessions.items()
                                     if now - item["touched"] < SEARCH_SESSION_SECONDS}
            token = str(data.get("search_id", ""))
            if token:
                session = self._search_sessions.get(token)
                if not session or session["library_id"] != library_id or not scope_matches(session, data):
                    raise ValueError("Suche abgelaufen. Bitte erneut suchen.")
            else:
                query = str(data.get("query", "")).strip()
                if not query:
                    raise ValueError("Suchfrage fehlt")
                raw_queries = data.get("queries") if isinstance(data.get("queries"), dict) else {}
                queries = {normalize_language(code) or str(code): str(text).strip()[:500]
                           for code, text in raw_queries.items() if str(text).strip()}
                query = canonical_acronym_query(db, library_id, query, scope.get("attachment_keys"))
                queries = {code: canonical_acronym_query(db, library_id, text, scope.get("attachment_keys"))
                           for code, text in queries.items()}
                # AI reviews relevance after retrieval. Its candidate stage must
                # retain secondary results (e.g. numeric ablations) for review.
                evidence_mode = data.get("retrieval_mode") in {"evidence", "ai"}
                ranked = self._vector_rank(db, library_id, query, queries, evidence_mode=evidence_mode,
                                           attachment_keys=scope.get("attachment_keys"),
                                           ai_mode=data.get("retrieval_mode") == "ai")
                db.commit()  # Release the one-time migration write lock before reranking.
                token = uuid.uuid4().hex
                literal_term = short_search_term(query)
                pattern = (re.compile(r"(?<!\w)" + re.escape(literal_term) + r"(?!\w)", re.IGNORECASE)
                           if literal_term else None) if evidence_mode else direct_literal_pattern(query)
                has_literal = bool(pattern and any(entry[3] for entry in ranked))
                allowed = set(scope["attachment_keys"]) if "attachment_keys" in scope else None
                session = {"library_id": library_id, **scope, "ranked": ranked, "cursor": 0,
                           "hits": [], "seen": set(), "seen_locations": set(), "recent": [],
                           "touched": now, "term_frequency": None, "term_sample_size": 0,
                           "query": query, "queries": queries,
                           "evidence_mode": evidence_mode,
                           "literal_pattern": pattern if has_literal else None,
                           "literal_only": has_literal and (evidence_mode or len(query.split()) == 1),
                           "total_chunks": sum(row["count"] for row in db.execute(
                               "SELECT attachment_key,COUNT(*) AS count FROM chunks WHERE library_id=? GROUP BY attachment_key",
                               (library_id,)) if allowed is None or row["attachment_key"] in allowed)}
                self._search_sessions[token] = session
                if len(self._search_sessions) > 4:
                    oldest = min(self._search_sessions, key=lambda key: self._search_sessions[key]["touched"])
                    del self._search_sessions[oldest]
            if offset > len(session["hits"]):
                raise ValueError("Ungültige Trefferposition. Bitte erneut suchen.")
            session["touched"] = now
            self._fill_search_session(db, session)
            page_hits = session["hits"][offset:offset + limit]
            for hit in page_hits:
                if "position" not in hit:
                    try:
                        with pymupdf.open(hit["_pdf_path"]) as pdf:
                            hit["position"] = quote_position(pdf[hit["page"] - 1], hit["quote"])
                    except Exception:
                        hit["position"] = {"pageIndex": hit["page"] - 1}
            next_offset = offset + len(page_hits)
            return {"results": [{key: value for key, value in hit.items() if key != "_pdf_path"}
                                for hit in page_hits],
                    "search_id": token, "next_offset": next_offset,
                    "has_more": next_offset < len(session["hits"]),
                    "total_results": len(session["hits"]),
                    "scored_chunks": session["cursor"], "total_chunks": session["total_chunks"]}

    def search(self, data: dict) -> list[dict]:
        """Compatibility helper for callers that only need the first page."""
        return self.search_page(data)["results"]

    def locate_quote(self, data: dict) -> dict:
        import pymupdf
        # This read-only lookup uses no models or mutable search sessions.
        # It must not queue behind a full embedding/BERTScore search.
        with self._connect() as db:
            doc = db.execute("SELECT pdf_path FROM documents WHERE library_id=? AND attachment_key=?",
                             (int(data["library_id"]), str(data["attachment_key"]))).fetchone()
            if not doc:
                raise ValueError("PDF ist in dieser Bibliothek nicht verarbeitet")
            indexed_path = doc["pdf_path"]
        current_path = Path(data["pdf_path"]) if data.get("pdf_path") else None
        path = current_path if current_path and current_path.is_file() and current_path.suffix.lower() == ".pdf" else Path(indexed_path)
        with pymupdf.open(path) as pdf:
            page_index = int(data["page"]) - 1
            if not 0 <= page_index < len(pdf):
                raise ValueError("PDF-Seite ist ungültig")
            return {"position": quote_position(pdf[page_index], str(data["quote"])[:20000])}

    def save_quote(self, data: dict) -> dict:
        library_id = int(data["library_id"])
        attachment_key = str(data["attachment_key"])
        page = int(data["page"])
        quote = str(data["quote"]).strip()
        if page < 1 or not quote or len(quote) > 5000:
            raise ValueError("Ungültige Fundstelle")
        position = data.get("position", {"pageIndex": page - 1})
        if not isinstance(position, dict) or position.get("pageIndex") != page - 1:
            position = {"pageIndex": page - 1}
        with self.lock, self._connect() as db:
            doc = db.execute("SELECT * FROM documents WHERE library_id=? AND attachment_key=?",
                             (library_id, attachment_key)).fetchone()
            if not doc:
                raise ValueError("Dokument in dieser Bibliothek nicht gefunden")
            passages = db.execute("SELECT text FROM chunks WHERE library_id=? AND attachment_key=? AND page=?",
                                  (library_id, attachment_key, page)).fetchall()
            if not any(quote in row["text"] for row in passages):
                raise ValueError("Zitat nicht in der indizierten PDF-Seite gefunden")
            db.execute("""INSERT INTO saved_quotes
                (library_id,item_key,attachment_key,page,quote,title,creators,year,zotero_uri,position)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(library_id,attachment_key,page,quote)
                DO UPDATE SET position=excluded.position""",
                (library_id, doc["item_key"], attachment_key, page, quote,
                 doc["title"], doc["creators"], doc["year"], doc["zotero_uri"],
                 json.dumps(position)))
            row = db.execute("SELECT * FROM saved_quotes WHERE library_id=? AND attachment_key=? "
                             "AND page=? AND quote=?", (library_id, attachment_key, page, quote)).fetchone()
            return self._saved_row(row)

    @staticmethod
    def _saved_row(row) -> dict:
        result = dict(row)
        result["position"] = json.loads(result["position"])
        return result

    def saved_quotes(self, library_id: int, query: str = "") -> list[dict]:
        with self.lock, self._connect() as db:
            rows = db.execute("SELECT * FROM saved_quotes WHERE library_id=? ORDER BY created_at DESC,id DESC",
                              (int(library_id),)).fetchall()
        result = [self._saved_row(row) for row in rows]
        words = [word.casefold() for word in str(query).split()]
        return [row for row in result if all(word in (row["quote"] + " " + row["title"] + " " +
                    row["note"] + " " + row["creators"]).casefold() for word in words)]

    def update_saved_note(self, library_id: int, quote_id: int, note: str) -> dict:
        with self.lock, self._connect() as db:
            cursor = db.execute("UPDATE saved_quotes SET note=? WHERE library_id=? AND id=?",
                                (str(note)[:10000], int(library_id), int(quote_id)))
            if not cursor.rowcount:
                raise ValueError("Gespeichertes Zitat nicht gefunden")
            return self._saved_row(db.execute("SELECT * FROM saved_quotes WHERE id=?",
                                             (int(quote_id),)).fetchone())

    def delete_saved_quote(self, library_id: int, quote_id: int) -> dict:
        with self.lock, self._connect() as db:
            cursor = db.execute("DELETE FROM saved_quotes WHERE library_id=? AND id=?",
                                (int(library_id), int(quote_id)))
            if not cursor.rowcount:
                raise ValueError("Gespeichertes Zitat nicht gefunden")
        return {"ok": True}

    def stats(self, library_id: int) -> dict:
        """Number of indexed PDFs and searchable chunks in one library."""
        with self.lock, self._connect() as db:
            self._backfill_topics(db, library_id)
            documents = db.execute(
                "SELECT COUNT(*) FROM documents WHERE library_id=?", (library_id,)
            ).fetchone()[0]
            chunks_count = db.execute(
                "SELECT COUNT(*) FROM chunks WHERE library_id=?", (library_id,)
            ).fetchone()[0]
            topic_documents = db.execute(
                "SELECT COUNT(*) FROM documents WHERE library_id=? AND topic_embedding!='[]'",
                (library_id,)
            ).fetchone()[0]
        return {"library_id": library_id, "documents": documents, "chunks": chunks_count,
                "topic_documents": topic_documents}

    def languages(self, library_id: int, attachment_keys=None) -> dict[str, int]:
        import pymupdf
        with self.lock, self._connect() as db:
            missing = db.execute("SELECT attachment_key,pdf_path FROM documents "
                                 "WHERE library_id=? AND language=''", (library_id,)).fetchall()
            allowed = set(attachment_keys) if attachment_keys is not None else None
            if allowed is not None:
                missing = [row for row in missing if row["attachment_key"] in allowed]
            for row in missing:
                language = "und"
                try:
                    with pymupdf.open(row["pdf_path"]) as pdf:
                        first_page = next(iter(pdf), None)
                        if first_page:
                            language = detect_language(first_page.get_text("text"))
                except Exception:
                    pass
                db.execute("UPDATE documents SET language=? WHERE library_id=? AND attachment_key=?",
                           (language, library_id, row["attachment_key"]))
            rows = db.execute("SELECT attachment_key,language FROM documents WHERE library_id=?", (library_id,)).fetchall()
        return dict(Counter((row["language"] or "und") for row in rows
                            if allowed is None or row["attachment_key"] in allowed))
