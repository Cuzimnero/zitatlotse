"""Inspect direct retrieval locally using a disposable copy of an existing index."""
import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("db", type=Path)
parser.add_argument("--library", type=int, default=1)
parser.add_argument("queries", nargs="*", default=["Average", "average", "soft targets", "knowledge distillation",
    "DINO momentum teacher", "Warum enthalten Soft Targets mehr Informationen als die korrekten Klassenlabels?",
    "Why do soft targets contain more information than hard labels?", "MAE", "rms", "Migraine placebo clinical trial"])
args = parser.parse_args()
os.environ.setdefault("HF_HOME", str(args.db.resolve().parent / "models"))
from engine import Engine

with tempfile.TemporaryDirectory() as folder:
    snapshot = Path(folder) / "snapshot.sqlite"
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(snapshot)) as target: source.backup(target)
    engine = Engine(snapshot)
    real = engine.scorer
    scores = []
    class Trace:
        def score(self, candidates, references, **kwargs):
            value = real.score(candidates, references, **kwargs)
            scores.extend(value[2].tolist())
            return value
    engine._scorer = Trace()
    for query in args.queries:
        scores.clear()
        page = engine.search_page({"library_id":args.library, "query":query, "limit":30})
        session = engine._search_sessions[page["search_id"]]
        ranked = session["ranked"]
        total_results = page["total_results"]
        all_hits = list(page["results"])
        while page["has_more"]:
            page = engine.search_page({"library_id":args.library,"search_id":page["search_id"],"offset":page["next_offset"],"limit":30})
            all_hits.extend(page["results"])
        assert len(all_hits) == total_results
        assert all(h["library_id"] == args.library for h in all_hits)
        print(json.dumps({"query":query, "model":engine.model_name, "candidates":len(ranked),
            "cosine_range":[round(min((r[0] for r in ranked),default=0),3),round(max((r[0] for r in ranked),default=0),3)],
            "bert_range":[round(min(scores,default=0),3),round(max(scores,default=0),3)],
            "hits":total_results, "documents":len({h["attachment_key"] for h in all_hits}),
            "titles":list(dict.fromkeys(h["title"] for h in all_hits))}),flush=True)
