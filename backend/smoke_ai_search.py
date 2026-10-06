"""Real AI-search regressions against the installed local service.

Requires --live: requests can send retrieved passages to the configured provider
and incur API costs. No keys, private model reasoning or raw API responses are
recorded. The PDF index is never changed.
"""
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


CASES = [
    {"id":"mivolo_body", "question":"Wie verändert sich der Fehler der Altersschätzung, wenn MiVOLO nur den Körper verwendet?",
     "direct":"MiVOLO body-only age estimation mean absolute error face and body", "positive":True},
    {"id":"mivolo_exact", "question":"Wie verändert sich der Fehler der Altersschätzung, wenn MiVOLO nur den Körper",
     "direct":"MiVOLO body only MAE face body comparison ablation", "positive":True},
    {"id":"dino_teacher", "question":"Wie wird der Lehrer in DINO aktualisiert, und warum verwendet DINO einen Momentum-Lehrer?",
     "direct":"DINO momentum teacher exponential moving average", "positive":True},
    {"id":"dino_patches", "question":"Welchen Einfluss hat die Größe der Bild-Patches bei DINO auf die Qualität der Repräsentationen und den Rechenaufwand?",
     "direct":"DINO smaller image patches representation quality computational cost", "positive":True},
    {"id":"distillation", "question":"Warum werden bei Wissensdistillation Soft Targets mit erhöhter Temperatur verwendet?",
     "direct":"knowledge distillation soft targets temperature class similarities", "positive":True},
    {"id":"distillation_temperature", "question":"Was ist die Perfekte Knowledge destillation temperatur?",
     "direct":"knowledge distillation optimal temperature soft targets", "positive":True},
    {"id":"unrelated", "question":"Welche klinischen Studien belegen die Wirksamkeit eines Migräne-Medikaments gegenüber Placebo?",
     "direct":"migraine medication placebo clinical trial efficacy", "positive":False},
]


def document_language_queries(result):
    """Match the real window: one existing retrieval formulation per language."""
    queries = {}
    def add(language, query):
        if not isinstance(language,str) or not isinstance(query,str) or not 1 <= len(query.strip()) <= 1000:
            return
        language = language.replace("_","-").lower().split("-")[0]
        if len(language) in (2,3) and language.isascii() and language.isalpha() and language != "all":
            queries.setdefault(language,query.strip())
    if result.get("agentic_used") and isinstance(result.get("agent_steps"),list):
        for step in result["agent_steps"]:
            language = step.get("language","")
            if language == "all" and len(result.get("languages",{})) == 1:
                language = next(iter(result["languages"]))
            add(language,step.get("query"))
    else:
        for language,query in result.get("queries",{}).items():
            add(language,query)
    return queries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--library", type=int, default=1)
    parser.add_argument("--case", action="append", choices=[case["id"] for case in CASES])
    parser.add_argument("--attachment-key", action="append", help="Restrict test payloads to explicitly approved PDFs")
    parser.add_argument("--document-relevance", action="store_true", help="Also check the local document overview")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live: parser.error("Cloud-Testläufe benötigen den ausdrücklich gewählten Schalter --live")
    base = "http://127.0.0.1:8765"
    def get(path):
        with urlopen(base + path, timeout=15) as response: return json.load(response)
    def post(path, data):
        request = Request(base + path, json.dumps(data).encode(),
                          {"Content-Type":"application/json","X-Zitatlotse-Client":"1"})
        with urlopen(request, timeout=180) as response: return json.load(response)
    settings, health = get("/settings"), get("/health")
    report = {"created_at":datetime.now(timezone.utc).isoformat(), "version":health.get("version"),
              "provider":settings["provider"], "model":settings["model"], "agentic_enabled":settings.get("agentic_enabled"),
              "library_id":args.library, "scope":"approved PDF selection" if args.attachment_key else "entire library", "cases":[]}
    scope = {"attachment_keys":args.attachment_key} if args.attachment_key else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    allowed_keys = set(args.attachment_key or [])
    for case in CASES:
        if args.case and case["id"] not in args.case: continue
        print("TEST", case["id"], flush=True)
        start = time.monotonic()
        direct = post("/search", {"library_id":args.library,**scope,"query":case["direct"],"limit":20})
        row = {**case,"direct_hits":direct.get("total_results",len(direct["results"])), "mode":"chat"}
        job = post("/chat/start", {"library_id":args.library,**scope,"message":case["question"],"ui_lang":"de","mode":"chat"})
        last_sequence = 0
        while time.monotonic() - start < 420:
            status = post("/chat/status", {"library_id":args.library, **job})
            for event in status.get("activity", []):
                if event["sequence"] > last_sequence:
                    print("STEP", case["id"], event["type"], event.get("query", ""), event.get("count", ""), flush=True)
                    last_sequence = event["sequence"]
            if status["state"] in {"complete","failed","cancelled"}: break
            time.sleep(1)
        else:
            post("/chat/cancel", {"library_id":args.library, **job})
            status = {"state":"failed","error":"Test timeout"}
        result = status.get("result", {})
        selected = result.get("selected_results", [hit for hit in result.get("results",[]) if hit.get("recommended")])
        row.update(state=status["state"], ai_hits=result.get("total_results",len(result.get("results",[]))),
                   selected_hits=len(selected), agentic_used=result.get("agentic_used", False),
                   warning=result.get("warning", ""), error=status.get("error", ""), reply=result.get("reply", ""),
                   queries=result.get("queries", {}), steps=result.get("agent_steps", []), activity=status.get("activity", []),
                   sources=[{"title":hit["title"],"page":hit["page"],"key":hit["attachment_key"]} for hit in selected],
                   ui_result=result,
                   seconds=round(time.monotonic()-start,1))
        row["scope_ok"] = all(hit.get("library_id") == args.library and
                              (not allowed_keys or hit.get("attachment_key") in allowed_keys)
                              for hit in result.get("results", []) + selected)
        row["passed"] = (row["scope_ok"] and row["state"] == "complete" and not row["error"] and
                         (bool(selected) if case["positive"] else row["ai_hits"] == 0 and not selected))
        if args.document_relevance:
            overview = post("/document-relevance", {"library_id":args.library,**scope,"query":case["question"],
                                                   "language_queries":document_language_queries(result)})
            row["document_relevance"] = overview
            documents = overview["documents"]
            row["overview_ok"] = (len(documents) == overview["total_documents"] and
                sum(c["count"] for c in overview["categories"]) == len(documents) and
                all(d["library_id"] == args.library and (not allowed_keys or d["attachment_key"] in allowed_keys) and
                    (d["similarity"] is None or math.isfinite(d["similarity"]) and -1 <= d["similarity"] <= 1)
                    for d in documents) and (not allowed_keys or {d["attachment_key"] for d in documents} == allowed_keys))
            row["passed"] = row["passed"] and row["overview_ok"]
        report["cases"].append(row)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2), encoding="utf-8")
        print("RESULT", json.dumps({key:row[key] for key in ("id","direct_hits","ai_hits","selected_hits","state","passed","warning","error","seconds")},ensure_ascii=True),flush=True)
    print("REPORT", str(args.output), flush=True)
    return 0 if report["cases"] and all(row["passed"] for row in report["cases"]) else 1


if __name__ == "__main__": raise SystemExit(main())
