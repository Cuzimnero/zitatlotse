"""Bounded, in-memory retrieval caches. No private text is persisted here.

Callers hold Engine.lock. Database changes invalidate the matrix; query vectors
are keyed by model/configuration and cannot cross an embedding-model change.
Large libraries fall back to streaming instead of allocating an unbounded matrix.
"""
from collections import OrderedDict
import json
import numpy as np

from embedding_models import encode_texts


class RetrievalCache:
    def __init__(self, max_bytes=64 * 1024 * 1024, max_queries=128):
        self.max_bytes, self.max_queries = max_bytes, max_queries
        self.queries = OrderedDict()
        self.matrices = OrderedDict()
        self.bytes = 0
        self.stamp = None
        self.query_hits = self.matrix_hits = 0

    def invalidate(self):
        self.matrices.clear()
        self.bytes = 0
        self.stamp = None

    def query_vectors(self, engine, texts):
        texts = list(dict.fromkeys(texts))
        prefix = (engine.model_name, json.dumps(engine.embedding_config, sort_keys=True))
        vectors, missing = {}, []
        for text in texts:
            key = (*prefix, text)
            if key in self.queries:
                self.query_hits += 1
                vectors[text] = self.queries[key]
                self.queries.move_to_end(key)
            else:
                missing.append(text)
        if missing:
            encoded = encode_texts(engine.embedder, engine.model_name, missing, "query", engine.embedding_config)
            if len(encoded) != len(missing):
                raise ValueError("Ungültige Suchvektoren")
            for text, value in zip(missing, encoded):
                vector = np.asarray(list(value), dtype=np.float32)
                norm = np.linalg.norm(vector)
                if vector.ndim != 1 or not np.all(np.isfinite(vector)) or norm <= 0:
                    raise ValueError("Ungültige Suchvektoren")
                vector = vector / norm
                vector.flags.writeable = False
                vectors[text] = vector
                self.queries[(*prefix, text)] = vector
                while len(self.queries) > self.max_queries:
                    self.queries.popitem(last=False)
        return vectors

    def batches(self, engine, db, library_id, allowed):
        # The WAL stamp also detects another connection's committed changes.
        # total_changes detects uncommitted backfills in this connection.
        stamp = []
        for path in (engine.db_path, engine.db_path.with_name(engine.db_path.name + "-wal")):
            try:
                stat = path.stat()
                stamp.append((stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                stamp.append(None)
        stamp = (tuple(stamp), db.total_changes, engine.model_name,
                 json.dumps(engine.embedding_config, sort_keys=True))
        if stamp != self.stamp:
            self.invalidate()
            self.stamp = stamp
        if library_id in self.matrices:
            self.matrix_hits += 1
            batches, _ = self.matrices[library_id]
            self.matrices.move_to_end(library_id)
        else:
            # Include a conservative allowance for Python row/text overhead.
            estimate = db.execute("SELECT COALESCE(SUM(COALESCE(length(embedding_blob),length(embedding)*2) "
                                  "+length(CAST(text AS BLOB))*4+768),0) FROM chunks WHERE library_id=?",
                                  (library_id,)).fetchone()[0]
            def read():
                cursor = db.execute("SELECT id,attachment_key,page,text,embedding_blob,embedding "
                                    "FROM chunks WHERE library_id=? ORDER BY id", (library_id,))
                while rows := cursor.fetchmany(1024):
                    by_dimension = {}
                    for row in rows:
                        try:
                            vector = (np.frombuffer(row["embedding_blob"], dtype="<f4") if row["embedding_blob"]
                                      else np.asarray(json.loads(row["embedding"]), dtype=np.float32))
                            norm = np.linalg.norm(vector)
                            if vector.ndim != 1 or not np.all(np.isfinite(vector)) or norm <= 0:
                                continue
                        except (ValueError, TypeError):
                            continue
                        entry = {key: row[key] for key in ("id", "attachment_key", "page", "text")}
                        by_dimension.setdefault(vector.size, []).append((entry, vector / norm))
                    for group in by_dimension.values():
                        matrix = np.stack([vector for _, vector in group])
                        matrix.flags.writeable = False
                        yield [entry for entry, _ in group], matrix
            if estimate <= self.max_bytes:
                batches = list(read())
                while self.matrices and self.bytes + estimate > self.max_bytes:
                    _, (_, size) = self.matrices.popitem(last=False)
                    self.bytes -= size
                self.matrices[library_id] = (batches, estimate)
                self.bytes += estimate
            else:
                batches = read()
        for rows, matrix in batches:
            indices = [i for i, row in enumerate(rows) if row["attachment_key"] in allowed]
            if len(indices) == len(rows):
                yield rows, matrix
            elif indices:
                yield [rows[i] for i in indices], matrix[indices]
