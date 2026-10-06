import io
import json
import unittest
from unittest.mock import patch

import server


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class ProviderTest(unittest.TestCase):
    def test_failed_ai_review_never_displays_unreviewed_broad_candidates(self):
        weak = {"id":1,"title":"Study","page":1,"quote":"Only loosely related material."}
        pages = [{"results":[weak],"search_id":"broad","next_offset":1,"has_more":False,"total_chunks":1},
                 {"results":[],"search_id":"strict","next_offset":0,"has_more":False,"total_chunks":1,"total_results":0}]
        with patch.object(server.engine,"languages",return_value={"en":1}), \
                patch.object(server.engine,"search_page",side_effect=pages) as search, \
                patch.object(server,"get_settings",return_value={"provider":"ollama","agentic_enabled":False}), \
                patch.object(server,"call_llm",side_effect=ValueError("Provider unavailable")):
            result = server.chat_search({"library_id":1,"message":"Which clinical trials support this claim?"})
        self.assertEqual(result["results"],[])
        self.assertEqual(result["total_results"],0)
        self.assertEqual([c.args[0]["retrieval_mode"] for c in search.call_args_list],["ai","direct"])

    def test_agent_toggle_and_unsupported_model_fallback(self):
        hits = [{"id":1, "title":"Study", "page":1, "quote":"Evidence of overfitting."}]
        for enabled in (False, True):
            with self.subTest(enabled=enabled), \
                    patch.object(server.engine, "languages", return_value={"en":1}), \
                    patch.object(server.engine, "search_page", return_value={"results":hits, "search_id":"session",
                                 "next_offset":1, "has_more":False, "total_chunks":1, "total_results":1}), \
                    patch.object(server, "get_settings", return_value={"provider":"ollama", "agentic_enabled":enabled}), \
                    patch.object(server, "agentic_search", side_effect=ValueError("No tool support")) as agent, \
                    patch.object(server, "call_llm", side_effect=['{"queries":{"en":"overfitting evidence"}}',
                                 '{"answer":"Evidence [1].","has_evidence":true,"selected_refs":[1]}']):
                result = server.chat_search({"library_id":1, "message":"Suche Belege für Overfitting", "ui_lang":"de"})
            self.assertEqual(agent.call_count, int(enabled))
            self.assertTrue(result["results"][0]["recommended"])
            self.assertEqual(result["total_results"], 1)
            if enabled: self.assertIn("Mehrstufige Suche nicht verfügbar", result["warning"])

    def test_chat_translates_german_request_for_english_documents(self):
        plan = '{"queries":{"en":"empirical evidence of overfitting"},"reply":"Ich suche auf Englisch."}'
        review = '{"answer":"Die Studie beschreibt Überanpassung [1].","has_evidence":true,"selected_refs":[1]}'
        hits = [{"id": 11, "title": "Studie A", "page": 3, "quote": "Evidence of overfitting."},
                {"id": 12, "title": "Studie B", "page": 4, "quote": "Unrelated passage."}]
        with patch.object(server.engine, "languages", return_value={"en": 2}), \
                patch.object(server.engine, "search_page", return_value={
                    "results": hits, "search_id": "session-1", "next_offset": 2,
                    "has_more": True, "total_chunks": 12}) as search, \
                patch.object(server, "get_settings", return_value={"provider": "ollama", "model": "test"}), \
                patch.object(server, "call_llm", side_effect=[plan, review]) as llm:
            result = server.chat_search({"library_id": 1, "message": "Suche Beweise für Overfitting",
                                         "ui_lang": "de", "history": []})
        self.assertTrue(result["used_ai"])
        self.assertTrue(result["reviewed"])
        self.assertEqual(result["queries"]["en"], "empirical evidence of overfitting")
        self.assertIn("Ich suche auf Englisch.", result["reply"])
        self.assertIn("Überanpassung [1]", result["reply"])
        self.assertEqual(search.call_args.args[0]["queries"]["en"], "empirical evidence of overfitting")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["reference_number"], 1)
        self.assertTrue(result["results"][0]["recommended"])
        self.assertFalse(result["results"][1]["recommended"])
        self.assertEqual(result["results"][0]["quote"], "Evidence of overfitting.")
        self.assertEqual(result["search_id"], "session-1")
        self.assertTrue(result["has_more"])
        self.assertEqual(llm.call_count, 2)

    def test_review_can_reject_all_weak_results(self):
        answer = '{"answer":"","has_evidence":false,"selected_refs":[]}'
        hits = [{"id": 1, "title": "Test", "page": 1, "quote": "Weak match."}]
        with patch.object(server, "call_llm", return_value=answer):
            summary, chosen = server.review_chat_results("Beweise?", hits, {"provider": "ollama"}, "de")
        self.assertEqual(chosen, [])
        self.assertIn("keinen hinreichend direkten Beleg", summary)

    def test_chat_hides_quotes_when_review_finds_no_evidence(self):
        hits = [{"id": 1, "title": "Test", "page": 1, "quote": "Unrelated passage."}]
        with patch.object(server.engine, "languages", return_value={"en": 1}), \
                patch.object(server.engine, "search_page", return_value={
                    "results": hits, "search_id": "session-3", "next_offset": 1,
                    "has_more": True, "total_chunks": 50}), \
                patch.object(server, "get_settings", return_value={"provider": "ollama"}), \
                patch.object(server, "call_llm", side_effect=[
                    '{"queries":{"en":"strawberry cake"},"reply":""}',
                    '{"answer":"","has_evidence":false,"selected_refs":[]}']):
            result = server.chat_search({"library_id": 1, "message": "Erdbeerkuchen", "ui_lang": "de"})
        self.assertEqual(result["results"], [])
        self.assertFalse(result["has_more"])
        self.assertEqual(result["search_id"], "")

    def test_short_keyword_search_keeps_exact_hits_without_llm_filter(self):
        hits = [{"id": 1, "title": "Study", "page": 2,
                 "quote": "The MAE was measured on the validation set."}]
        with patch.object(server.engine, "languages", return_value={"en": 1}), \
                patch.object(server.engine, "search_page", return_value={
                    "results": hits, "search_id": "session-mae", "next_offset": 1,
                    "has_more": True, "total_chunks": 50}), \
                patch.object(server, "get_settings", return_value={"provider": "ollama"}), \
                patch.object(server, "call_llm") as llm:
            result = server.chat_search({"library_id": 1, "message": "mae", "ui_lang": "de"})
        self.assertEqual(result["results"], hits)
        self.assertTrue(result["has_more"])
        self.assertIn("Textstellen", result["reply"])
        self.assertFalse(result["reviewed"])
        llm.assert_not_called()

    def test_review_rejects_unlinked_claims(self):
        answer = '{"answer":"Ein unbelegter Satz.","has_evidence":true,"selected_refs":[1]}'
        hits = [{"id": 1, "title": "Test", "page": 1, "quote": "A source quote."}]
        with patch.object(server, "call_llm", return_value=answer):
            with self.assertRaisesRegex(ValueError, "Quellen"):
                server.review_chat_results("Frage?", hits, {"provider": "ollama"}, "de")

    def test_chat_without_provider_keeps_multilingual_query(self):
        with patch.object(server.engine, "languages", return_value={"en": 1}), \
                patch.object(server.engine, "search_page", return_value={
                    "results": [], "search_id": "session-2", "next_offset": 0,
                    "has_more": False, "total_chunks": 0}), \
                patch.object(server, "get_settings", return_value={"provider": "none"}):
            result = server.chat_search({"library_id": 1, "message": "Überanpassung", "ui_lang": "de"})
        self.assertFalse(result["used_ai"])
        self.assertEqual(result["queries"], {"default": "Überanpassung"})

    def test_anthropic_uses_messages_endpoint_and_key_header(self):
        answer = {"content": [{"type": "text", "text": '{"ids": [1]}'}]}
        with patch.object(server, "get_key", return_value="dummy-key"), \
                patch.object(server.urllib.request, "urlopen", return_value=Response(json.dumps(answer).encode())) as send:
            result = server.call_llm("test", {"provider": "anthropic", "model": "test-model"})
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.headers["X-api-key"], "dummy-key")
        self.assertEqual(result, '{"ids": [1]}')

    def test_deepseek_uses_own_endpoint(self):
        answer = {"choices": [{"message": {"content": '{"ids": []}'}}]}
        with patch.object(server, "get_key", return_value="dummy-key"), \
                patch.object(server.urllib.request, "urlopen", return_value=Response(json.dumps(answer).encode())) as send:
            server.call_llm("test", {"provider": "deepseek", "model": "deepseek-flash"})
        self.assertEqual(send.call_args.args[0].full_url,
                         "https://api.deepseek.com/chat/completions")

    def test_deepseek_errors_distinguish_key_balance_and_model(self):
        for code, expected in [(401, "API-Schlüssel"), (402, "Guthaben"),
                               (422, "Modell")]:
            with self.subTest(code=code), \
                    patch.object(server, "get_key", return_value="dummy-key"), \
                    patch.object(server.urllib.request, "urlopen", side_effect=
                                 server.urllib.error.HTTPError(
                                     "https://api.deepseek.com/chat/completions",
                                     code, "error", None, None)):
                with self.assertRaisesRegex(ValueError, expected):
                    server.call_llm("test", {"provider": "deepseek", "model": "deepseek-flash"})

    def test_ollama_model_picker_lists_installed_models(self):
        listing = {"models": [{"name": "mistral:latest"}, {"name": "gemma3:4b"}]}
        with patch.object(server.urllib.request, "urlopen",
                          return_value=Response(json.dumps(listing).encode())) as send:
            result = server.list_models({"provider": "ollama",
                                         "ollama_url": "http://127.0.0.1:11434"})
        self.assertEqual(send.call_args.args[0].full_url,
                         "http://127.0.0.1:11434/api/tags")
        self.assertEqual([entry["id"] for entry in result["models"]],
                         ["gemma3:4b", "mistral:latest"])
        self.assertEqual(result["source"], "installed")

    def test_deepseek_model_picker_uses_saved_key_without_exposing_it(self):
        listing = {"data": [{"id": "deepseek-flash", "name":"DeepSeek Flash"},
                            {"id": "deepseek-v4-pro", "name":"DeepSeek V4 Pro"}]}
        with patch.object(server, "get_key", return_value="dummy-key"), \
                patch.object(server.urllib.request, "urlopen",
                             return_value=Response(json.dumps(listing).encode())) as send:
            result = server.list_models({"provider": "deepseek"})
        self.assertEqual(send.call_args.args[0].full_url, "https://api.deepseek.com/models")
        self.assertEqual(send.call_args.args[0].headers["Authorization"], "Bearer dummy-key")
        self.assertNotIn("dummy-key", json.dumps(result))
        self.assertEqual(len(result["models"]), 2)
        self.assertEqual(result["models"][1]["label"], "DeepSeek V4 Pro (deepseek-v4-pro)")

    def test_model_picker_rejects_remote_ollama_address(self):
        with self.assertRaisesRegex(ValueError, "lokaler HTTP-Server"):
            server.list_models({"provider": "ollama", "ollama_url": "https://example.com:11434"})

    def test_cloud_model_choices_exist_without_a_key_and_do_not_make_network_requests(self):
        for provider in ("openai", "anthropic"):
            with self.subTest(provider=provider), patch.object(server,"get_key",return_value=""), patch.object(server.urllib.request,"urlopen") as send:
                listing = server.list_models({"provider":provider})
                self.assertGreaterEqual(len(listing["models"]), 3)
                self.assertEqual(listing["source"], "suggestions")
                self.assertEqual(listing["reason"], "no_key")
                send.assert_not_called()

    def test_openai_connection_and_nonagent_requests_use_current_token_parameter(self):
        response = Response(b'{"choices":[{"message":{"content":"{\\"ids\\":[]}"}}]}')
        with patch.object(server,"get_key",return_value="test-key"), patch.object(server.urllib.request,"urlopen",return_value=response) as send:
            self.assertEqual(server.call_llm("Return JSON", {"provider":"openai","model":"gpt-5-mini"}), '{"ids":[]}')
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", payload)

    def test_openai_list_filters_modalities_keeps_text_finetunes_and_uses_entered_key(self):
        ids = ["gpt-4.1-mini", "gpt-image-2", "gpt-realtime", "gpt-audio-1.5", "text-embedding-3-small",
               "o3", "ft:gpt-4.1-mini:organization:custom", "gpt-4.1-mini"]
        with patch.object(server.urllib.request,"urlopen",return_value=Response(json.dumps({"data":[{"id":x} for x in ids]}).encode())) as send:
            listing = server.list_models({"provider":"openai", "api_key":"test-only-key"})
        self.assertEqual({model["id"] for model in listing["models"]}, {"gpt-4.1-mini", "o3", "ft:gpt-4.1-mini:organization:custom"})
        self.assertEqual(listing["source"], "api")
        self.assertEqual(send.call_args.args[0].headers["Authorization"], "Bearer test-only-key")
        self.assertNotIn("test-only-key", json.dumps(listing))

    def test_anthropic_model_list_follows_all_pages_and_preserves_labels(self):
        pages = [{"data":[{"id":"claude-new","display_name":"Claude New"}],"has_more":True,"last_id":"claude-new"},
                 {"data":[{"id":"claude-other","display_name":"Claude Other"}],"has_more":False}]
        with patch.object(server,"get_key",return_value="test-only-key"), patch.object(server.urllib.request,"urlopen",side_effect=[Response(json.dumps(page).encode()) for page in pages]) as send:
            listing = server.list_models({"provider":"anthropic"})
        self.assertEqual(len(listing["models"]), 2)
        self.assertEqual(send.call_args.args[0].full_url, "https://api.anthropic.com/v1/models?after_id=claude-new&limit=1000")
        self.assertEqual(send.call_args.args[0].headers["X-api-key"], "test-only-key")
        self.assertEqual(send.call_args.args[0].headers["Anthropic-version"], "2023-06-01")
        self.assertEqual(listing["models"][0]["label"], "Claude New (claude-new)")

    def test_cloud_discovery_errors_and_empty_results_leave_labelled_suggestions(self):
        for provider in ("openai","anthropic"):
            for failure, reason in [(server.urllib.error.HTTPError("https://example.invalid",401,"bad key",None,None),"key_rejected"),
                                    (server.urllib.error.URLError("private internal error"),"unavailable"),
                                    (Response(b'{"data":[]}'),"empty")]:
                options = {"side_effect":failure} if isinstance(failure, Exception) else {"return_value":failure}
                with self.subTest(provider=provider,reason=reason), patch.object(server,"get_key",return_value="test-only-key"), patch.object(server.urllib.request,"urlopen",**options):
                    listing = server.list_models({"provider":provider})
                self.assertEqual(listing["reason"], reason)
                self.assertEqual(listing["source"], "suggestions")
                self.assertNotIn("private internal error", json.dumps(listing))

    def test_ollama_retries_transient_server_error(self):
        failure = server.urllib.error.HTTPError("http://127.0.0.1:11434/api/generate", 500,
                                                "temporary", None, None)
        answer = Response(b'{"response":"{\\"answer\\":\\"ok\\"}"}')
        with patch.object(server.urllib.request, "urlopen", side_effect=[failure, answer]) as send, \
                patch.object(server.time, "sleep"):
            result = server.call_llm("test", {"provider": "ollama", "model": "mistral",
                                               "ollama_url": "http://127.0.0.1:11434"})
        self.assertEqual(result, '{"answer":"ok"}')
        self.assertEqual(send.call_count, 2)
        self.assertEqual(json.loads(send.call_args.args[0].data)["options"]["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
