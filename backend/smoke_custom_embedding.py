"""Download a real custom encoder and rebuild an isolated synthetic test index.

No personal PDF, API key or live database is used or changed.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--cache", type=Path, required=True)
args = parser.parse_args()
os.environ["HF_HOME"] = str(args.cache)

import numpy as np
from engine import Engine
from embedding_models import EmbeddingManager, encode_texts
from document_relevance import document_relevance

model_id = "sentence-transformers/paraphrase-MiniLM-L3-v2"
started = time.monotonic()
with tempfile.TemporaryDirectory(prefix="zitatlotse-custom-model-") as folder:
    engine = Engine(Path(folder)/"index.sqlite")
    with engine._connect() as db:
        for library, key, title, text in [
            (7,"VISION","Vision paper","The teacher parameters are updated by an exponential moving average of the student parameters."),
            (7,"DISTILL","Distillation paper","Knowledge distillation trains a student with the soft probability targets produced by a teacher."),
            (7,"GARDEN","Gardening paper","Tomato plants require regular watering and nutrient-rich soil to produce fruit."),
            (8,"OTHER","Other library","The teacher parameters are updated by an exponential moving average of the student parameters.")]:
            db.execute("INSERT INTO documents(library_id,item_key,attachment_key,collection_ids,title,creators,year,zotero_uri,pdf_path,file_mtime,file_size) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (library,key,key,"[]",title,"","","","synthetic.pdf",1,1))
            db.execute("INSERT INTO chunks(library_id,attachment_key,page,ordinal,text,embedding,embedding_blob) VALUES (?,?,1,0,?,'[]',?)",
                       (library,key,text,np.array([1.,0.],dtype="<f4").tobytes()))
        db.execute("INSERT INTO saved_quotes(library_id,item_key,attachment_key,page,quote,title,creators,year,zotero_uri,note) VALUES (7,'VISION','VISION',1,'Saved quotation','Vision paper','','','','Keep my note')")
    manager = EmbeddingManager(engine)
    manager.start({"confirmed":True,"custom_model":{"id":model_id,"input_format":"auto","batch_size":8}})
    deadline = time.monotonic() + 300
    while (job := manager.status()["job"])["state"] in {"loading","rebuilding"}:
        if time.monotonic() > deadline:
            raise TimeoutError("Custom model test did not finish within 5 minutes")
        time.sleep(.2)
    if job["state"] != "complete":
        raise RuntimeError(job.get("error", "Rebuild failed"))
    query = "How are teacher parameters updated from the student?"
    overview = document_relevance(engine, {"library_id":7,"query":query})
    assert overview["total_documents"] == 3
    assert overview["documents"][0]["attachment_key"] == "VISION"
    assert all(doc["library_id"] == 7 for doc in overview["documents"])
    restricted = document_relevance(engine, {"library_id":7,"query":query,"attachment_keys":["DISTILL"]})
    assert [doc["attachment_key"] for doc in restricted["documents"]] == ["DISTILL"]
    assert document_relevance(engine, {"library_id":7,"query":query,"attachment_keys":[]})["total_documents"] == 0
    before = encode_texts(engine.embedder, model_id, [query], "query", engine.embedding_config)
    restarted = Engine(engine.db_path)
    after = encode_texts(restarted.embedder, model_id, [query], "query", restarted.embedding_config)
    assert np.allclose(before, after, atol=1e-6)
    assert restarted.model_name == model_id and restarted.embedding_config["input_format"] == "auto"
    with restarted._connect() as db:
        assert {len(row[0]) for row in db.execute("SELECT embedding_blob FROM chunks")} == {384*4}
        assert db.execute("SELECT note FROM saved_quotes").fetchone()[0] == "Keep my note"
    report = {"passed":True,"model":model_id,"config":restarted.embedding_config,"dimensions":384,
              "chunks_rebuilt":job["completed"],"libraries_rebuilt":2,"query":query,
              "top_document":overview["documents"][0]["attachment_key"],
              "scores":{doc["attachment_key"]:doc["similarity"] for doc in overview["documents"]},
              "restart_vectors_equal":True,"saved_note_preserved":True,"collection_and_empty_scope_passed":True,
              "seconds":round(time.monotonic()-started,1)}
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
