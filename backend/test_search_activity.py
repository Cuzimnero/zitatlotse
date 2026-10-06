import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agent_search as agent
import evidence_search as evidence
from search_activity import SearchJobs, SearchCancelled
from search_scope import scope_fields
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def tool(name, arguments):
    return {"calls":[{"id":"call", "name":name, "arguments":arguments}], "reasoning_content":"PRIVATE REASONING"}


def hit(number):
    return {"id":number,"library_id":7,"attachment_key":"PDF","item_key":"P", "page":number,
            "title":"Study", "quote":"Original evidence " + str(number)}


class ActivityTest(unittest.TestCase):
    def test_http_chat_jobs_deliver_live_activity_before_answer(self):
        import server
        ready, release = threading.Event(), threading.Event()
        turns = []
        def model(*_, **__):
            turns.append(1)
            if len(turns) == 1: return tool("search_library", {"query":"evidence","language":"en"})
            ready.set()
            release.wait(2)
            return tool("finish_search", {"answer":"Finding [1].", "has_evidence":True, "selected_refs":[1]})
        local = server.LocalServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=local.serve_forever, daemon=True)
        thread.start()
        def post(path, data):
            request = Request(f"http://127.0.0.1:{local.server_port}" + path,
                              json.dumps(data).encode(), {"Content-Type":"application/json","X-Zitatlotse-Client":"1"})
            with urlopen(request, timeout=3) as response: return json.load(response)
        engine = SimpleNamespace(languages=Mock(return_value={"en":1}),search_page=Mock(return_value={"results":[hit(1)]}))
        data = {"library_id":7,"collection_id":10,"attachment_keys":["PDF"],"message":"Find evidence"}
        try:
            with patch.object(server, "engine", engine), patch.object(server, "chat_jobs", SearchJobs()), \
                    patch.object(server, "get_settings", return_value={"provider":"ollama","agentic_enabled":True}), \
                    patch.object(agent, "call_agent_model", side_effect=model):
                token = post("/chat/start", data)
                self.assertTrue(ready.wait(2))
                status = post("/chat/status", {**data, **token})
                self.assertEqual(status["state"], "running")
                self.assertIn("search_results", [event["type"] for event in status["activity"]])
                with self.assertRaises(HTTPError) as wrong_scope:
                    post("/chat/status", {**data, **token, "collection_id":11})
                wrong_scope.exception.close()
                release.set()
                for _ in range(50):
                    status = post("/chat/status", {**data, **token})
                    if status["state"] == "complete": break
                    time.sleep(.005)
                self.assertEqual(status["state"], "complete")
                self.assertEqual(status["result"]["reply"], "Finding [1].")
                self.assertEqual(status["activity"][-1]["type"], "complete")
                engine.languages.assert_called_once_with(7, attachment_keys=["PDF"])
        finally:
            release.set()
            local.shutdown()
            local.server_close()
            thread.join(2)

    def test_live_events_are_bounded_sanitized_and_scoped(self):
        jobs = SearchJobs()
        ready, release, done = threading.Event(), threading.Event(), threading.Event()
        def runner(progress):
            progress(phase="searching",event={"type":"tool_call","tool":"search_library","query":"test query",
                     "reasoning_content":"PRIVATE REASONING", "api_key":"SECRET"})
            ready.set()
            release.wait(2)
            for i in range(300): progress(event={"type":"search_results","count":i})
            done.set()
            return {"results":[],"total_results":0}
        data = {"library_id":7,"collection_id":10,"message":"test"}
        token = jobs.start(data, runner)
        self.assertTrue(ready.wait(2))
        live = jobs.status({**data, **token})
        self.assertEqual(live["state"], "running")
        self.assertEqual(live["activity"][-1]["query"], "test query")
        self.assertNotIn("SECRET", json.dumps(live))
        self.assertNotIn("PRIVATE REASONING", json.dumps(live))
        live["activity"].clear()
        self.assertEqual(len(jobs.status({**data, **token})["activity"]), 2)
        with self.assertRaises(ValueError): jobs.status({**data, **token,"collection_id":11})
        with self.assertRaises(ValueError): jobs.status({**data, **token,"library_id":8})
        release.set()
        self.assertTrue(done.wait(2))
        for _ in range(100):
            snapshot = jobs.status({**data, **token})
            if snapshot["state"] == "complete": break
            time.sleep(.005)
        self.assertEqual(snapshot["state"], "complete")
        events = snapshot["activity"]
        self.assertEqual(len(events), 256)
        self.assertEqual(events[-1]["type"], "complete")
        self.assertEqual([e["sequence"] for e in events], sorted(set(e["sequence"] for e in events)))
        self.assertEqual(snapshot["result"]["activity"], events)

    def test_each_native_search_and_next_model_call_report_real_events_and_keep_scope(self):
        events = []
        engine = SimpleNamespace(search_page=Mock(side_effect=[{"results":[hit(1)]},{"results":[hit(2)]}]))
        data = {"library_id":7,"collection_id":10,"attachment_keys":["PDF"],"message":"Question"}
        with patch.object(agent, "call_agent_model", side_effect=[
                tool("search_library", {"query":"support", "language":"en"}),
                tool("search_library", {"query":"counter evidence", "language":"en"}),
                tool("finish_search", {"answer":"Evidence [1] and [2].", "has_evidence":True,"selected_refs":[1,2]})]):
            result = agent.agentic_search(data, engine, {"provider":"ollama"}, lambda _:"", {"en":1},
                                          lambda **event:events.append(event.get("event", {})))
        self.assertEqual([e["round"] for e in events if e.get("type") == "model_call"], [1,2,3])
        self.assertEqual([e["query"] for e in events if e.get("type") == "tool_call" and "query" in e], ["support","counter evidence"])
        self.assertEqual([e["count"] for e in events if e.get("type") == "search_results"], [1,1])
        self.assertNotIn("PRIVATE REASONING", json.dumps(events))
        self.assertTrue(all(c.args[0]["attachment_keys"] == ["PDF"] for c in engine.search_page.call_args_list))
        with self.assertRaises(ValueError):
            agent.result_store.page({"library_id":7,"collection_id":11,"search_id":result["search_id"]})

    def test_reset_cancels_before_any_fallback_or_model_call(self):
        def cancelled(**_): raise SearchCancelled("Reset")
        engine = SimpleNamespace(languages=Mock(return_value={"en":1}))
        with patch.object(agent, "call_agent_model") as model:
            with self.assertRaises(SearchCancelled):
                evidence.evidence_search({"library_id":7,"message":"claim"}, engine,
                                         {"provider":"ollama","agentic_enabled":True}, lambda _:"", Mock(), cancelled)
            model.assert_not_called()

    def test_empty_scope_is_explicit_and_incomplete_collection_scope_is_rejected(self):
        self.assertEqual(scope_fields({"collection_id":10,"attachment_keys":[]}), {"collection_id":10,"attachment_keys":[]})
        with self.assertRaises(ValueError): scope_fields({"collection_id":10})
        with self.assertRaises(ValueError): scope_fields({"attachment_keys":"PDF"})


if __name__ == "__main__": unittest.main()
