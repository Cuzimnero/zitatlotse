import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from document_relevance import classify_documents, document_relevance
from engine import Engine


class DocumentRelevanceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.engine = Engine(Path(self.folder.name) / "index.sqlite", embedder=object())
        self.encoder = patch("document_relevance.encode_texts", return_value=np.array([[2., 0.]]))
        self.encoder.start()
        self.addCleanup(self.encoder.stop)

    def insert(self, library, key, vectors, legacy=False):
        with self.engine._connect() as db:
            db.execute("INSERT INTO documents (library_id,item_key,attachment_key,collection_ids,title,creators,year,zotero_uri,pdf_path,file_mtime,file_size) VALUES (?,?,?,'[]',?,'','','','',0,0)",
                       (library, "ITEM" + key, key, "Paper " + key))
            for ordinal, vector in enumerate(vectors):
                db.execute("INSERT INTO chunks (library_id,attachment_key,page,ordinal,text,embedding,embedding_blob) VALUES (?,?,?,?,?,?,?)",
                           (library, key, ordinal + 1, ordinal, "Example passage from paper " + key,
                            json.dumps(vector) if legacy else "[]",
                            None if legacy else np.asarray(vector, dtype="<f4").tobytes()))

    def test_maximum_not_average_all_chunks_and_true_cosine(self):
        self.insert(1, "A", [[1, 0], [-1, 0], [-1, 0]])
        self.insert(1, "B", [[3, 4]], legacy=True)
        self.insert(1, "C", [[-1, 0]])
        result = document_relevance(self.engine, {"library_id":1, "query":"Question"})
        self.assertEqual([d["attachment_key"] for d in result["documents"]], ["A", "B", "C"])
        self.assertEqual([d["similarity"] for d in result["documents"]], [1., .6, -1.])
        self.assertEqual(result["documents"][0]["page"], 1)
        self.assertEqual(result["total_documents"], 3)
        self.assertEqual(result["aggregation"], "maximum_chunk_cosine")

    def test_library_whitelist_empty_collection_and_unindexed_pdf(self):
        self.insert(1, "A", [[1, 0]])
        self.insert(1, "B", [[0, 1]])
        self.insert(2, "OTHER", [[1, 0]])
        result = document_relevance(self.engine, {"library_id":1,"collection_id":10,
                                   "attachment_keys":["B", "NEW"],"query":"Question"})
        self.assertEqual([d["attachment_key"] for d in result["documents"]], ["B", "NEW"])
        self.assertEqual(result["total_documents"], 2)
        self.assertEqual(result["scored_documents"], 1)
        self.assertEqual(result["documents"][1]["category"], "unindexed")
        self.assertEqual(result["categories"][-1]["percentage"], 50)
        empty = document_relevance(self.engine, {"library_id":1,"collection_id":12,
                                  "attachment_keys":[],"query":"Question"})
        self.assertEqual(empty["documents"], [])
        self.assertEqual(empty["total_documents"], 0)
        with self.assertRaises(ValueError):
            document_relevance(self.engine, {"library_id":1,"collection_id":10,"query":"Question"})

    def test_relative_bands_and_uniform_scores_keep_ties_together(self):
        values = [.1, .11, .3, .5, .7, .9, .9]
        docs = [{"attachment_key":str(i), "similarity":v} for i,v in enumerate(values)]
        result = classify_documents(docs)
        self.assertEqual(result["categories"][4]["count"], 2)
        self.assertEqual(result["categories"][0]["count"], 2)
        self.assertAlmostEqual(sum(c["percentage"] for c in result["categories"]),100,places=1)
        equal = classify_documents([{"attachment_key":str(i),"similarity":.7} for i in range(3)])
        self.assertTrue(equal["uniform"])
        self.assertTrue(all(d["category"] == "same" for d in equal["documents"]))

    def test_zero_similarity_is_lowest_not_highest(self):
        result = classify_documents([{"attachment_key":"DUMMY","similarity":0.},
                                     {"attachment_key":"RELEVANT","similarity":.9}])
        self.assertEqual([(d["attachment_key"], d["category"]) for d in result["documents"]],
                         [("RELEVANT","highest"),("DUMMY","lowest")])

    def test_query_compared_only_in_each_documents_language(self):
        for key, vector, language in [("EN",[1,0],"en"),("DE",[1,0],"de-DE"),("UNKNOWN",[0,1],"und")]:
            self.insert(1,key,[vector])
            with self.engine._connect() as db:
                db.execute("UPDATE documents SET language=? WHERE attachment_key=?",(language,key))
        with patch("document_relevance.encode_texts",return_value=np.array([[0.,1.],[1.,0.],[-1.,0.]])) as encoder:
            result=document_relevance(self.engine,{"library_id":1,"query":"Original question",
                "language_queries":{"en-US":"English query","de":"Deutsche Anfrage"}})
        scores={d["attachment_key"]:(d["similarity"],d["matched_query"]) for d in result["documents"]}
        self.assertEqual(scores["EN"],(1.,"English query"))
        self.assertEqual(scores["DE"],(-1.,"Deutsche Anfrage"),"The English query cannot inflate the German document's score")
        self.assertEqual(scores["UNKNOWN"],(1.,"Original question"))
        self.assertEqual(encoder.call_args.args[2],["Original question","English query","Deutsche Anfrage"])
        self.assertEqual(result["language_queries"],{"en":"English query","de":"Deutsche Anfrage"})

    def test_invalid_language_queries_rejected_before_embedding(self):
        for variants in ([], {"default":"Query"}, {"en":""}, {"en":123}, {"English":"Query"}, {"en":"x"*1001}):
            with self.subTest(variants=variants), self.assertRaises(ValueError):
                document_relevance(self.engine,{"library_id":1,"query":"Question","language_queries":variants})

    def test_encoder_must_return_one_vector_per_query_variant(self):
        self.insert(1,"EN",[[1,0]])
        with self.assertRaisesRegex(ValueError,"Suchvektoren"):
            document_relevance(self.engine,{"library_id":1,"query":"Question","language_queries":{"en":"English query"}})

    def test_incompatible_active_model_does_not_display_false_relevance(self):
        self.insert(1, "DUMMY", [[1,0]])
        self.insert(1, "PAPER", [[0,1]])
        compatibility = {"status":"incompatible","de":"Embedding-Modell wechseln","en":"Change embedding model"}
        with patch("document_relevance.model_compatibility", return_value=compatibility), patch("document_relevance.encode_texts") as encoder:
            result = document_relevance(self.engine, {"library_id":1,"query":"Knowledge distillation"})
        encoder.assert_not_called()
        self.assertEqual(result["model_compatibility"], compatibility)
        self.assertEqual(result["total_documents"], 2)
        self.assertEqual(result["scored_documents"], 0)
        self.assertTrue(all(d["similarity"] is None for d in result["documents"]))
        self.assertFalse(any(d["category"] == "highest" for d in result["documents"]))

    def test_invalid_vectors_remain_unscored(self):
        self.insert(1, "A", [[0, 0], [1, 0, 0], [float("nan"), 1]])
        result = document_relevance(self.engine, {"library_id":1,"query":"Question"})
        self.assertEqual(result["scored_documents"], 0)
        self.assertIsNone(result["documents"][0]["similarity"])

    def test_identical_text_copies_count_once_and_use_the_strongest_attachment(self):
        self.insert(1, "COPY_A", [[3,4]])
        self.insert(1, "COPY_B", [[1,0]])
        self.insert(1, "DIFFERENT", [[0,1]])
        with self.engine._connect() as db:
            db.execute("UPDATE chunks SET text='The same complete paper text.' WHERE attachment_key IN ('COPY_A','COPY_B')")
            db.execute("UPDATE documents SET title='Same title' WHERE library_id=1")
        result = document_relevance(self.engine, {"library_id":1,"query":"Question"})
        self.assertEqual(result["total_documents"], 2)
        self.assertEqual(result["total_attachments"], 3)
        self.assertEqual(result["duplicate_attachments"], 1)
        self.assertEqual(sum(category["count"] for category in result["categories"]), 2)
        group = result["documents"][0]
        self.assertEqual(group["attachment_key"], "COPY_B")
        self.assertEqual(group["attachment_keys"], ["COPY_A","COPY_B"])
        self.assertEqual(group["duplicate_count"], 1)
        self.assertEqual(group["similarity"], 1)
        # Same-title, different-content documents remain separate.
        self.assertEqual(result["documents"][1]["attachment_key"], "DIFFERENT")

    def test_copy_groups_obey_library_collection_scope_and_keep_unknown_documents_separate(self):
        for library,key in [(1,"A"),(1,"B"),(2,"OTHER")]: self.insert(library,key,[[1,0]])
        with self.engine._connect() as db: db.execute("UPDATE chunks SET text='Identical text'")
        scoped = document_relevance(self.engine, {"library_id":1,"query":"Question","attachment_keys":["B","NEW1","NEW2"]})
        self.assertEqual(scoped["total_documents"], 3)
        self.assertEqual(scoped["duplicate_attachments"], 0)
        self.assertEqual(scoped["documents"][0]["attachment_keys"], ["B"])
        self.assertTrue(all(doc["library_id"] == 1 for doc in scoped["documents"]))
        all_in_library = document_relevance(self.engine, {"library_id":1,"query":"Question"})
        self.assertEqual(all_in_library["total_documents"], 1)
        self.assertEqual(all_in_library["documents"][0]["attachment_keys"], ["A","B"])

    def test_fingerprints_cached_across_queries_and_reindexing_resets_identity(self):
        self.insert(1,"A",[[1,0]])
        document_relevance(self.engine, {"library_id":1,"query":"Question"})
        with self.engine._connect() as db:
            old = db.execute("SELECT content_fingerprint FROM documents").fetchone()[0]
        self.assertTrue(old)
        with patch("document_relevance.hashlib.sha256") as hash_text:
            document_relevance(self.engine, {"library_id":1,"query":"Another question"})
            hash_text.assert_not_called()
        # Exercise the real PDF indexing path, including its UPDATE on conflict.
        import pymupdf
        path = Path(self.folder.name) / "changed.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((30,30), "A revised academic paper discusses new experimental results and different conclusions.")
            pdf.save(path)
        class Encoder:
            def encode(self, texts, **_): return np.tile([1.,0.], (len(texts),1))
        with patch.object(self.engine, "_embedder", Encoder()):
            indexed = self.engine.index_pdf({"library_id":1,"item_key":"ITEMA","attachment_key":"A",
                                           "title":"Changed","language":"en","pdf_path":str(path)})
        self.assertEqual(indexed["status"], "indexed")
        with self.engine._connect() as db:
            self.assertEqual(db.execute("SELECT content_fingerprint FROM documents").fetchone()[0], "")
        document_relevance(self.engine, {"library_id":1,"query":"Question"})
        with self.engine._connect() as db:
            self.assertNotEqual(db.execute("SELECT content_fingerprint FROM documents").fetchone()[0], old)


if __name__ == "__main__":
    unittest.main()
