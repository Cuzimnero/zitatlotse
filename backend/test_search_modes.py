"""Speed-mode regressions: no BERT loading, stable pages and fixed scope."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import numpy as np
import pymupdf as pdf_module
from engine import Engine


class Embedder:
    def encode(self, texts, **kwargs):
        return np.asarray([[1., 0.] for _ in texts], dtype=np.float32)


class SearchModeTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.pdf_patch = patch.dict(sys.modules, {"pymupdf": pdf_module})
        self.pdf_patch.start()
        self.addCleanup(self.pdf_patch.stop)
        root = Path(self.folder.name)
        self.pdf_path = root / "sample.pdf"
        with pdf_module.open() as doc:
            for text in ("Klima und seine Folgen betreffen die Landwirtschaft und die Ernte.",
                         "Klima und seine Folgen beeinflussen Wasserreserven in trockenen Regionen.",
                         "Klima und seine Folgen verändern die Lebensräume der Tiere."):
                page = doc.new_page()
                page.insert_text((50, 80), text)
            doc.save(self.pdf_path)
        self.scorer = Mock()
        self.scorer.score.side_effect = lambda candidates, references, **kw: (None, None, np.asarray([.9] * len(candidates)))
        self.engine = Engine(root / "test.sqlite", Embedder(), self.scorer)
        for library, key in ((71, "PDF"), (71, "OTHER"), (72, "FOREIGN")):
            self.engine.index_pdf({"library_id":library, "item_key":key, "attachment_key":key,
                "pdf_path":str(self.pdf_path), "language":"de", "title":"Climate study"})

    def test_fast_never_loads_or_calls_bert_in_any_retrieval_mode(self):
        with patch.object(Engine, "scorer", new_callable=PropertyMock, side_effect=AssertionError("BERT loaded")):
            for mode in ("direct", "ai", "evidence"):
                with self.subTest(mode=mode):
                    result = self.engine.search_page({"library_id":71, "query":"Klima Folgen",
                        "search_mode":"fast", "retrieval_mode":mode, "attachment_keys":["PDF"]})
                    self.assertTrue(result["results"])
                    self.assertEqual(result["search_mode"], "fast")
                    for hit in result["results"]:
                        self.assertIsNone(hit["bert_score"])
                        self.assertAlmostEqual(hit["score"], 1.)
                        self.assertEqual(hit["attachment_key"], "PDF")
                        self.assertEqual(hit["library_id"], 71)
        self.scorer.score.assert_not_called()

    def test_thorough_default_and_explicit_mode_still_score_candidates(self):
        for mode in (None, "thorough"):
            request = {"library_id":71, "query":"Klima Folgen"}
            if mode: request["search_mode"] = mode
            result = self.engine.search_page(request)
            self.assertEqual(result["search_mode"], "thorough")
            self.assertTrue(result["results"])
            self.assertAlmostEqual(result["results"][0]["bert_score"], .9)
        self.assertGreaterEqual(self.scorer.score.call_count, 2)

    def test_fast_literal_pagination_preserves_mode_scope_and_pdf_positions(self):
        with patch.object(Engine, "scorer", new_callable=PropertyMock, side_effect=AssertionError("BERT loaded")):
            first = self.engine.search_page({"library_id":71, "query":"Klima", "search_mode":"fast",
                "collection_id":10, "attachment_keys":["PDF"], "limit":1})
            hits = list(first["results"])
            page = first
            while page["has_more"]:
                # Even after the user switches defaults, existing pages keep their mode.
                page = self.engine.search_page({"library_id":71, "search_id":first["search_id"],
                    "search_mode":"thorough", "offset":page["next_offset"], "limit":1})
                self.assertEqual(page["search_mode"], "fast")
                hits.extend(page["results"])
            self.assertEqual(len(hits), 3)
            self.assertEqual({h["page"] for h in hits}, {1, 2, 3})
            self.assertTrue(all(h["position"].get("rects") for h in hits))
            self.assertEqual(self.engine.search({"library_id":71,"query":"Klima","search_mode":"fast","attachment_keys":[]}), [])
            self.assertEqual(self.engine.search({"library_id":999,"query":"Klima","search_mode":"fast"}), [])
            with self.assertRaises(ValueError):
                self.engine.search_page({"library_id":72,"search_id":first["search_id"]})
            with self.assertRaises(ValueError):
                self.engine.search_page({"library_id":71,"search_id":first["search_id"],"collection_id":11})

    def test_invalid_mode_and_very_weak_fast_candidates(self):
        for mode in ("unknown", False, None):
            with self.assertRaises(ValueError):
                self.engine.search({"library_id":71,"query":"Klima Folgen","search_mode":mode})
        with self.engine._connect() as db:
            db.execute("UPDATE chunks SET embedding_blob=?", (np.asarray([.2, .9798],dtype="<f4").tobytes(),))
        self.assertEqual(self.engine.search({"library_id":71,"query":"Klima Folgen","search_mode":"fast"}), [])
        self.scorer.score.assert_not_called()


if __name__ == "__main__": unittest.main()
