"""Offline paired timing experiment using synthetic PDFs and cached real models.

Run with --output DIR and --model-cache DIR (the Hugging Face cache root).
No provider API, real Zotero database, or private document is accessed.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ.update(HF_HOME=str(args.model_cache), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      MPLCONFIGDIR=str(args.output / "matplotlib"))
    import socket
    def offline(*_): raise RuntimeError("Network disabled in this experiment")
    socket.socket.connect = offline
    import numpy as np
    import pymupdf
    from engine import Engine
    from embedding_models import encode_texts

    engine = Engine(args.output / "synthetic.sqlite")
    texts = [f"Average validation error for experiment {i} was {i % 10 + 1} percent. "
             "Independent evaluation measured prediction accuracy using a held-out validation sample. "
             "This synthetic example is intended exclusively for a reproducible latency experiment."
             for i in range(120)]
    pdf_path = args.output / "synthetic.pdf"
    with pymupdf.open() as pdf:
        for text in texts:
            pdf.new_page().insert_textbox((40, 40, 540, 400), text, fontsize=12)
        pdf.save(pdf_path)
    before = time.perf_counter()
    vectors = np.asarray(encode_texts(engine.embedder, engine.model_name, texts, "passage"), dtype=np.float32)
    embedding_setup = time.perf_counter() - before
    center = vectors.mean(axis=0); center /= np.linalg.norm(center)
    with engine._connect() as db:
        db.execute("INSERT INTO documents (library_id,item_key,attachment_key,collection_ids,title,creators,year,"
                   "zotero_uri,pdf_path,language,topic_flags,topic_embedding,content_fingerprint,file_mtime,file_size) "
                   "VALUES (1,'ITEM','PDF','[]','Synthetic benchmark','','2026','',?,'en','[\"average\"]',?,'synthetic',0,0)",
                   (str(pdf_path), json.dumps(center.tolist())))
        for i, (text, vector) in enumerate(zip(texts, vectors)):
            db.execute("INSERT INTO chunks (library_id,attachment_key,page,ordinal,text,embedding,embedding_blob) "
                       "VALUES (1,'PDF',?,?,?,'[]',?)", (i+1, i, text, vector.astype('<f4').tobytes()))
    before = time.perf_counter()
    engine.scorer.score([texts[0]], ["Average"], batch_size=8)
    bert_setup = time.perf_counter() - before
    data = {"library_id":1, "query":"Average", "limit":20}
    engine.retrieval_cache.query_vectors(engine, ["Average"])
    # Warm the matrix once, then alternate order to reduce timing bias.
    engine.search_page({**data, "search_mode":"fast"})
    runs = []
    for iteration in range(3):
        pair = {}
        for progressive in ((False, True) if iteration % 2 == 0 else (True, False)):
            start = time.perf_counter()
            page = engine.search_page({**data, "progressive":progressive})
            first_seconds = time.perf_counter() - start
            first_scored = page["scored_chunks"]
            hits = list(page["results"])
            while page["has_more"]:
                page = engine.search_page({"library_id":1, "search_id":page["search_id"],
                                           "offset":page["next_offset"], "limit":20})
                hits.extend(page["results"])
            total_seconds = time.perf_counter() - start
            locations = {(h["page"], h["quote"]) for h in hits}
            assert len(locations) == len(hits) == 120
            assert all(h["position"].get("rects") for h in hits)
            pair["progressive" if progressive else "complete_first"] = {
                "first_page_seconds":round(first_seconds, 4), "all_pages_seconds":round(total_seconds, 4),
                "first_scored_chunks":first_scored, "locations":len(locations)}
        runs.append(pair)
    result = {"model":engine.model_name, "bert_model":"bert-base-multilingual-cased", "chunks":120,
              "private_documents":False, "cloud_calls":0, "model_downloads":False,
              "embedding_setup_seconds":round(embedding_setup, 3), "bert_setup_seconds":round(bert_setup, 3),
              "runs":runs,
              "median_first_complete":statistics.median(r["complete_first"]["first_page_seconds"] for r in runs),
              "median_first_progressive":statistics.median(r["progressive"]["first_page_seconds"] for r in runs)}
    (args.output / "timings.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__": main()
