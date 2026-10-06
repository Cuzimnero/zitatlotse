import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import evidence_search as evidence
import agent_search as agent


def hit(number, library=7):
    return {"library_id":library, "id":number, "attachment_key":"PDF" + str(number), "item_key":"P",
            "title":"Study " + str(number), "page":number, "quote":"Original passage " + str(number),
            "position":{"pageIndex":number - 1, "rects":[[1,2,3,4]]}}


class EvidenceTest(unittest.TestCase):
    settings = {"provider":"ollama", "agentic_enabled":False}
    data = {"library_id":7, "message":"Model overfits.", "ui_lang":"de"}

    def test_all_pages_all_batches_dedup_and_sixty_forty(self):
        pages = [{"results":[hit(i) for i in range(1, 9)], "search_id":"s", "has_more":True, "next_offset":8},
                 {"results":[hit(8), hit(9), hit(10), hit(11)], "search_id":"s", "has_more":False, "next_offset":12}]
        engine = SimpleNamespace(languages=Mock(return_value={"en":1}), search_page=Mock(side_effect=pages))
        def llm(prompt, _):
            if "Passages: " not in prompt: return '{"queries":{"en":"overfitting generalization"}}'
            sources = json.loads(prompt.split("\nPassages: ", 1)[1])
            return json.dumps({"assessments":[{"ref":s["ref"], "stance":"pro" if s["ref"] <= 6 else
                "contra" if s["ref"] <= 10 else "neutral", "point":"Finding", "reason":"Reason"} for s in sources]})
        llm = Mock(side_effect=llm)
        result = evidence.evidence_search(self.data, engine, self.settings, lambda _:"", llm)
        self.assertEqual(result["evidence"], {"pro":6, "contra":4, "neutral":1, "total":11, "pro_percent":60., "contra_percent":40.})
        self.assertEqual(llm.call_count, 3)
        self.assertEqual(len(result["selected_results"]), 10)
        self.assertEqual(result["results"][8]["quote"], "Original passage 9")
        self.assertEqual(engine.search_page.call_args.args[0]["offset"], 8)
        self.assertTrue(all(h["library_id"] == 7 for h in result["results"]))

    def test_neutral_only_has_no_percentage_and_no_selected_quotes(self):
        engine = SimpleNamespace(languages=Mock(return_value={"en":1}), search_page=Mock(return_value={
            "results":[hit(1)], "has_more":False}))
        llm = Mock(side_effect=['{"queries":{}}', '{"assessments":[{"ref":1,"stance":"neutral","reason":"Insufficient"}]}'])
        result = evidence.evidence_search(self.data, engine, self.settings, lambda _:"", llm)
        self.assertIsNone(result["evidence"]["pro_percent"])
        self.assertEqual(result["selected_results"], [])
        self.assertIn("Keine ausreichend", result["reply"])

    def test_invalid_refs_or_incomplete_review_fail_instead_of_false_balance(self):
        for answer in ('{"assessments":[]}', '{"assessments":[{"ref":99,"stance":"pro","reason":"Fake"}]}'):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                evidence.review_evidence("Claim", [{**hit(1), "reference_number":1}], self.settings, "de", lambda *_:answer)

    def test_foreign_library_hits_rejected(self):
        engine = SimpleNamespace(languages=lambda _: {}, search_page=lambda _:{"results":[hit(1, 8)], "has_more":False})
        with self.assertRaisesRegex(ValueError, "Bibliothek"):
            evidence.evidence_search(self.data, engine, self.settings, lambda _:"", Mock())

    def test_agent_collects_all_pages_even_when_finish_selects_no_quotes(self):
        def tool(name, arguments): return {"calls":[{"id":"call", "name":name,"arguments":arguments}]}
        engine = SimpleNamespace(languages=lambda _: {"en":1}, search_page=Mock(side_effect=[
            {"results":[hit(1)], "search_id":"s", "next_offset":1, "has_more":True},
            {"results":[hit(2)], "search_id":"s", "next_offset":2, "has_more":False}]))
        settings = {**self.settings,"agentic_enabled":True,"agentic_max_steps":2}
        with patch.object(agent, "call_agent_model", side_effect=[tool("search_library", {"query":"overfitting","language":"en"}),
             tool("finish_search", {"answer":"", "has_evidence":False, "selected_refs":[]})]):
            llm = Mock(return_value='{"assessments":[{"ref":1,"stance":"pro","reason":"Supports"},{"ref":2,"stance":"contra","reason":"Opposes"}]}')
            result = evidence.evidence_search(self.data, engine, settings, lambda _:"", llm)
        self.assertTrue(result["agentic_used"])
        self.assertEqual(result["evidence"]["total"], 2)
        self.assertEqual(result["evidence"]["contra_percent"], 50.)

    def test_jobs_are_library_scoped_and_can_cancel_before_next_batch(self):
        jobs = evidence.EvidenceJobs()
        gate = threading.Event()
        def runner(progress):
            gate.wait(2)
            progress(phase="reviewing", completed=1, total=1)
            return {"test":"result"}
        job = jobs.start(self.data, runner)
        with self.assertRaises(ValueError): jobs.status({"library_id":8, **job})
        self.assertEqual(jobs.status({"library_id":7, **job}, cancel=True)["state"], "cancelled")
        gate.set()
        time.sleep(.02)
        self.assertNotIn("result", jobs.status({"library_id":7, **job}))

    def test_separate_aspect_queries_collect_all_pages_before_next_search(self):
        pages = [{"results":[hit(1)], "search_id":"benefit", "has_more":True, "next_offset":1},
                 {"results":[hit(2)], "search_id":"benefit", "has_more":False},
                 {"results":[hit(2), hit(3)], "search_id":"cost", "has_more":False}]
        engine = SimpleNamespace(languages=lambda _: {"en":1}, search_page=Mock(side_effect=pages))
        def llm(prompt, _):
            if "Passages: " not in prompt:
                return '{"queries":{"en":["patch representation quality","patch computational throughput"]}}'
            sources = json.loads(prompt.split("\nPassages: ", 1)[1])
            return json.dumps({"assessments":[{"ref":s["ref"], "stance":"pro" if s["ref"] < 3 else "contra",
                "scope":"aspect", "point":"Measured aspect", "reason":"Overall judgment remains open"} for s in sources]})
        result = evidence.evidence_search(self.data, engine, self.settings, lambda _:"", llm)
        calls = [c.args[0] for c in engine.search_page.call_args_list]
        self.assertEqual([c.get("query") for c in calls], ["patch representation quality", None, "patch computational throughput"])
        self.assertEqual(calls[1]["search_id"], "benefit")
        self.assertTrue(all(c["library_id"] == 7 for c in calls))
        self.assertEqual(calls[0]["retrieval_mode"], "evidence")
        self.assertEqual(result["evidence"]["total"], 3, "Deduplicate shared passages across aspect searches")
        self.assertTrue(all(h["evidence_scope"] == "aspect" for h in result["selected_results"]))


if __name__ == "__main__": unittest.main()
