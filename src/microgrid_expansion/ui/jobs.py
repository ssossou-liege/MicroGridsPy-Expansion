"""Background work, and a way to watch it.

A certification takes twenty seconds to two minutes and an expansion plan five to nine, which
is far too long to hold an HTTP request open and long enough that an interface showing nothing
would look broken. Work therefore runs in a thread, reports progress as it goes, and the page
polls for it.

Progress is honest rather than decorative: each stage is announced when it starts, and the
share reported is the share of stages done, not a bar invented to fill the wait.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class Job:
    """One unit of background work and everything the page needs to render it."""

    id: str
    kind: str
    label: str
    status: str = "en cours"          # en cours | terminé | échoué | annulé
    stage: str = "démarrage"
    done: int = 0
    total: int = 1
    result: Any = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "status": self.status, "stage": self.stage,
                "done": self.done, "total": self.total,
                "fraction": round(self.fraction, 4),
                "result": self.result, "error": self.error,
                "started_at": self.started_at, "finished_at": self.finished_at}


class JobRegistry:
    """Every job this session has started, running or finished."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, label: str, work: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, label=label)
        with self._lock:
            self._jobs[job.id] = job

        def run() -> None:
            try:
                job.result = work(job)
                job.status = "annulé" if job._cancel.is_set() else "terminé"
                job.stage = "fini"
                job.done = job.total
            except Exception as exc:                       # noqa: BLE001 - reported to the page
                job.status = "échoué"
                job.error = f"{type(exc).__name__}: {exc}"
                job.stage = "interrompu"
                traceback.print_exc()
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat()

        threading.Thread(target=run, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Ask a job to stop. It stops at its next stage boundary, not mid-solve."""
        job = self._jobs.get(job_id)
        if job is None or job.status != "en cours":
            return False
        job._cancel.set()
        job.stage = "arrêt demandé"
        return True

    def recent(self, limit: int = 20) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]
