import json
import random
import sqlite3
import struct
import threading
from contextlib import closing
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as real_pymupdf

from engine import Engine, chunks, detect_language, normalize_language, quote_position


class FakeVector:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class FakeEmbedder:
    def encode(self, texts, **kwargs):
        return [FakeVector([1.0, 0.0] if "Klima" in text else [0.0, 1.0]) for text in texts]


class FakeScores:
    def __init__(self, scores):
        self.scores = scores

    def tolist(self):
        return self.scores


class FakeScorer:
    def score(self, candidates, references, **kwargs):
        assert len(candidates) == len(references)
        return None, None, FakeScores([0.9 if "Klima" in x else 0.1 for x in candidates])


class FakePage:
    def get_text(self, mode):
        return "Der Klimawandel beeinflusst die Landwirtschaft erheblich. Weitere Messungen bestätigen diesen Befund."


class FakePDF:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter([FakePage()])


class EngineTest(unittest.TestCase):
    def test_ai_candidates_keep_secondary_numeric_passage_without_changing_direct_search(self):
        class TwoPages(FakePDF):
            def __iter__(self):
                return iter([types.SimpleNamespace(get_text=lambda _:"MiVOLO age estimation face and body features."),
                    types.SimpleNamespace(get_text=lambda _:"MiVOLO body-only inference achieved an MAE of 6.66 on IMDB-clean.")])
        class Vectors:
            def encode(self, texts, **kwargs): return [FakeVector([1.,0.]) for _ in texts]
        class Scores:
            def score(self, candidates, references, **kwargs): return None,None,FakeScores([.6235]*len(candidates))
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=lambda _:TwoPages())}), tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"paper.pdf";path.write_bytes(b"mock")
            engine=Engine(Path(folder)/"index.sqlite",Vectors(),Scores())
            engine.index_pdf({"library_id":7,"attachment_key":"PDF","item_key":"P","title":"MiVOLO","pdf_path":str(path)})
            engine.model_name="Qwen/Qwen3-Embedding-0.6B"
            with engine._connect() as db:
                db.execute("UPDATE chunks SET embedding_blob=? WHERE page=1",(struct.pack("<ff",.67,.74236),))
                db.execute("UPDATE chunks SET embedding_blob=? WHERE page=2",(struct.pack("<ff",.575,.81813),))
            request={"library_id":7,"query":"MiVOLO body-only inference MAE"}
            direct=engine.search_page(request)
            broad=engine.search_page({**request,"retrieval_mode":"ai"})
            self.assertFalse(any("6.66" in h["quote"] for h in direct["results"]))
            self.assertTrue(any("6.66" in h["quote"] for h in broad["results"]))
            self.assertTrue(all(h["bert_score"] >= .60 for h in broad["results"]))

    def test_collection_scope_filters_before_ranking_keeps_pagination_and_empty_scope(self):
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=lambda _:FakePDF())}), tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine = Engine(root / "index.sqlite", FakeEmbedder(), FakeScorer())
            for lib, key, language in ((7,"PDF","en"),(7,"OTHER","de"),(8,"PDF","fr")):
                path = root / (key + ".pdf"); path.write_bytes(b"mock")
                engine.index_pdf({"library_id":lib,"item_key":key,"attachment_key":key,"language":language,
                    "title":"Klima", "pdf_path":str(path)})
            scope = {"library_id":7,"collection_id":10,"attachment_keys":["PDF"],"query":"Klima"}
            self.assertEqual(engine.languages(7, attachment_keys=["PDF"]), {"en":1})
            self.assertEqual(engine.languages(7, attachment_keys=[]), {})
            for mode in ("direct","evidence"):
                page = engine.search_page({**scope,"retrieval_mode":mode,"limit":1})
                self.assertTrue(page["results"])
                self.assertEqual({h["attachment_key"] for h in page["results"]}, {"PDF"})
                self.assertEqual({h["library_id"] for h in page["results"]}, {7})
                with self.assertRaises(ValueError):
                    engine.search_page({"library_id":7,"collection_id":11,"search_id":page["search_id"]})
                engine.search_page({"library_id":7,"collection_id":10,"search_id":page["search_id"]})
            empty = engine.search_page({**scope,"attachment_keys":[]})
            self.assertEqual(empty["results"], [])
            self.assertEqual(empty["total_chunks"], 0)

    def test_average_word_search_keeps_every_pdf_despite_low_cosine_and_bert(self):
        class Pages:
            def __init__(self, path): self.path = str(path)
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def __iter__(self):
                if "noise" in self.path:
                    text = "Averaged predictions improved this unrelated model substantially."
                else:
                    text = " ".join(f"The Average error for configuration {n} was reported separately." for n in range(25))
                yield types.SimpleNamespace(get_text=lambda _:text)
        class Embedder:
            def encode(self, texts, **kwargs): return [FakeVector([1.,0.]) for _ in texts]
        class LowScorer:
            def score(self, candidates, references, **kwargs): return None, None, FakeScores([.1] * len(candidates))
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=Pages)}), tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine = Engine(root / "index.sqlite", Embedder(), LowScorer())
            for lib, key in ((1,"A"),(1,"B"),(1,"noise"),(2,"A")):
                path = root / (key + ".pdf"); path.write_bytes(b"mock")
                engine.index_pdf({"library_id":lib,"item_key":key,"attachment_key":key,"title":key,"pdf_path":str(path)})
            with engine._connect() as db:
                db.execute("UPDATE chunks SET embedding_blob=? WHERE attachment_key <> 'noise'", (struct.pack("<ff", .1,.994987),))
            engine.model_name = "Qwen/Qwen3-Embedding-0.6B"
            for query in ("Average","average","AVERAGE"):
                page = engine.search_page({"library_id":1,"query":query,"limit":20})
                hits = list(page["results"])
                while page["has_more"]:
                    page = engine.search_page({"library_id":1,"search_id":page["search_id"],"offset":page["next_offset"],"limit":20})
                    hits.extend(page["results"])
                self.assertEqual(len(hits),50)
                self.assertEqual({h["attachment_key"] for h in hits},{"A","B"})
                self.assertTrue(all(h["library_id"] == 1 and h["match_type"] == "literal" for h in hits))
            self.assertEqual(engine.search_page({"library_id":3,"query":"Average"})["results"], [])
            self.assertEqual(engine.search_page({"library_id":1,"query":"averag"})["results"], [])

    def test_direct_phrase_and_ligature_matches_are_not_removed_by_semantic_gate(self):
        class LowScorer:
            def score(self, candidates, references, **kwargs): return None, None, FakeScores([.1] * len(candidates))
        text = "Soft targets contain information about similarities between classes. Overﬁtting harms generalization."
        page = types.SimpleNamespace(get_text=lambda _:text)
        class PDF:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def __iter__(self): return iter([page])
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=lambda _:PDF())}), tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / "p.pdf"; path.write_bytes(b"mock")
            engine = Engine(root / "index.sqlite", FakeEmbedder(), LowScorer())
            engine.index_pdf({"library_id":1,"item_key":"P","attachment_key":"P","title":"Study","pdf_path":str(path)})
            for query, expected in (("soft targets","Soft targets"),("SOFT   TARGETS","Soft targets"),("overfitting","Overﬁtting")):
                hits = engine.search_page({"library_id":1,"query":query})["results"]
                self.assertTrue(hits,query)
                self.assertIn(expected,hits[0]["quote"])

    def test_qwen_direct_semantics_accepts_relevant_range_and_rejects_unrelated_range(self):
        text = "The teacher updated with momentum outperforms the student during DINO training."
        class Scorer:
            value = .63
            def score(self, candidates, references, **kwargs): return None,None,FakeScores([self.value] * len(candidates))
        class Embedder:
            def encode(self,texts,**kwargs): return [FakeVector([1.,0.]) for _ in texts]
        page = types.SimpleNamespace(get_text=lambda _:text)
        class PDF:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def __iter__(self): return iter([page])
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=lambda _:PDF())}), tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / "p.pdf"; path.write_bytes(b"mock")
            scorer = Scorer()
            engine = Engine(root / "index.sqlite", Embedder(), scorer)
            engine.index_pdf({"library_id":1,"item_key":"P","attachment_key":"P","title":"Study","pdf_path":str(path)})
            engine.model_name = "Qwen/Qwen3-Embedding-0.6B"
            with engine._connect() as db:
                db.execute("UPDATE chunks SET embedding_blob=?", (struct.pack("<ff", .62,.784602),))
            request = {"library_id":1,"query":"DINO momentum teacher"}
            self.assertTrue(engine.search_page(request)["results"])
            scorer.value = .4
            self.assertEqual(engine.search_page(request)["results"],[])
            scorer.value = .63
            with engine._connect() as db:
                db.execute("UPDATE chunks SET embedding_blob=?", (struct.pack("<ff", .29,.957026),))
            unrelated = engine.search_page(request)
            self.assertEqual(unrelated["results"],[])
            self.assertEqual(unrelated["scored_chunks"],0,"Weak cosine should not incur BERTScore work")

    def test_evidence_candidates_survive_moderate_cosine_but_weak_bert_does_not(self):
        class Scorer:
            value = .63
            def score(self, candidates, references, **kwargs):
                return None, None, FakeScores([self.value] * len(candidates))
        source = "Smaller patches improve representation quality while decreasing inference throughput."
        page = types.SimpleNamespace(get_text=lambda _:source)
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=lambda _:FakePDF())}), \
                tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"mock")
            scorer = Scorer()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), scorer)
            engine.index_pdf({"library_id":1, "item_key":"A", "attachment_key":"PDF",
                              "pdf_path":str(pdf), "title":"DINO", "language":"en"})
            with engine._connect() as db:
                db.execute("UPDATE chunks SET text=?, embedding_blob=?", (source, struct.pack("<ff", .759934, .65)))
            query = {"library_id":1, "query":"small patches representation computational throughput"}
            self.assertEqual(engine.search_page(query)["results"], [])
            candidates = engine.search_page({**query, "retrieval_mode":"evidence"})
            self.assertEqual(len(candidates["results"]), 1)
            self.assertIn("Smaller patches", candidates["results"][0]["quote"])
            scorer.value = .3
            self.assertEqual(engine.search_page({**query, "retrieval_mode":"evidence"})["results"], [])
            self.assertEqual(engine.search_page({**query, "library_id":2, "retrieval_mode":"evidence"})["results"], [])

    def test_evidence_qualifies_each_language_query_against_its_own_score_range(self):
        class Embedder:
            def encode(self, texts, **kwargs):
                return [FakeVector([1.,0.,0.] if "English aspect" in text else [0.,1.,0.]) for text in texts]
        with patch.dict(sys.modules, {"pymupdf":types.SimpleNamespace(open=lambda _:FakePDF())}), \
                tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"mock")
            engine = Engine(root / "index.sqlite", Embedder(), FakeScorer())
            for key, vector in (("EN", (.8,.1,.591608)), ("ORIGINAL", (.1,.96,.261534))):
                engine.index_pdf({"library_id":1, "item_key":key, "attachment_key":key,
                                  "pdf_path":str(pdf), "title":key, "language":"en"})
                with engine._connect() as db:
                    db.execute("UPDATE chunks SET embedding_blob=? WHERE attachment_key=?",
                               (struct.pack("<fff", *vector), key))
            with engine._connect() as db:
                direct = engine._vector_rank(db, 1, "Deutsche lange Behauptung", {"en":"English aspect query"})
                evidence = engine._vector_rank(db, 1, "Deutsche lange Behauptung", {"en":"English aspect query"}, evidence_mode=True)
            self.assertEqual(len(direct), 1, "The original query's .96 suppresses the translated query's .8 in the old gate")
            self.assertEqual(len(evidence), 2)
            self.assertEqual({r[2] for r in evidence}, {"English aspect query", "Deutsche lange Behauptung"})

    def test_quote_highlights_the_entire_multiline_passage_and_normalizes_hyphenation(self):
        with patch.dict(sys.modules, {"pymupdf":real_pymupdf}):
            pdf = real_pymupdf.open()
            page = pdf.new_page()
            lines = ["First line with over-", "fitting and limitations."] + [f"Distinct line number {i}." for i in range(13)]
            for i, line in enumerate(lines): page.insert_text((72, 90 + i * 18), line)
            page.insert_text((350, 90), "Unrelated other column.")
            quote = "First line with overfitting and limitations. " + " ".join(lines[2:])
            position = quote_position(page, quote)
            self.assertEqual(len(position["rects"]), 15, "Highlight cannot stop after the first 8 words or 12 lines")
            self.assertTrue(all(rect[2] < 350 for rect in position["rects"]))
            self.assertNotIn("rects", quote_position(page, "A quote that does not exist."))
            pdf.close()

    def test_cosine_gate_sends_every_qualifying_chunk_to_bertscore(self):
        class RecordingScorer:
            def __init__(self): self.seen = 0
            def score(self, candidates, references, **kwargs):
                self.seen += len(candidates)
                return None, None, FakeScores([0.9] * len(candidates))
        with patch.dict(sys.modules, {"pymupdf": types.SimpleNamespace(open=lambda path: FakePDF())}), \
                tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"mock")
            scorer = RecordingScorer()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), scorer)
            for key, vector in (("A", (1.0, 0.0)), ("B", (0.96, 0.28)),
                                ("C", (0.8, 0.6))):
                engine.index_pdf({"library_id": 1, "item_key": key, "attachment_key": key,
                                  "pdf_path": str(pdf), "title": "Klima"})
                with engine._connect() as db:
                    db.execute("UPDATE chunks SET embedding_blob=? WHERE attachment_key=?",
                               (struct.pack("<ff", *vector), key))
            with engine._connect() as db:
                ranked = engine._vector_rank(db, 1, "Klima", {})
            self.assertEqual(len(ranked), 2)
            page = engine.search_page({"library_id": 1, "query": "Klima"})
            self.assertEqual(page["scored_chunks"], 2)
            self.assertEqual(scorer.seen, 2)

    def test_paginated_search_migrates_vectors_and_caps_bertscore_batch(self):
        class ManyPDF:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                for number in range(90):
                    rng = random.Random(number)
                    words = ["".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=9)) for _ in range(12)]
                    yield types.SimpleNamespace(get_text=lambda mode, words=words:
                                                "Klima " + " ".join(words) + ".")
        class RecordingScorer(FakeScorer):
            batch_sizes = []
            def score(self, candidates, references, **kwargs):
                self.batch_sizes.append(len(candidates))
                return super().score(candidates, references, **kwargs)
        with patch.dict(sys.modules, {"pymupdf": types.SimpleNamespace(open=lambda path: ManyPDF())}), \
                tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "many.pdf"
            path.write_bytes(b"mock")
            scorer = RecordingScorer()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), scorer)
            engine.index_pdf({"library_id": 1, "item_key": "A", "attachment_key": "PDF",
                              "pdf_path": str(path), "title": "Klima"})
            with closing(sqlite3.connect(engine.db_path)) as db:
                db.execute("UPDATE chunks SET embedding_blob=NULL")
                db.commit()
            page = engine.search_page({"library_id": 1, "query": "Klima", "limit": 20})
            found = list(page["results"])
            while page["has_more"]:
                page = engine.search_page({"library_id": 1, "search_id": page["search_id"],
                                           "offset": page["next_offset"], "limit": 20})
                found.extend(page["results"])
            self.assertEqual(len(found), 90)
            self.assertEqual(len({hit["quote"] for hit in found}), 90)
            self.assertTrue(all(size <= 64 for size in scorer.batch_sizes))
            self.assertEqual(engine.search_page({"library_id": 2, "query": "Klima"})["results"], [])
            with closing(sqlite3.connect(engine.db_path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM chunks WHERE embedding_blob IS NULL"
                                            ).fetchone()[0], 0)

    def test_exact_pdf_position_and_saved_quote_library_scope(self):
        with patch.dict(sys.modules, {"pymupdf": real_pymupdf}), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf = real_pymupdf.open()
            page = pdf.new_page()
            page.insert_text((72, 150), "Der Klimawandel beeinflusst die Landwirtschaft erheblich.")
            pdf.save(pdf_path)
            pdf.close()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), FakeScorer())
            engine.index_pdf({"library_id": 1, "item_key": "ARTICLE", "attachment_key": "PDF",
                              "pdf_path": str(pdf_path), "title": "Klimastudie"})
            hit = engine.search({"library_id": 1, "query": "Klima"})[0]
            self.assertEqual(hit["position"]["pageIndex"], 0)
            self.assertTrue(hit["position"]["rects"])
            saved = engine.save_quote(hit)
            self.assertEqual(saved["position"], hit["position"])
            self.assertEqual(engine.save_quote(hit)["id"], saved["id"])
            self.assertEqual(engine.saved_quotes(2), [])
            self.assertEqual(len(engine.saved_quotes(1, "Klimastudie")), 1)
            self.assertEqual(engine.update_saved_note(1, saved["id"], "Wichtig")["note"], "Wichtig")
            self.assertEqual(len(engine.saved_quotes(1, "Wichtig")), 1)
            with self.assertRaises(ValueError):
                engine.update_saved_note(2, saved["id"], "Fremd")
            engine.delete_saved_quote(1, saved["id"])
            self.assertEqual(engine.saved_quotes(1), [])

    def test_locator_uses_current_zotero_path_without_waiting_for_search_lock(self):
        with patch.dict(sys.modules, {"pymupdf":real_pymupdf}), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf = real_pymupdf.open()
            page = pdf.new_page()
            quote = "The smaller patches improve feature quality but reduce throughput."
            page.insert_text((72,150), quote)
            pdf.save(pdf_path)
            pdf.close()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), FakeScorer())
            engine.index_pdf({"library_id":1, "item_key":"A", "attachment_key":"PDF", "title":"Paper", "pdf_path":str(pdf_path)})
            moved_path = root / "moved.pdf"
            pdf_path.rename(moved_path)
            results, errors = [], []
            def locate():
                try:
                    results.append(engine.locate_quote({"library_id":1, "attachment_key":"PDF", "page":1,
                                                       "quote":quote, "pdf_path":str(moved_path)}))
                except Exception as exc: errors.append(exc)
            with engine.lock:
                worker = threading.Thread(target=locate)
                worker.start()
                worker.join(timeout=2)
                blocked = worker.is_alive()
            worker.join(timeout=2)
            self.assertFalse(blocked, "PDF location must not wait behind a search holding the engine lock")
            self.assertEqual(errors, [])
            self.assertTrue(results[0]["position"]["rects"])
            with self.assertRaisesRegex(ValueError, "Bibliothek"):
                engine.locate_quote({"library_id":2, "attachment_key":"PDF", "page":1, "quote":quote, "pdf_path":str(moved_path)})

    def test_library_scope_and_citation_page(self):
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: FakePDF())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "article.pdf"
            pdf.write_bytes(b"mock")
            engine = Engine(root / "index.sqlite", FakeEmbedder(), FakeScorer())
            item = {"library_id": 1, "item_key": "ABC", "attachment_key": "PDF1",
                    "collection_ids": [12], "title": "Artikel", "creators": "A. Beispiel",
                    "year": "2024", "zotero_uri": "zotero://select/library/items/ABC", "pdf_path": str(pdf)}
            self.assertEqual(engine.index_pdf(item)["status"], "indexed")
            self.assertEqual(engine.stats(1), {"library_id": 1, "documents": 1, "chunks": 1,
                                               "topic_documents": 1})
            self.assertEqual(engine.stats(2), {"library_id": 2, "documents": 0, "chunks": 0,
                                               "topic_documents": 0})
            self.assertEqual(engine.index_pdf(item)["status"], "unchanged")
            self.assertEqual(engine.search({"library_id": 2, "query": "Klima"}), [])
            hits = engine.search({"library_id": 1, "query": "Klima"})
            self.assertEqual(hits[0]["page"], 1)
            self.assertIn("Klimawandel", hits[0]["quote"])
            self.assertEqual(hits[0]["title"], "Artikel")

    def test_chunks_preserve_short_source_text(self):
        source = "Ein langer relevanter Satz über Klima. Noch ein relevanter Satz."
        self.assertEqual(chunks(source), [source])

    def test_chunk_overlap(self):
        source = "Erster Satz mit vielen einzelnen Wörtern zu einem Thema. " * 9
        parts = chunks(source, target_words=30, overlap_words=6)
        self.assertGreater(len(parts), 1)
        self.assertEqual(parts[0].split()[-6:], parts[1].split()[:6])

    def test_language_metadata_and_text_fallback(self):
        self.assertEqual(normalize_language("English"), "en")
        self.assertEqual(normalize_language("de-DE"), "de")
        self.assertEqual(detect_language("The model and the data are in the paper. " * 3), "en")
        self.assertEqual(detect_language("Die Daten und der Text sind in der Arbeit. " * 3), "de")

    def test_search_uses_document_language_query(self):
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: FakePDF())
        class RecordingScorer(FakeScorer):
            references_seen = []
            def score(self, candidates, references, **kwargs):
                self.references_seen.extend(references)
                return super().score(candidates, references, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "article.pdf"
            pdf.write_bytes(b"mock")
            scorer = RecordingScorer()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), scorer)
            for language, key in [("English", "EN"), ("Deutsch", "DE")]:
                engine.index_pdf({"library_id": 1, "item_key": key, "attachment_key": key,
                                  "pdf_path": str(pdf), "title": key, "language": language})
            self.assertEqual(engine.languages(1), {"de": 1, "en": 1})
            engine.search({"library_id": 1, "query": "Überanpassung",
                           "queries": {"en": "overfitting evidence", "de": "Belege für Überanpassung"}})
            self.assertIn("overfitting evidence", scorer.references_seen)
            self.assertIn("Belege für Überanpassung", scorer.references_seen)

    def test_search_deduplicates_repeated_quotes_in_one_pdf(self):
        repeated = "Der Klimawandel beeinflusst die Landwirtschaft erheblich. " * 40
        page = types.SimpleNamespace(get_text=lambda mode: repeated)
        class RepeatedPDF:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self): return iter([page])
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: RepeatedPDF())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "repeated.pdf"
            pdf.write_bytes(b"mock")
            engine = Engine(root / "index.sqlite", FakeEmbedder(), FakeScorer())
            engine.index_pdf({"library_id": 1, "item_key": "A", "attachment_key": "PDF",
                              "pdf_path": str(pdf), "title": "Wiederholung"})
            engine.index_pdf({"library_id": 1, "item_key": "B", "attachment_key": "PDF2",
                              "pdf_path": str(pdf), "title": "Kopie"})
            hits = engine.search({"library_id": 1, "query": "Klima", "limit": 10})
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["quote"],
                             "Der Klimawandel beeinflusst die Landwirtschaft erheblich.")

    def test_topic_flags_are_saved_but_do_not_exclude_documents(self):
        class TopicPDF:
            def __init__(self, path):
                self.text = ("Klima und Landwirtschaft verändern die Ernten erheblich. " * 3
                             if "climate" in str(path) else
                             "Neuronen und Synapsen prägen die neurologische Entwicklung. " * 3)
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                return iter([types.SimpleNamespace(get_text=lambda mode: self.text)])
        class RecordingScorer(FakeScorer):
            seen = []
            def score(self, candidates, references, **kwargs):
                self.seen.extend(candidates)
                return super().score(candidates, references, **kwargs)
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: TopicPDF(path))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scorer = RecordingScorer()
            engine = Engine(root / "index.sqlite", FakeEmbedder(), scorer)
            for key, title in [("climate", "Klima Landwirtschaft"),
                               ("brain", "Neurologische Forschung")]:
                pdf = root / (key + ".pdf")
                pdf.write_bytes(b"mock")
                engine.index_pdf({"library_id": 1, "item_key": key, "attachment_key": key,
                                  "pdf_path": str(pdf), "title": title})
            with closing(sqlite3.connect(engine.db_path)) as db:
                rows = db.execute("SELECT attachment_key,topic_flags,topic_embedding FROM documents"
                                  ).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertIn("klima", json.loads(rows[0][1]))
                self.assertTrue(json.loads(rows[0][2]))
                # Simulate a PDF indexed by an older add-on version.
                db.execute("UPDATE documents SET topic_flags='[]',topic_embedding='[]' "
                           "WHERE attachment_key='climate'")
                db.commit()
            hits = engine.search({"library_id": 1, "query": "Klima", "limit": 5})
            self.assertTrue(hits)
            self.assertEqual({hit["attachment_key"] for hit in hits}, {"climate"})
            self.assertEqual(hits[0]["attachment_key"], "climate")
            self.assertFalse(any("Neuronen" in text for text in scorer.seen),
                             "Exact keyword matches do not require BERTScore on unrelated chunks")
            unrelated = engine.search_page({"library_id": 1, "query": "Erdbeerkuchen", "limit": 5})
            self.assertEqual(unrelated["results"], [])
            self.assertFalse(unrelated["has_more"])
            with closing(sqlite3.connect(engine.db_path)) as db:
                stored = db.execute("SELECT topic_flags FROM documents WHERE attachment_key='climate'"
                                    ).fetchone()[0]
                self.assertIn("klima", json.loads(stored))

    def test_quote_selection_matches_inflected_pdf_word(self):
        text = ("Higher dimensions improve the representation quality in this dataset. "
                "With more parameters, the models overﬁt on observed links and fail on unseen links.")
        class TopicPDF:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                return iter([types.SimpleNamespace(get_text=lambda mode: text)])
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: TopicPDF())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "overfit.pdf"
            pdf.write_bytes(b"mock")
            class HighScorer:
                def score(self, candidates, references, **kwargs):
                    return None, None, FakeScores([0.8] * len(candidates))
            engine = Engine(root / "index.sqlite", FakeEmbedder(), HighScorer())
            engine.index_pdf({"library_id": 1, "item_key": "A", "attachment_key": "PDF",
                              "pdf_path": str(pdf), "title": "Overfitting"})
            hits = engine.search({"library_id": 1, "query": "overfitting"})
            self.assertEqual(len(hits), 1)
            self.assertIn("overﬁt", hits[0]["quote"])

    def test_quote_selection_prefers_distinctive_search_term(self):
        common = "Graph embedding methods represent nodes in a vector space. "
        rare = ("Graph embedding methods represent nodes in a vector space. "
                "Additional parameters make these models overﬁt the training links.")
        class TopicPDF:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                for page in range(8):
                    yield types.SimpleNamespace(get_text=lambda mode, page=page:
                                                rare if page == 7 else common)
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: TopicPDF())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"mock")
            class HighScorer:
                def score(self, candidates, references, **kwargs):
                    return None, None, FakeScores([0.8] * len(candidates))
            engine = Engine(root / "index.sqlite", FakeEmbedder(), HighScorer())
            engine.index_pdf({"library_id": 1, "item_key": "A", "attachment_key": "PDF",
                              "pdf_path": str(pdf), "title": "Graph embeddings"})
            hits = engine.search({"library_id": 1,
                                  "query": "overfitting graph embedding", "limit": 20})
            self.assertIn("overﬁt", next(hit for hit in hits if hit["page"] == 8)["quote"])

    def test_later_windows_do_not_restore_generic_quotes(self):
        class ManyPDF:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                for page in range(70):
                    unique = "".join(random.Random(page).choices("abcdefghijklmnopqrstuvwxyz", k=10))
                    text = ("Graph embedding methods represent nodes in the " + unique + " dataset. "
                            + ("Extra parameters cause models to overﬁt observed links."
                               if page == 0 else ""))
                    yield types.SimpleNamespace(get_text=lambda mode, text=text: text)
        sys.modules["pymupdf"] = types.SimpleNamespace(open=lambda path: ManyPDF())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "many.pdf"
            pdf.write_bytes(b"mock")
            class HighScorer:
                def score(self, candidates, references, **kwargs):
                    return None, None, FakeScores([0.8] * len(candidates))
            engine = Engine(root / "index.sqlite", FakeEmbedder(), HighScorer())
            engine.index_pdf({"library_id": 1, "item_key": "A", "attachment_key": "PDF",
                              "pdf_path": str(pdf), "title": "Graph embeddings"})
            page = engine.search_page({"library_id": 1,
                                       "query": "overfitting graph embedding", "limit": 2})
            self.assertEqual(len(page["results"]), 1)
            self.assertIn("overﬁt", page["results"][0]["quote"])
            self.assertFalse(page["has_more"])
            self.assertEqual(page["scored_chunks"], 70)

    def test_mae_case_insensitive_search_returns_each_matching_sentence(self):
        text = " ".join(
            f"The MAE result for model {number} was measured on a separate test sample."
            for number in range(25))
        class AcronymPDF:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                return iter([types.SimpleNamespace(get_text=lambda mode: text),
                             types.SimpleNamespace(get_text=lambda mode:
                                                   "An unrelated baseline was recorded separately.")])
        class LowScorer:
            def score(self, candidates, references, **kwargs):
                return None, None, FakeScores([0.1] * len(candidates))
        class AcronymEmbedder:
            def encode(self, texts, **kwargs):
                return [FakeVector([1.0, 0.0] if "MAE" in text else [0.0, 1.0])
                        for text in texts]
        with patch.dict(sys.modules, {"pymupdf": types.SimpleNamespace(open=lambda path: AcronymPDF())}), \
                tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "mae.pdf"
            pdf.write_bytes(b"mock")
            engine = Engine(root / "index.sqlite", AcronymEmbedder(), LowScorer())
            engine.index_pdf({"library_id": 1, "item_key": "A", "attachment_key": "PDF",
                              "pdf_path": str(pdf), "title": "Measurement errors"})
            for spelling in ("MAE", "mae"):
                page = engine.search_page({"library_id": 1, "query": spelling, "limit": 20})
                hits = list(page["results"])
                self.assertTrue(page["has_more"])
                while page["has_more"]:
                    page = engine.search_page({"library_id": 1, "search_id": page["search_id"],
                                               "offset": page["next_offset"], "limit": 20})
                    hits.extend(page["results"])
                self.assertEqual(len(hits), 25)
                self.assertEqual(len({hit["quote"] for hit in hits}), 25)
                self.assertTrue(all("MAE" in hit["quote"] for hit in hits))
                self.assertLess(page["scored_chunks"], page["total_chunks"],
                                "BERTScore only sees cosine-qualified chunks")
            self.assertEqual(engine.search({"library_id": 1, "query": "rms"}), [])

    def test_flag_prefilter_keeps_documents_when_flags_miss_query(self):
        class DocumentPDF:
            def __init__(self, path):
                self.text = ("Der Klimawandel beeinflusst die Landwirtschaft erheblich."
                             if "relevant" in str(path) else
                             "Neuronen und Synapsen werden in dieser Studie beschrieben.")
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                return iter([types.SimpleNamespace(get_text=lambda mode: self.text)])
        with patch.dict(sys.modules, {"pymupdf": types.SimpleNamespace(open=DocumentPDF)}), \
                tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = Engine(root / "index.sqlite", FakeEmbedder(), FakeScorer())
            for number in range(24):
                pdf = root / f"neutral-{number}.pdf"
                pdf.write_bytes(b"mock")
                key = f"A{number:02d}"
                engine.index_pdf({"library_id": 1, "item_key": key, "attachment_key": key,
                                  "pdf_path": str(pdf), "title": "Neutrale Forschung"})
            pdf = root / "relevant.pdf"
            pdf.write_bytes(b"mock")
            engine.index_pdf({"library_id": 1, "item_key": "ZZZ", "attachment_key": "ZZZ",
                              "pdf_path": str(pdf), "title": "Neutrale Forschung"})
            with closing(sqlite3.connect(engine.db_path)) as db:
                db.execute("UPDATE documents SET topic_flags='[\"fremd\"]', "
                           "topic_embedding='[0.0,1.0]' WHERE attachment_key='ZZZ'")
                db.commit()
            with engine._connect() as db:
                ranked = engine._vector_rank(db, 1, "Klimawandel", {})
            self.assertEqual(len(ranked), 1)
            hits = engine.search({"library_id": 1, "query": "Klimawandel"})
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["attachment_key"], "ZZZ")

if __name__ == "__main__":
    unittest.main()
