"""Deterministic performance contracts; no cloud calls or model downloads."""
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import threading
from contextlib import closing
from unittest.mock import patch, Mock

import numpy as np
from engine import Engine
from document_relevance import document_relevance
from evidence_search import review_evidence, evidence_batches
from search_budget import call_budget, take_call, CallBudgetExceeded
import server
import settings as settings_module


class Encoder:
    def __init__(self): self.calls = []
    def encode(self, texts, **kwargs):
        self.calls.append(list(texts))
        return np.array([[1., 0.] for _ in texts])


class Scorer:
    def __init__(self): self.count = 0
    def score(self, texts, queries, **kwargs):
        self.count += len(texts)
        return None, None, np.array([.9] * len(texts))


class PerformanceTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.encoder, self.scorer = Encoder(), Scorer()
        self.engine = Engine(self.root / "quotes.sqlite", self.encoder, self.scorer)
        with self.engine._connect() as db:
            for library, key in ((1, "A"), (1, "B"), (2, "A")):
                db.execute("INSERT INTO documents (library_id,item_key,attachment_key,collection_ids,title,creators,year,"
                           "zotero_uri,pdf_path,language,topic_flags,topic_embedding,content_fingerprint,file_mtime,file_size) "
                           "VALUES (?,?,?,'[]',?,'','2026','','missing.pdf','en','[\"average\"]','[1,0]',?,0,0)",
                           (library, key, key, key, str(library) + key))
                for i in range(120):
                    text = f"Average error in synthetic experiment {i} was recorded for the independent measurement."
                    db.execute("INSERT INTO chunks (library_id,attachment_key,page,ordinal,text,embedding,embedding_blob) "
                               "VALUES (?,?,?,?,?,'[1,0]',?)",
                               (library, key, i + 1, i, text, np.array([1., 0.], dtype='<f4').tobytes()))
        self.data = {"library_id":1, "collection_id":10, "attachment_keys":["A"], "query":"Average", "limit":20}

    def test_translated_query_is_the_only_vector_and_bert_query_for_english_scope(self):
        with patch.object(self.scorer, "score", wraps=self.scorer.score) as score:
            self.engine.search_page({**self.data, "query":"Wie hoch ist der Fehler?", "progressive":True,
                                     "queries":{"en":"Average validation error"}})
        self.assertEqual(len(self.encoder.calls), 1)
        self.assertEqual(len(self.encoder.calls[0]), 1)
        self.assertTrue(self.encoder.calls[0][0].endswith("Average validation error"))
        self.assertEqual(set(score.call_args.args[1]), {"Average validation error"})

    def test_processing_status_uses_actual_chunks_and_is_library_scoped(self):
        with self.engine._connect() as db:
            db.execute("DELETE FROM chunks WHERE library_id=1 AND attachment_key='B'")
        result = self.engine.processing_status({"library_id":1, "attachment_keys":["A","B","MISSING"]})
        rows = {row["attachment_key"]:row for row in result["documents"]}
        self.assertEqual(rows["A"]["chunks"],120)
        self.assertEqual(rows["B"]["chunks"],0)
        self.assertNotIn("MISSING",rows)
        self.assertNotIn("pdf_path",rows["A"])
        self.assertEqual(self.engine.processing_status({"library_id":3,"attachment_keys":["A"]})["documents"],[])
        self.assertEqual(self.engine.processing_status({"library_id":1,"attachment_keys":[]})["documents"],[])
        for data in ({"library_id":True,"attachment_keys":["A"]},
                     {"library_id":1,"attachment_keys":["A"]*201},
                     {"library_id":1,"attachment_keys":[4]}):
            with self.assertRaises(ValueError):self.engine.processing_status(data)
        self.assertEqual(self.encoder.calls,[])
        self.assertEqual(self.scorer.count,0)

    def test_processing_status_does_not_wait_for_the_search_model_lock(self):
        results=[]
        thread=threading.Thread(target=lambda:results.append(self.engine.processing_status({"library_id":1,"attachment_keys":["A"]})))
        with self.engine.lock:
            thread.start();thread.join(timeout=2)
            blocked=thread.is_alive()
        thread.join(timeout=2)
        self.assertFalse(blocked)
        self.assertEqual(results[0]["documents"][0]["chunks"],120)

    def test_progressive_first_window_is_bounded_and_all_locations_remain_reachable(self):
        first = self.engine.search_page({**self.data, "progressive":True})
        self.assertEqual(self.scorer.count, 40)
        self.assertFalse(first["retrieval_complete"])
        self.assertIsNone(first["total_results"])
        self.assertEqual(first["candidate_count"], 120)
        baseline = self.engine.search_page(self.data)
        progressive_state = self.engine._search_sessions[first["search_id"]]
        baseline_state = self.engine._search_sessions[baseline["search_id"]]
        self.assertEqual(progressive_state["term_frequency"], baseline_state["term_frequency"])
        self.assertEqual(progressive_state["term_sample_size"], 64)
        hits, current = list(first["results"]), first
        while current["has_more"]:
            current = self.engine.search_page({**self.data, "search_id":current["search_id"], "offset":current["next_offset"]})
            hits.extend(current["results"])
        self.assertTrue(current["retrieval_complete"])
        self.assertEqual(len(hits), 120)
        self.assertEqual(len({(h["attachment_key"], h["page"]) for h in hits}), 120)
        self.assertEqual({h["library_id"] for h in hits}, {1})
        self.assertEqual({h["attachment_key"] for h in hits}, {"A"})
        reloaded = self.engine.search_page({**self.data, "search_id":first["search_id"], "offset":0})
        self.assertEqual(reloaded["results"], first["results"])
        with self.assertRaises(ValueError):
            self.engine.search_page({**self.data, "library_id":2, "search_id":first["search_id"]})

    def test_empty_progressive_window_can_continue_without_inventing_results(self):
        with patch.object(self.engine, "_fill_search_session", wraps=self.engine._fill_search_session):
            # No literal match; low BERT scores must reject the first window.
            self.scorer.score = lambda texts, queries, **kw: (None, None, np.zeros(len(texts)))
            first = self.engine.search_page({**self.data, "query":"semantic interpretation of experiments", "progressive":True})
            self.assertEqual(first["results"], [])
            self.assertEqual(first["next_offset"], 0)
            self.assertTrue(first["has_more"])
            second = self.engine.search_page({**self.data, "search_id":first["search_id"], "offset":0})
            self.assertEqual(second["results"], [])
            self.assertEqual(second["scored_chunks"], 80)

    def test_direct_literal_hits_are_not_hidden_behind_higher_cosine_nonmatches(self):
        with self.engine._connect() as db:
            db.execute("UPDATE chunks SET text=replace(text,'Average','Unrelated') "
                       "WHERE library_id=1 AND attachment_key='A' AND page<=110")
            db.execute("UPDATE chunks SET embedding_blob=? WHERE library_id=1 AND attachment_key='A' AND page>110",
                       (np.array([.3, .9539392], dtype='<f4').tobytes(),))
        first = self.engine.search_page({**self.data, "progressive":True})
        self.assertEqual(first["scored_chunks"], 40)
        self.assertEqual(len(first["results"]), 10)
        self.assertEqual({h["page"] for h in first["results"]}, set(range(111, 121)))
        self.assertTrue(all(h["match_type"] == "literal" and h["attachment_key"] == "A"
                            and h["library_id"] == 1 for h in first["results"]))

    def test_unchanged_pdf_refreshes_moved_path_without_reembedding_or_dropping_chunks(self):
        path = self.root / "moved.pdf"
        path.write_bytes(b"fake PDF for unchanged-file check")
        with self.engine._connect() as db:
            db.execute("UPDATE documents SET file_mtime=?,file_size=? WHERE library_id=1 AND attachment_key='A'",
                       (path.stat().st_mtime, path.stat().st_size))
        result = self.engine.index_pdf({"library_id":1, "item_key":"A", "attachment_key":"A", "title":"A",
                                       "pdf_path":str(path), "language":"en"})
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(self.encoder.calls, [])
        with self.engine._connect() as db:
            self.assertEqual(db.execute("SELECT pdf_path FROM documents WHERE library_id=1 AND attachment_key='A'").fetchone()[0], str(path))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chunks WHERE library_id=1 AND attachment_key='A'").fetchone()[0], 120)

    def test_cache_reuses_queries_and_matrices_but_obeys_scope_and_database_changes(self):
        self.engine.search_page(self.data)
        calls = len(self.encoder.calls)
        self.engine.search_page(self.data)
        self.assertEqual(len(self.encoder.calls), calls)
        self.assertGreater(self.engine.retrieval_cache.matrix_hits, 0)
        diagram = document_relevance(self.engine, self.data)
        self.assertEqual({doc["attachment_key"] for doc in diagram["documents"]}, {"A"})
        self.assertEqual(len(self.encoder.calls), calls)
        self.assertTrue(all(doc["similarity"] == 1. for doc in diagram["documents"]))
        with closing(sqlite3.connect(self.engine.db_path)) as db:
            db.execute("UPDATE chunks SET embedding_blob=? WHERE library_id=1 AND attachment_key='A'",
                       (np.array([0., 1.], dtype='<f4').tobytes(),))
            db.commit()
        diagram = document_relevance(self.engine, self.data)
        self.assertEqual(diagram["documents"][0]["similarity"], 0.)
        self.engine.embedding_config = {"query_prefix":"new prefix: "}
        self.engine.retrieval_cache.query_vectors(self.engine, ["Average"])
        self.assertEqual(len(self.encoder.calls), calls + 1)

    def test_cache_memory_limit_falls_back_to_streaming_with_identical_results(self):
        expected = self.engine.search_page(self.data)["results"]
        self.engine.retrieval_cache.invalidate()
        self.engine.retrieval_cache.max_bytes = 1
        actual = self.engine.search_page(self.data)["results"]
        self.assertEqual(actual, expected)
        self.assertEqual(self.engine.retrieval_cache.bytes, 0)
        self.assertFalse(self.engine.retrieval_cache.matrices)
        self.engine.retrieval_cache.max_queries = 2
        self.engine.retrieval_cache.query_vectors(self.engine, ["one", "two", "three"])
        self.assertEqual(len(self.engine.retrieval_cache.queries), 2)

    def test_accelerated_chat_uses_two_calls_and_skips_unneeded_agent(self):
        options = {"provider":"deepseek", "model":"test", "agentic_enabled":True, "latency_optimized":True}
        hit = {"id":1, "library_id":1, "attachment_key":"A", "title":"Synthetic study", "page":1, "quote":"Evidence of overfitting."}
        payloads = []
        def provider(request, **kwargs):
            payloads.append(json.loads(request.data))
            content = ({"queries":{"en":"overfitting empirical evidence"}} if len(payloads) == 1 else
                       {"answer":"Evidence [1].", "has_evidence":True, "selected_refs":[1]})
            return io.BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps(content)}, "finish_reason":"stop"}]}).encode())
        with patch.object(server, "get_settings", return_value=options), patch.object(server, "get_key", return_value="test-key"), \
                patch.object(server.engine, "languages", return_value={"en":1}), \
                patch.object(server.engine, "search_page", return_value={"results":[hit], "search_id":"x", "next_offset":1,
                    "has_more":False, "total_results":1, "total_chunks":1, "retrieval_complete":True}) as search, \
                patch.object(server, "agentic_search") as agent, patch("urllib.request.urlopen", side_effect=provider):
            result = server.chat_search({"library_id":1, "message":"Which experiments establish overfitting?"})
        self.assertEqual(result["performance"]["model_calls"], 2)
        agent.assert_not_called()
        self.assertTrue(result["results"][0]["recommended"])
        self.assertTrue(search.call_args.args[0]["progressive"])
        self.assertEqual(payloads[0]["thinking"], {"type":"disabled"})
        self.assertNotIn("reasoning_effort", payloads[0])
        self.assertEqual(payloads[1]["thinking"], {"type":"enabled"})

    def test_shared_call_budget_includes_retries_and_restores_request_context(self):
        with call_budget(2, 10) as budget:
            self.assertLessEqual(take_call(120), 10)
            take_call(120)
            with self.assertRaises(CallBudgetExceeded): take_call(120)
            self.assertEqual(budget.used, 2)
        self.assertEqual(take_call(120), 120)
        with call_budget(5, -1):
            with self.assertRaises(CallBudgetExceeded): take_call(120)

    def test_missing_evidence_uses_bounded_native_followup_without_false_quotes(self):
        options = {"provider":"deepseek", "model":"test", "agentic_enabled":True,
                   "agentic_max_steps":6, "latency_optimized":True}
        hit = {"id":1, "library_id":1, "attachment_key":"A", "title":"Synthetic study", "page":1, "quote":"Unrelated observation."}
        page = {"results":[hit], "search_id":"x", "next_offset":1, "has_more":False, "total_results":1, "total_chunks":1}
        sent = []
        def provider(request, **kwargs):
            sent.append(json.loads(request.data))
            if len(sent) <= 2:
                value = ({"queries":{"en":"overfitting evidence"}} if len(sent) == 1 else
                         {"answer":"", "has_evidence":False, "selected_refs":[]})
                message = {"content":json.dumps(value)}
            else:
                finish = len(sent) == 5
                message = {"content":"", "reasoning_content":"synthetic test value",
                    "tool_calls":[{"id":str(len(sent)), "type":"function", "function":{
                        "name":"finish_search" if finish else "search_library",
                        "arguments":json.dumps({"answer":"", "has_evidence":False, "selected_refs":[]} if finish else
                                               {"query":"independent experimental aspect " + str(len(sent)), "language":"en"})}}]}
            return io.BytesIO(json.dumps({"choices":[{"message":message,"finish_reason":"stop"}]}).encode())
        with patch.object(server, "get_settings", return_value=options), patch.object(server, "get_key", return_value="test-key"), \
                patch.object(server.engine, "languages", return_value={"en":1}), \
                patch.object(server.engine, "search_page", return_value=page), patch("urllib.request.urlopen", side_effect=provider):
            result = server.chat_search({"library_id":1, "message":"Which experimental findings support this claim?"})
        self.assertEqual(len(sent), 5)
        self.assertEqual(result["performance"]["model_calls"], 5)
        self.assertEqual(result["results"], [])
        self.assertEqual([tool["function"]["name"] for tool in sent[-1]["tools"]], ["finish_search"])

    def test_larger_evidence_batches_review_every_reference_without_changing_balance(self):
        hits = [{"reference_number":i, "title":"Synthetic study", "page":i, "quote":f"Observation {i}."} for i in range(1, 49)]
        calls = []
        def llm(prompt, options):
            sources = json.loads(prompt.split("\nPassages: ")[1])
            calls.append(len(sources))
            return json.dumps({"assessments":[{"ref":s["ref"], "stance":"pro" if s["ref"] % 2 else "contra",
                "reason":"Synthetic reason", "scope":"direct"} for s in sources]})
        optimized = review_evidence("Claim", hits, {"latency_optimized":True}, "en", llm)
        self.assertEqual(calls, [24, 24])
        calls.clear()
        original = review_evidence("Claim", hits, {"latency_optimized":False}, "en", llm)
        self.assertEqual(calls, [8]*6)
        self.assertEqual(optimized, original)
        long = [{**h, "context":"Long context "*1000} for h in hits]
        batches = list(evidence_batches(long, True))
        self.assertEqual(sum(len(b) for b in batches), 48)
        self.assertTrue(all(len(b) < 24 for b in batches))

    def test_acceleration_setting_persists_and_rejects_non_boolean_values(self):
        with patch.object(settings_module, "DATA_DIR", self.root), \
                patch.object(settings_module, "SETTINGS_PATH", self.root / "settings.json"), \
                patch.object(settings_module, "get_key", return_value=""):
            self.assertTrue(settings_module.get_settings()["latency_optimized"])
            self.assertFalse(settings_module.save_settings({"latency_optimized":False})["latency_optimized"])
            with self.assertRaises(ValueError): settings_module.save_settings({"latency_optimized":"false"})


if __name__ == "__main__": unittest.main()
