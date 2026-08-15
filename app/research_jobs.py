from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Callable


class ResearchJobs:
    """Small in-process queue for read-only, long-running research views.

    Jobs are intentionally not strategy evidence and are lost on a server restart;
    completed experiments remain in the database through strategy governance.
    """
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")
        self._lock = Lock()
        self._sequence = 0
        self._jobs: dict[str, dict] = {}

    @staticmethod
    def _public_job(job: dict) -> dict:
        return {key: value for key, value in job.items() if not key.startswith("_")}

    def submit(
        self,
        kind: str,
        work: Callable[[], dict],
        *,
        cache_key: str | None = None,
    ) -> dict:
        with self._lock:
            if cache_key:
                for existing in reversed(list(self._jobs.values())):
                    if (
                        existing.get("_cache_key") == cache_key
                        and existing.get("status") in {"running", "completed"}
                    ):
                        return self._public_job(existing)
            self._sequence += 1
            job_id = f"{kind}-{self._sequence}"
            self._jobs[job_id] = {"id": job_id, "kind": kind, "status": "running",
                                  "created_at": datetime.now().isoformat(timespec="seconds"),
                                  "_cache_key": cache_key}

        def run() -> None:
            try:
                result = work()
                with self._lock:
                    self._jobs[job_id].update({"status": "completed", "result": result,
                                               "completed_at": datetime.now().isoformat(timespec="seconds")})
            except Exception as exc:  # The API exposes a concise failure, not a traceback.
                with self._lock:
                    self._jobs[job_id].update({"status": "failed", "error": str(exc),
                                               "completed_at": datetime.now().isoformat(timespec="seconds")})

        self._executor.submit(run)
        return self.get(job_id) or {"id": job_id, "status": "running"}

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return self._public_job(job)


research_jobs = ResearchJobs()
