import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agent_search as agent


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def tool(name, arguments):
    return {"calls": [{"id": "call-1", "name": name, "arguments": arguments}]}


def hit(number, library=7):
    return {"id": number, "library_id": library, "attachment_key": "PDF", "item_key": "PARENT",
            "page": number, "title": "Study", "quote": f"Original evidence number {number}."}


class AgentTest(unittest.TestCase):
    def test_grouped_citations_finish_without_rejecting_valid_sources(self):
        engine = SimpleNamespace(search_page=Mock(return_value={"results":[hit(1),hit(2)]}))
        with patch.object(agent,"call_agent_model",side_effect=[
                tool("search_library",{"query":"evidence","language":"en"}),
                tool("finish_search",{"answer":"Findings [1, 2].","has_evidence":True,"selected_refs":[1,2]})]) as model:
            result=agent.agentic_search({"library_id":7,"message":"question"},engine,
                {"provider":"openai"},lambda _:"key",{"en":1})
        self.assertEqual(len(result["selected_results"]),2)
        self.assertEqual(model.call_count,2)
        self.assertEqual(agent.citation_refs("[1–3] and [5; 7]"),{1,2,3,5,7})
        with self.assertRaises(ValueError):agent.citation_refs("[1-99999999]")

    def test_numeric_source_after_eighth_hit_is_exposed_and_can_be_selected(self):
        hits = [hit(n) for n in range(1, 13)]
        hits[10].update(quote="MiVOLO achieved a MAE of 6.66 with body-only images.",
                        context="Table 3 compares face, body and face-and-body inputs.")
        engine = SimpleNamespace(search_page=Mock(return_value={"results":hits}))
        def model(messages, *_args, **_kwargs):
            if len(messages) == 1: return tool("search_library", {"query":"MiVOLO body-only MAE","language":"en"})
            sources = json.loads(messages[-1]["output"])["passages"]
            self.assertEqual(len(sources), 12)
            self.assertIn("6.66", sources[10]["quote"])
            self.assertIn("Table 3", sources[10]["context"])
            return tool("finish_search", {"answer":"Body-only MAE is 6.66 [11].", "has_evidence":True,"selected_refs":[11]})
        with patch.object(agent, "call_agent_model", side_effect=model):
            result = agent.agentic_search({"library_id":7,"message":"MiVOLO body error"}, engine,
                {"provider":"openai"}, lambda _:"key", {"en":1})
        self.assertIn("6.66", result["selected_results"][0]["quote"])
        self.assertEqual(engine.search_page.call_args.args[0]["retrieval_mode"], "ai")

    def setUp(self):
        self.settings = {"provider": "openai", "model": "test-model", "agentic_max_steps": 3}
        self.data = {"library_id": 7, "message": "Find evidence and counter-evidence", "ui_lang": "de"}

    def test_results_drive_next_query_and_refs_survive_merge_and_pagination(self):
        engine = SimpleNamespace(search_page=Mock(side_effect=[
            {"results": [hit(n) for n in range(1, 21)]},
            {"results": [hit(n) for n in range(21, 41)]}]))
        turns = []

        def model(messages, *args, **kwargs):
            turns.append(json.loads(json.dumps(messages)))
            if len(turns) == 1:
                return tool("search_library", {"query": "overfitting evidence", "language": "en"})
            if len(turns) == 2:
                self.assertIn("Original evidence number 1", messages[-1]["output"])
                return tool("search_library", {"query": "overfitting counter-evidence", "language": "en"})
            return tool("finish_search", {"answer": "Beleg [1] und Gegenbeleg [21].", "has_evidence": True,
                                          "selected_refs": [1, 21]})

        with patch.object(agent, "call_agent_model", side_effect=model):
            result = agent.agentic_search(self.data, engine, self.settings, lambda _: "key", {"en": 2})
        self.assertEqual(engine.search_page.call_count, 2)
        self.assertEqual([call.args[0]["library_id"] for call in engine.search_page.call_args_list], [7, 7])
        self.assertEqual(result["total_results"], 40)
        self.assertEqual(len(result["selected_results"]), 2)
        self.assertEqual(result["results"][0]["reference_number"], 1)
        self.assertEqual(result["results"][1]["reference_number"], 21)
        self.assertTrue(result["results"][1]["recommended"])
        self.assertEqual(len(result["agent_steps"]), 2)
        page = agent.result_store.page({"library_id": 7, "search_id": result["search_id"], "offset": 20})
        self.assertEqual(len(page["results"]), 20)
        self.assertFalse(page["has_more"])
        with self.assertRaisesRegex(ValueError, "abgelaufen"):
            agent.result_store.page({"library_id": 8, "search_id": result["search_id"]})

    def test_limit_and_duplicate_queries_do_not_run_extra_searches(self):
        engine = SimpleNamespace(search_page=Mock(return_value={"results": [hit(1)]}))
        self.settings["agentic_max_steps"] = 1
        with patch.object(agent, "call_agent_model", side_effect=[
            tool("search_library", {"query": "evidence", "language": "en"}),
            tool("search_library", {"query": "other query", "language": "en"}),
            tool("finish_search", {"answer": "Evidence [1].", "has_evidence": True, "selected_refs": [1]})]) as model:
            result = agent.agentic_search(self.data, engine, self.settings, lambda _: "key", {"en": 1})
        self.assertEqual(engine.search_page.call_count, 1)
        self.assertTrue(model.call_args_list[1].kwargs["finish_only"])
        self.assertEqual(len(result["agent_steps"]), 1)

    def test_model_cannot_switch_library_or_execute_arbitrary_functions(self):
        engine = SimpleNamespace(search_page=Mock(return_value={"results": [hit(1)]}))
        with patch.object(agent, "call_agent_model", side_effect=[
            tool("search_library", {"query": "evidence", "language": "en", "library_id": 8}),
            tool("run_shell", {"command": "anything"}),
            tool("search_library", {"query": "evidence", "language": "en"}),
            tool("finish_search", {"answer": "Evidence [1].", "has_evidence": True, "selected_refs": [1]})]):
            agent.agentic_search(self.data, engine, self.settings, lambda _: "key", {"en": 1})
        self.assertEqual(engine.search_page.call_count, 1)
        self.assertEqual(engine.search_page.call_args.args[0]["library_id"], 7)

    def test_unknown_references_are_rejected_and_no_evidence_returns_no_quotes(self):
        engine = SimpleNamespace(search_page=Mock(return_value={"results": [hit(1)]}))
        with patch.object(agent, "call_agent_model", side_effect=[
            tool("search_library", {"query": "evidence", "language": "en"}),
            tool("finish_search", {"answer": "Invented [99].", "has_evidence": True, "selected_refs": [99]}),
            tool("finish_search", {"answer": "", "has_evidence": False, "selected_refs": []})]):
            result = agent.agentic_search(self.data, engine, self.settings, lambda _: "key", {"en": 1})
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total_results"], 0)
        self.assertNotIn("Invented", result["reply"])

    def test_unsupported_model_produces_no_fabricated_search(self):
        engine = SimpleNamespace(search_page=Mock())
        with patch.object(agent, "call_agent_model", return_value={"calls": []}):
            with self.assertRaisesRegex(agent.AgentSearchError, "Funktionsaufruf"):
                agent.agentic_search(self.data, engine, self.settings, lambda _: "key", {"en": 1})
        engine.search_page.assert_not_called()

    def test_native_protocols_return_matching_tool_results_and_preserve_reasoning(self):
        for provider in ("openai", "anthropic", "deepseek", "ollama"):
            with self.subTest(provider=provider):
                settings = {"provider": provider, "model": "test", "ollama_url": "http://127.0.0.1:11434"}
                fn = {"name": "search_library", "arguments": '{"query":"evidence","language":"en"}'}
                if provider == "openai":
                    answer = {"output": [{"type": "reasoning", "id": "reasoning-1", "summary": []},
                                         {"type": "function_call", "call_id": "call-native", **fn}]}
                elif provider == "anthropic":
                    answer = {"content": [{"type": "thinking", "thinking": "private", "signature": "signed"},
                                          {"type": "tool_use", "id": "call-native", "name": fn["name"],
                                           "input": json.loads(fn["arguments"])}]}
                else:
                    message = {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "call-native", "type": "function", "function": fn}],
                        "thinking" if provider == "ollama" else "reasoning_content": "private"}
                    answer = {"message": message} if provider == "ollama" else {"choices": [{"message": message}]}
                messages = [{"role": "user", "content": "question"}]
                with patch.object(agent.urllib.request, "urlopen", return_value=Response(json.dumps(answer).encode())) as send:
                    turn = agent.call_agent_model(messages, "instructions", settings, lambda _: "dummy-key")
                    payload = json.loads(send.call_args.args[0].data)
                self.assertEqual(turn["calls"][0]["id"], "call-native")
                self.assertTrue(payload["tools"])
                self.assertNotIn("dummy-key", json.dumps(payload))
                agent.append_tool_results(messages, provider, [(turn["calls"][0], {"passages": []})])
                if provider == "openai":
                    self.assertEqual(messages[-1]["call_id"], "call-native")
                    self.assertFalse(payload["store"])
                    self.assertEqual(messages[-3]["type"], "reasoning")
                elif provider == "anthropic":
                    self.assertEqual(messages[-1]["content"][0]["tool_use_id"], "call-native")
                    self.assertEqual(messages[-2]["content"][0]["signature"], "signed")
                elif provider == "deepseek":
                    self.assertEqual(messages[-1]["tool_call_id"], "call-native")
                    self.assertEqual(messages[-2]["reasoning_content"], "private")
                else:
                    self.assertEqual(messages[-1]["tool_name"], "search_library")
                    self.assertEqual(messages[-2]["thinking"], "private")

    def test_deepseek_thinking_finish_replays_reasoning_without_forced_tool_choice(self):
        settings = {"provider":"deepseek", "model":"deepseek-v4-pro"}
        native = {"role":"assistant", "content":None, "reasoning_content":"private reasoning",
                  "tool_calls":[{"id":"search-1", "type":"function", "function":
                      {"name":"search_library", "arguments":'{"query":"patch quality","language":"en"}'}}]}
        messages = [{"role":"user", "content":"Find evidence"}]
        with patch.object(agent.urllib.request, "urlopen", return_value=Response(json.dumps(
                {"choices":[{"message":native, "finish_reason":"tool_calls"}]}).encode())):
            turn = agent.call_agent_model(messages, "instructions", settings, lambda _:"key", search_only=True)
        self.assertEqual(messages[-1]["content"], "")
        agent.append_tool_results(messages, "deepseek", [(turn["calls"][0], {"passages":[]})])
        with patch.object(agent.urllib.request, "urlopen", return_value=Response(json.dumps(
                {"choices":[{"message":{"role":"assistant", "content":""}, "finish_reason":"stop"}]}).encode())) as send:
            agent.call_agent_model(messages, "instructions", settings, lambda _:"key", finish_only=True)
        payload = json.loads(send.call_args.args[0].data)
        self.assertNotIn("tool_choice", payload, "DeepSeek thinking rejects named tool_choice with HTTP 400")
        self.assertEqual([t["function"]["name"] for t in payload["tools"]], ["finish_search"])
        self.assertEqual(payload["messages"][2]["reasoning_content"], "private reasoning")
        self.assertEqual(payload["messages"][3]["tool_call_id"], "search-1")
        self.assertEqual(payload["thinking"], {"type":"enabled"})
        self.assertGreater(payload["max_tokens"], 2048)

    def test_deepseek_http_400_is_not_reported_as_missing_tool_support(self):
        error = agent.urllib.error.HTTPError("https://api.deepseek.com", 400, "bad format", {}, None)
        with patch.object(agent.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(agent.AgentSearchError, "Anfrageformat") as caught:
                agent.call_agent_model([], "instructions", {"provider":"deepseek", "model":"deepseek-v4-pro"}, lambda _:"secret")
        self.assertNotIn("unterstützt", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

    def test_truncated_tool_response_reports_token_limit_without_fabricating_results(self):
        engine = SimpleNamespace(search_page=Mock())
        with patch.object(agent, "call_agent_model", return_value={"calls":[], "finish_reason":"length"}):
            with self.assertRaisesRegex(agent.AgentSearchError, "Tokenlimit"):
                agent.agentic_search(self.data, engine, self.settings, lambda _:"key", {"en":1})
        engine.search_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
