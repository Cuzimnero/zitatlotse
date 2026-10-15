"""Real PDF/SQLite/HTTP flows; deterministic model doubles, no cloud requests."""
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pymupdf

import server
import settings
from engine import Engine


class ControlledEncoder:
    def encode(self, texts, **_):
        return np.asarray([[1., 0., 0.] if any(word in text.casefold() for word in
                           ("overfitting", "validation", "mae")) else
                           [0., 1., 0.] if "orchard" in text.casefold() else [0., 0., 1.]
                           for text in texts], dtype=np.float32)


class SystemFlowTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.scorer = Mock()
        self.scorer.score.side_effect = lambda candidates, references, **_: (
            None, None, np.asarray([.94] * len(candidates)))
        self.engine = Engine(self.root / "quotes.sqlite", ControlledEncoder(), self.scorer)
        self.patch(server, "engine", self.engine)
        self.patch(settings, "DATA_DIR", self.root)
        self.patch(settings, "SETTINGS_PATH", self.root / "settings.json")
        self.patch(settings, "_keyring", Mock(side_effect=AssertionError("Real credentials accessed")))
        settings.save_settings({"provider":"none", "search_mode":"fast"})
        self.http = server.LocalServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_http)
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        self.pdf = self.make_pdf("study", [
            "Overfitting increased the Average validation error in the baseline experiment. "
            "The MAE reached 6.66 when the model used body information alone.",
            "Regularization reduced overfitting across the validation cohorts. "
            "The MAE fell to 4.12 after independent hyperparameter selection.",
            "External validation revealed overfitting in the smallest training sample. "
            "A larger MAE of 8.25 indicates that the uncertainty remains substantial."])
        self.metadata = {"library_id":71, "item_key":"ITEM", "attachment_key":"PDF",
                         "pdf_path":str(self.pdf), "language":"en-US", "title":"Synthetic validation study",
                         "creators":"Example, A.", "year":"2026", "collection_ids":[10]}
        self.post("/index", self.metadata)

    def patch(self, obj, name, value):
        p = patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)
        return value

    def stop_http(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(3)

    def make_pdf(self, name, texts):
        path = self.root / (name + ".pdf")
        with pymupdf.open() as pdf:
            for text in texts:
                page = pdf.new_page()
                self.assertGreater(page.insert_textbox((45, 45, 540, 650), text, fontsize=12), 0)
            pdf.save(path)
        return path

    def request(self, path, data=None, headers=None, raw=None):
        body = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, body, headers if headers is not None else
                          {"Content-Type":"application/json", "X-Zitatlotse-Client":"1"})
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def post(self, path, data):
        status, result = self.request(path, data)
        self.assertEqual(status, 200, result)
        return result

    def search(self, **changes):
        return self.post("/search", {"library_id":71, "query":"MAE", **changes})

    def test_http_pdf_index_metadata_flags_and_unchanged_rescan(self):
        """PDF indexing stores page chunks, normalized language and flags without duplicate rescans."""
        before = self.request("/status?library_id=71")[1]
        self.assertEqual(before["documents"], 1)
        self.assertEqual(before["chunks"], 3)
        self.assertEqual(self.post("/index", self.metadata)["status"], "unchanged")
        self.assertEqual(self.request("/status?library_id=71")[1], before)
        with self.engine._connect() as db:
            row = db.execute("SELECT language,topic_flags FROM documents").fetchone()
        self.assertEqual(row["language"], "en")
        self.assertTrue(json.loads(row["topic_flags"]))

    def test_http_keyword_case_pagination_and_pdf_rectangles(self):
        """Case variants find the same three MAE passages and real PDF highlight rectangles."""
        for query in ("MAE", "mae", "MaE"):
            page = self.search(query=query, limit=1)
            hits = list(page["results"])
            while page["has_more"]:
                page = self.search(search_id=page["search_id"], offset=page["next_offset"], limit=1)
                hits.extend(page["results"])
            self.assertEqual({h["page"] for h in hits}, {1, 2, 3})
            self.assertEqual(len(hits), 3)
            for hit in hits:
                self.assertTrue(hit["position"]["rects"])
                self.assertEqual(hit["position"]["pageIndex"], hit["page"] - 1)

    def test_http_collection_library_and_session_isolation(self):
        """Identical attachment keys in two libraries and paginated collection scopes remain isolated."""
        self.post("/index", {**self.metadata, "library_id":72})
        first = self.search(collection_id=10, attachment_keys=["PDF"], limit=1)
        self.assertTrue(first["results"])
        self.assertTrue(all(h["library_id"] == 71 for h in first["results"]))
        for changes in ({"library_id":72}, {"collection_id":11}):
            status, _ = self.request("/search", {"library_id":71, "collection_id":10,
                "search_id":first["search_id"], **changes})
            self.assertEqual(status, 400)
        self.assertEqual(self.search(collection_id=12, attachment_keys=[])["results"], [])
        self.assertEqual(self.search(library_id=99)["results"], [])

    def test_http_saved_quote_note_search_delete_and_foreign_access(self):
        """Saving twice is idempotent; note search works; foreign-library writes fail."""
        hit = self.search()["results"][0]
        saved = self.post("/saved/add", hit)
        again = self.post("/saved/add", hit)
        self.assertEqual(saved["id"], again["id"])
        self.post("/saved/note", {"library_id":71, "id":saved["id"], "note":"check this finding"})
        found = self.post("/saved/list", {"library_id":71, "query":"CHECK finding"})["results"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["position"], hit["position"])
        self.assertEqual(self.post("/saved/list", {"library_id":72})["results"], [])
        for endpoint in ("/saved/note", "/saved/delete"):
            self.assertEqual(self.request(endpoint, {"library_id":72, "id":saved["id"]})[0], 400)
        self.post("/saved/delete", {"library_id":71, "id":saved["id"]})
        self.assertEqual(self.post("/saved/list", {"library_id":71})["results"], [])

    def test_http_modified_pdf_replaces_old_chunks_preserves_saved_quote(self):
        """Changed PDF contents replace old index rows while preserving existing saved quotations."""
        hit = self.search()["results"][0]
        saved = self.post("/saved/add", hit)
        path = self.make_pdf("revised", ["Overfitting and validation need revision. Replacementmarker appears in this update."])
        result = self.post("/index", {**self.metadata, "pdf_path":str(path)})
        self.assertEqual(result["status"], "indexed")
        self.assertTrue(self.search(query="Replacementmarker")["results"])
        with self.engine._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 1)
        self.assertEqual(self.post("/saved/list", {"library_id":71})["results"][0]["id"], saved["id"])

    def test_http_restart_engine_preserves_index_notes_and_mode(self):
        """A new Engine instance reads the same index and notes; disk settings retain Fast mode."""
        saved = self.post("/saved/add", self.search()["results"][0])
        self.post("/saved/note", {"library_id":71, "id":saved["id"], "note":"survives restart"})
        self.patch(server, "engine", Engine(self.root / "quotes.sqlite", ControlledEncoder(), self.scorer))
        self.assertEqual(len(self.search()["results"]), 3)
        self.assertEqual(self.post("/saved/list", {"library_id":71})["results"][0]["note"], "survives restart")
        self.assertEqual(self.request("/settings")[1]["search_mode"], "fast")

    def test_http_speed_modes_and_existing_page_snapshot(self):
        """Fast HTTP search skips BERT; existing pages keep Fast after Normal becomes the default."""
        first = self.search(query="overfitting validation", limit=1)
        self.assertTrue(first["results"])
        self.scorer.score.assert_not_called()
        self.post("/settings", {"search_mode":"thorough"})
        resumed = self.search(search_id=first["search_id"], offset=0)
        self.assertEqual(resumed["search_mode"], "fast")
        self.scorer.score.assert_not_called()
        normal = self.search(query="overfitting validation")
        self.assertEqual(normal["search_mode"], "thorough")
        self.assertTrue(normal["results"])
        self.scorer.score.assert_called()

    def test_http_no_match_and_invalid_requests_recover(self):
        """Unrelated vectors return no quotes; malformed requests fail without disabling health/search."""
        self.assertEqual(self.search(query="orchard farming harvest")["results"], [])
        self.assertEqual(self.request("/search", raw=b'{broken')[0], 400)
        self.assertEqual(self.request("/status?library_id=invalid")[0], 400)
        self.assertEqual(self.request("/unknown")[0], 404)
        self.assertTrue(self.request("/health")[1]["ok"])
        self.assertTrue(self.search()["results"])

    def test_http_rejects_missing_client_headers_and_wrong_content_type(self):
        """POST requests require the add-on marker and JSON content type."""
        for headers in ({"Content-Type":"application/json"},
                        {"Content-Type":"text/plain", "X-Zitatlotse-Client":"1"}):
            self.assertEqual(self.request("/search", {"library_id":71,"query":"MAE"}, headers=headers)[0], 403)
        self.assertTrue(self.search()["results"])

    def test_http_pdf_locator_current_path_and_wrong_page(self):
        """Quote lookup uses a moved PDF's current path and rejects an out-of-range page."""
        hit = self.search()["results"][0]
        moved = self.root / "moved.pdf"
        self.pdf.rename(moved)
        position = self.post("/quote-position", {**hit, "pdf_path":str(moved)})["position"]
        self.assertTrue(position["rects"])
        self.assertEqual(self.request("/quote-position", {**hit,"pdf_path":str(moved),"page":999})[0], 400)

    def test_http_chat_plan_review_and_rejection_use_real_retrieval(self):
        """Controlled AI planning and review operate on real PDF results, including rejecting all quotes."""
        self.post("/settings", {"provider":"ollama", "model":"test-only", "agentic_enabled":False})
        plan = '{"queries":{"en":"overfitting validation"}}'
        answers = self.patch(server, "call_llm", Mock(side_effect=[plan,
            '{"answer":"Validation evidence [1].","has_evidence":true,"selected_refs":[1]}']))
        result = self.post("/chat-search", {"library_id":71,"message":"Welche Befunde beschreiben die Validierung?","ui_lang":"de"})
        self.assertTrue(result["reviewed"])
        self.assertTrue(result["results"][0]["recommended"])
        self.assertTrue(result["results"][0]["position"]["rects"])
        answers.side_effect = [plan, '{"answer":"","has_evidence":false,"selected_refs":[]}']
        rejected = self.post("/chat-search", {"library_id":71,"message":"Welche Befunde beschreiben die Validierung?"})
        self.assertEqual(rejected["results"], [])
        self.assertFalse(rejected["has_more"])

    def test_http_parallel_searches_keep_results_in_their_library(self):
        """Eight concurrent HTTP requests retain library scope and do not mix search sessions."""
        self.post("/index", {**self.metadata, "library_id":72})
        libraries = [71, 72, 99, 71, 72, 99, 71, 72]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda library:self.search(library_id=library), libraries))
        for library, result in zip(libraries, results):
            self.assertEqual(len(result["results"]), 0 if library == 99 else 3)
            self.assertTrue(all(hit["library_id"] == library for hit in result["results"]))

    def test_http_relevance_chart_deduplicates_pdf_copies_and_sorts_scores(self):
        """Real indexed PDF copies count once; the orthogonal control document ranks below the study."""
        self.post("/index", {**self.metadata, "attachment_key":"COPY", "item_key":"COPYITEM"})
        control = self.make_pdf("control", ["The orchard produces apples. Harvest timing influences fruit storage."])
        self.post("/index", {**self.metadata,"attachment_key":"CONTROL", "item_key":"CONTROLITEM",
                             "title":"Orchard control", "pdf_path":str(control)})
        result = self.post("/document-relevance", {"library_id":71,"query":"overfitting validation"})
        self.assertEqual(result["total_attachments"], 3)
        self.assertEqual(result["total_documents"], 2)
        self.assertEqual(result["duplicate_attachments"], 1)
        self.assertEqual([doc["similarity"] for doc in result["documents"]], [1., 0.])
        self.assertEqual([doc["category"] for doc in result["documents"]], ["highest", "lowest"])
        self.assertEqual(sum(category["count"] for category in result["categories"]), 2)

    def test_http_evidence_job_assesses_original_passages_and_counts_balance(self):
        """An asynchronous evidence job retrieves real passages and reports the controlled stance counts."""
        self.post("/settings", {"provider":"ollama", "model":"test-only", "agentic_enabled":False})
        def llm(prompt, _):
            if "\nPassages: " not in prompt:
                return '{"queries":{"en":["overfitting validation"]}}'
            sources = json.loads(prompt.split("\nPassages: ", 1)[1])
            return json.dumps({"assessments":[{"ref":source["ref"], "stance":"pro" if source["ref"] < 3 else "contra",
                "scope":"direct", "reason":"Controlled test classification"} for source in sources]})
        self.patch(server, "call_llm", Mock(side_effect=llm))
        data = {"library_id":71,"message":"Overfitting affects validation.","ui_lang":"en"}
        token = self.post("/evidence/start", data)
        deadline = time.monotonic() + 5
        while True:
            status = self.post("/evidence/status", {**data, **token})
            if status["state"] in {"complete", "error", "cancelled"}: break
            self.assertLess(time.monotonic(), deadline, status)
            time.sleep(.01)
        self.assertEqual(status["state"], "complete", status)
        result = status["result"]
        self.assertEqual(result["evidence"]["pro"], 2)
        self.assertEqual(result["evidence"]["contra"], 1)
        self.assertAlmostEqual(result["evidence"]["pro_percent"], 66.7)
        self.assertAlmostEqual(result["evidence"]["contra_percent"], 33.3)
        self.assertTrue(all(h["position"]["rects"] for h in result["results"]))
        self.assertEqual(len(result["selected_results"]), 3)


if __name__ == "__main__":
    unittest.main()
