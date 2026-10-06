"""Bounded live operation events. Never store model reasoning or raw responses."""
import copy
import threading
import time
import uuid


class SearchCancelled(Exception):
    pass


EVENT_TYPES = {"started", "model_call", "tool_call", "search_started", "search_results",
               "tool_result", "cache_reused", "retry", "tool_rejected", "fallback",
               "review_started", "review_batch", "review_complete", "complete", "failed"}


class SearchJobs:
    def __init__(self, prefix="chat"):
        self.prefix = prefix
        self.jobs = {}
        self.lock = threading.RLock()

    def _event(self, job, event):
        if not isinstance(event, dict) or event.get("type") not in EVENT_TYPES:
            return
        clean = {"type": event["type"], "sequence": job["sequence"] + 1,
                 "elapsed": round(time.monotonic() - job["started"], 1)}
        for field in ("query", "language", "tool", "purpose"):
            if isinstance(event.get(field), str):
                clean[field] = event[field][:500 if field == "query" else 64]
        for field in ("round", "step", "count", "completed", "total"):
            if type(event.get(field)) is int and event[field] >= 0:
                clean[field] = event[field]
        job["sequence"] = clean["sequence"]
        job["activity"].append(clean)
        del job["activity"][:-256]

    def start(self, data, runner):
        library_id = int(data["library_id"])
        if not str(data.get("message", "")).strip():
            raise ValueError("Suchfrage fehlt")
        with self.lock:
            now = time.monotonic()
            self.jobs = {key: job for key, job in self.jobs.items()
                         if job["state"] == "running" or now - job["touched"] < 900}
            if sum(job["state"] == "running" for job in self.jobs.values()) >= 4:
                raise ValueError("Bitte laufende Suche abwarten")
            while len(self.jobs) >= 8:
                finished = [key for key, job in self.jobs.items() if job["state"] != "running"]
                del self.jobs[min(finished, key=lambda key: self.jobs[key]["touched"])]
            token = self.prefix + "-" + uuid.uuid4().hex
            job = {"library_id": library_id, "collection_id": data.get("collection_id", 0),
                   "state": "running", "phase": "searching", "completed": 0, "total": 0,
                   "started": now, "touched": now, "activity": [], "sequence": 0}
            self.jobs[token] = job
            self._event(job, {"type": "started"})
            threading.Thread(target=self._run, args=(token, runner), daemon=True).start()
            return {"job_id": token}

    def _run(self, token, runner):
        def progress(**changes):
            with self.lock:
                job = self.jobs[token]
                if job["state"] == "cancelled":
                    raise SearchCancelled("Suche wurde zurückgesetzt")
                self._event(job, changes.get("event"))
                for field in ("phase", "completed", "total"):
                    if field in changes:
                        job[field] = changes[field]
        try:
            result = runner(progress)
            with self.lock:
                job = self.jobs[token]
                if job["state"] != "cancelled":
                    self._event(job, {"type": "complete", "count": result.get("total_results", len(result.get("results", [])))})
                    result = {**result, "activity": copy.deepcopy(job["activity"])}
                    job.update(state="complete", result=result, touched=time.monotonic())
        except Exception as exc:
            with self.lock:
                job = self.jobs[token]
                if job["state"] != "cancelled":
                    self._event(job, {"type": "failed"})
                    job.update(state="failed", error=str(exc), touched=time.monotonic())

    def status(self, data, cancel=False):
        with self.lock:
            job = self.jobs.get(str(data.get("job_id", "")))
            if (not job or job["library_id"] != int(data["library_id"]) or
                    ("collection_id" in data and job["collection_id"] != data["collection_id"])):
                raise ValueError("Suche abgelaufen. Bitte erneut suchen.")
            job["touched"] = time.monotonic()
            if cancel and job["state"] == "running":
                job["state"] = "cancelled"
            return copy.deepcopy({key: value for key, value in job.items()
                                  if key not in {"library_id", "collection_id", "started", "touched", "sequence"}})
