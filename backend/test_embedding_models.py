import json
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

import numpy as np

from engine import Engine
from embedding_models import EmbeddingManager, MODELS, encode_texts, input_text, load_model, custom_config, compatibility_from_metadata, model_compatibility


class EmbeddingTest(unittest.TestCase):
    def seeded(self, path, count=5):
        engine = Engine(path)
        with engine._connect() as db:
            for lib in (7, 8):
                db.execute("INSERT INTO documents(library_id,item_key,attachment_key,collection_ids,title,creators,year,zotero_uri,pdf_path,file_mtime,file_size) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (lib, "P", "PDF", "[]", "Study", "", "", "", "missing.pdf", 1, 1))
                db.executemany("INSERT INTO chunks(library_id,attachment_key,page,ordinal,text,embedding,embedding_blob) VALUES (?,?,?,?,?,?,?)",
                               [(lib, "PDF", 1, i, f"Passage {i} about overfitting.", "[1,0]", np.array([1, 0], dtype="<f4").tobytes()) for i in range(count)])
            db.execute("INSERT INTO saved_quotes(library_id,item_key,attachment_key,page,quote,title,creators,year,zotero_uri,note) VALUES (7,'P','PDF',1,'Quote','Study','','','','Keep this note')")
        return engine

    def wait(self, manager):
        deadline = time.monotonic() + 5
        while manager.status()["job"]["state"] in {"loading", "rebuilding"}:
            if time.monotonic() > deadline:
                self.fail("Rebuild did not finish")
            time.sleep(.01)
        return manager.status()["job"]

    def test_confirmation_and_atomic_switch_all_libraries_and_restart(self):
        class NewModel:
            def encode(self, texts, **_):
                self.texts = texts
                return np.tile([0., .6, .8], (len(texts), 1))
        with tempfile.TemporaryDirectory() as folder:
            engine = self.seeded(Path(folder) / "index.sqlite")
            model = NewModel()
            manager = EmbeddingManager(engine, lambda _: model)
            target = "sentence-transformers/all-MiniLM-L6-v2"
            with self.assertRaises(ValueError): manager.start({"model": target})
            manager.start({"model": target, "confirmed": True})
            job = self.wait(manager)
            self.assertEqual(job["state"], "complete")
            self.assertEqual(job["completed"], 10)
            self.assertTrue(all(not text.startswith("passage:") for text in model.texts))
            with engine._connect() as db:
                self.assertEqual({len(row[0]) for row in db.execute("SELECT embedding_blob FROM chunks")}, {12})
                for row in db.execute("SELECT topic_embedding FROM documents"):
                    self.assertEqual(len(json.loads(row[0])), 3)
                self.assertEqual(db.execute("SELECT note FROM saved_quotes").fetchone()[0], "Keep this note")
            self.assertEqual(Engine(engine.db_path).model_name, target)
            self.assertFalse(engine.rebuilding)

    def test_failed_later_batch_preserves_every_old_vector_and_model(self):
        class FailingModel:
            calls = 0
            def encode(self, texts, **_):
                self.calls += 1
                if self.calls > 1: raise RuntimeError("simulated model failure")
                return np.tile([0., 1., 0.], (len(texts), 1))
        with tempfile.TemporaryDirectory() as folder:
            engine = self.seeded(Path(folder) / "index.sqlite", 80)
            original = engine.model_name
            manager = EmbeddingManager(engine, lambda _: FailingModel())
            manager.start({"model":"intfloat/multilingual-e5-base", "confirmed":True})
            self.assertEqual(self.wait(manager)["state"], "failed")
            with engine._connect() as db:
                self.assertEqual({len(row[0]) for row in db.execute("SELECT embedding_blob FROM chunks")}, {8})
            self.assertEqual(Engine(engine.db_path).model_name, original)
            self.assertFalse(engine.rebuilding)

    def test_e5_prefixes_are_model_specific(self):
        self.assertEqual(input_text("intfloat/multilingual-e5-base", "Text", "query"), "query: Text")
        self.assertEqual(input_text("sentence-transformers/all-MiniLM-L6-v2", "Text", "query"), "Text")

    def test_every_catalog_model_uses_the_publishers_retrieval_format(self):
        expected = {
            "intfloat/multilingual-e5-small": ("query: Text", "passage: Text"),
            "intfloat/multilingual-e5-base": ("query: Text", "passage: Text"),
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": ("Text", "Text"),
            "sentence-transformers/all-MiniLM-L6-v2": ("Text", "Text"),
            "mixedbread-ai/deepset-mxbai-embed-de-large-v1": ("query: Text", "passage: Text"),
            "BAAI/bge-m3": ("Text", "Text"),
            "Qwen/Qwen3-Embedding-0.6B": ("Instruct: Given a search query, retrieve relevant passages from research papers that answer the query\nQuery:Text", "Text"),
            "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: Text", "Text"),
            "sentence-transformers/multi-qa-MiniLM-L6-cos-v1": ("Text", "Text"),
        }
        self.assertEqual({entry["id"] for entry in MODELS}, set(expected))
        for model in MODELS:
            with self.subTest(model=model["id"]):
                query, passage = expected[model["id"]]
                self.assertEqual(input_text(model["id"], "Text", "query"), query)
                self.assertEqual(input_text(model["id"], "Text", "passage"), passage)
                self.assertEqual(model["url"], "https://huggingface.co/" + model["id"])
                self.assertGreater(model["dimensions"], 0)

    def test_new_encoders_normalize_vectors_and_reduce_large_model_batches(self):
        for name, batch in (("Qwen/Qwen3-Embedding-0.6B", 4), ("BAAI/bge-m3", 8),
                            ("mixedbread-ai/deepset-mxbai-embed-de-large-v1", 8),
                            ("BAAI/bge-small-en-v1.5", 32)):
            embedder = Mock()
            encode_texts(embedder, name, ["Text"], "query")
            embedder.encode.assert_called_once_with([input_text(name, "Text", "query")],
                normalize_embeddings=True, prompt="", batch_size=batch)
        with self.assertRaises(ValueError): input_text("BAAI/bge-m3", "Text", "invalid")

    def test_loader_prefers_cache_and_never_enables_repository_code(self):
        constructor = Mock(side_effect=[OSError("not cached"), "downloaded model"])
        with patch.dict(sys.modules, {"sentence_transformers":SimpleNamespace(SentenceTransformer=constructor)}):
            self.assertEqual(load_model("Qwen/Qwen3-Embedding-0.6B"), "downloaded model")
        self.assertEqual([call.kwargs for call in constructor.call_args_list], [
            {"local_files_only":True, "trust_remote_code":False},
            {"local_files_only":False, "trust_remote_code":False}])

    def test_rebuild_new_german_model_uses_passage_prefix_and_eight_item_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.seeded(Path(folder) / "index.sqlite")
            embedder = Mock()
            embedder.encode.side_effect = lambda texts, **_: np.tile([0., .6, .8], (len(texts), 1))
            manager = EmbeddingManager(engine, lambda _: embedder)
            name = "mixedbread-ai/deepset-mxbai-embed-de-large-v1"
            manager.start({"model":name, "confirmed":True})
            self.assertEqual(self.wait(manager)["state"], "complete")
            args, kwargs = embedder.encode.call_args
            self.assertTrue(all(text.startswith("passage: ") for text in args[0]))
            self.assertEqual(kwargs["batch_size"], 8)
            self.assertEqual(engine.model_name, name)

    def test_custom_hub_ids_profiles_and_invalid_paths(self):
        config = custom_config({"id":"https://huggingface.co/acme/text-encoder/", "input_format":"custom",
                                "query_prefix":"Question: \n", "passage_prefix":"Document: "})
        self.assertEqual(config["id"], "acme/text-encoder")
        self.assertEqual(input_text(config["id"], "Text", "query", config), "Question: \nText")
        self.assertEqual(input_text(config["id"], "Text", "passage", config), "Document: Text")
        for name in ("../weights", "C:/models", "https://example.org/owner/model", "https://huggingface.co/a/b?token=secret", "a/b/tree/main", "a/../../b"):
            with self.subTest(name=name), self.assertRaises(ValueError): custom_config({"id":name})
        for extra in ({"batch_size":0}, {"batch_size":65}, {"input_format":"invalid"}, {"revision":"../main"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError): custom_config({"id":"a/b", **extra})

    def test_automatic_profile_uses_repository_query_and_document_routes(self):
        model = Mock()
        config = custom_config({"id":"acme/router", "batch_size":4})
        encode_texts(model, config["id"], ["Question"], "query", config)
        encode_texts(model, config["id"], ["Passage"], "passage", config)
        model.encode_query.assert_called_once_with(["Question"], normalize_embeddings=True, batch_size=4)
        model.encode_document.assert_called_once_with(["Passage"], normalize_embeddings=True, batch_size=4)
        model.encode.assert_not_called()

    def test_custom_configuration_persists_and_same_repository_profile_rebuilds(self):
        class Model:
            def encode(self, texts, **_): return np.tile([.6, 0., .8], (len(texts), 1))
        with tempfile.TemporaryDirectory() as folder:
            engine = self.seeded(Path(folder) / "index.sqlite")
            manager = EmbeddingManager(engine, lambda _: Model())
            custom = {"id":"acme/text", "input_format":"custom", "query_prefix":"Q: ", "passage_prefix":"D: "}
            manager.start({"custom_model":custom,"confirmed":True})
            self.assertEqual(self.wait(manager)["state"], "complete")
            first = manager.status()["active_signature"]
            restarted = Engine(engine.db_path)
            self.assertEqual(restarted.embedding_config["query_prefix"], "Q: ")
            self.assertEqual(EmbeddingManager(restarted).status()["models"][-1]["id"], "acme/text")
            # A different database must not inherit custom configuration globally.
            self.assertIsNone(Engine(Path(folder) / "other.sqlite").embedding_config)
            manager.start({"custom_model":{**custom,"query_prefix":"Search: "},"confirmed":True})
            self.assertEqual(self.wait(manager)["state"], "complete")
            self.assertNotEqual(first, manager.status()["active_signature"])
            with engine._connect() as db:
                self.assertEqual(db.execute("SELECT note FROM saved_quotes").fetchone()[0], "Keep this note")
            with patch("engine.load_model", return_value=Model()) as load:
                model = Engine(engine.db_path).embedder
            self.assertEqual(load.call_args.args[1]["query_prefix"], "Search: ")

    def test_custom_invalid_routes_preserve_active_index_and_empty_database(self):
        for empty in (False, True):
            class BadModel:
                def encode_query(self, texts, **_): return np.tile([1., 0.], (len(texts), 1))
                def encode_document(self, texts, **_): return np.tile([1., 0., 0.], (len(texts), 1))
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as folder:
                engine = Engine(Path(folder)/"index.sqlite") if empty else self.seeded(Path(folder)/"index.sqlite")
                original = engine.model_name
                manager = EmbeddingManager(engine, lambda _: BadModel())
                manager.start({"custom_model":{"id":"acme/wrong"},"confirmed":True})
                self.assertEqual(self.wait(manager)["state"], "failed")
                self.assertEqual(Engine(engine.db_path).model_name, original)
                self.assertIsNone(engine.embedding_config)
                with engine._connect() as db:
                    self.assertEqual({len(row[0]) for row in db.execute("SELECT embedding_blob FROM chunks")}, set() if empty else {8})

    def test_zero_vectors_cannot_replace_custom_index(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.seeded(Path(folder)/"index.sqlite")
            model = Mock()
            model.encode.return_value = np.zeros((1,3))
            manager = EmbeddingManager(engine, lambda _: model)
            manager.start({"custom_model":{"id":"acme/zero","input_format":"plain"},"confirmed":True})
            self.assertEqual(self.wait(manager)["state"], "failed")
            self.assertIsNone(engine.embedding_config)

    def test_custom_revision_passed_to_cache_and_download_without_repository_code(self):
        model = object()
        constructor = Mock(side_effect=[OSError("not cached"), model])
        config = custom_config({"id":"acme/text","revision":"abc123"})
        with patch.dict(sys.modules, {"sentence_transformers":SimpleNamespace(SentenceTransformer=constructor)}), patch("embedding_models.model_compatibility", return_value={"status":"supported"}):
            self.assertIs(load_model(config["id"], config), model)
        self.assertTrue(all(call.kwargs["revision"] == "abc123" and call.kwargs["trust_remote_code"] is False for call in constructor.call_args_list))

    def test_task_classifier_is_not_an_embedding_even_if_pooling_can_make_vectors(self):
        for head in ("BertForSequenceClassification", "BertForTokenClassification", "BertForQuestionAnswering"):
            with self.subTest(head=head):
                result = compatibility_from_metadata({"architectures":[head]}, None)
                self.assertEqual(result["status"], "incompatible")
                self.assertIn("neu berechnen", result["de"])
        self.assertEqual(compatibility_from_metadata({"architectures":["BertModel"]}, [{"type":"Pooling"}])["status"], "supported")
        self.assertEqual(compatibility_from_metadata({"architectures":["Qwen3ForCausalLM"]}, [{"type":"Pooling"}])["status"], "supported")
        self.assertEqual(compatibility_from_metadata({"architectures":["BertModel"]}, None)["status"], "unverified")

    def test_classifier_rejected_before_loading_weights_and_index_preserved(self):
        incompatible = compatibility_from_metadata({"architectures":["BertForSequenceClassification"]}, None)
        constructor = Mock()
        with tempfile.TemporaryDirectory() as folder:
            engine = self.seeded(Path(folder) / "index.sqlite")
            original = engine.model_name
            with patch("embedding_models.model_compatibility", return_value=incompatible), patch.dict(sys.modules, {"sentence_transformers":SimpleNamespace(SentenceTransformer=constructor)}):
                manager = EmbeddingManager(engine)
                manager.start({"confirmed":True,"custom_model":{"id":"ProsusAI/finbert"}})
                self.assertEqual(self.wait(manager)["state"], "failed")
                constructor.assert_not_called()
                self.assertEqual(engine.model_name, original)
                with engine._connect() as db:
                    self.assertEqual({len(row[0]) for row in db.execute("SELECT embedding_blob FROM chunks")}, {8})
                    self.assertEqual(db.execute("SELECT note FROM saved_quotes").fetchone()[0], "Keep this note")

    def test_cached_metadata_checks_pinned_revision_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            config.write_text(json.dumps({"architectures":["BertForSequenceClassification"]}))
            with patch("huggingface_hub.try_to_load_from_cache", side_effect=[str(config), None]) as cache, patch("huggingface_hub.hf_hub_download") as download:
                self.assertEqual(model_compatibility("ProsusAI/finbert", {"revision":"abc123"})["status"], "incompatible")
                self.assertTrue(all(call.kwargs["revision"] == "abc123" for call in cache.call_args_list))
                download.assert_not_called()


if __name__ == "__main__": unittest.main()
