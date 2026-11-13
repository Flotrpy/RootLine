"""SQLite job queue with rate limits that survive restarts.

Jobs are (incident, condition, perturbation, model). Every request and its
token usage is recorded, so per-minute and per-day caps are enforced from
durable history: stopping and restarting the worker never resets a cap.
Failed requests back off exponentially with full jitter.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from rootline_harness.scheduler.providers import Limits

MINUTE = 60.0
DAY = 86_400.0
MAX_ATTEMPTS = 6
BACKOFF_BASE = 2.0
BACKOFF_CAP = 300.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    condition TEXT NOT NULL,
    perturbation TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_eligible_at REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    record TEXT,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (status, next_eligible_at);
CREATE TABLE IF NOT EXISTS usage (
    provider TEXT NOT NULL,
    ts REAL NOT NULL,
    tokens INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_by_provider ON usage (provider, ts);
"""


def job_key(incident_id: str, condition: str, perturbation: str, model_id: str) -> str:
    return f"{incident_id}|{condition}|{perturbation}|{model_id}"


@dataclass(frozen=True)
class Job:
    key: str
    incident_id: str
    condition: str
    perturbation: str
    model_id: str
    provider: str
    attempts: int


class Queue:
    def __init__(
        self,
        path: str | Path,
        limits: dict[str, Limits],
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
    ) -> None:
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.limits = limits
        self.clock = clock
        self.rng = rng or random.Random()
        # A crash leaves jobs 'running'; put them back.
        self.db.execute("UPDATE jobs SET status='pending' WHERE status='running'")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def enqueue(
        self, incident_id: str, condition: str, perturbation: str, model_id: str, provider: str
    ) -> bool:
        """Add a job; returns False if it already exists (any status)."""
        key = job_key(incident_id, condition, perturbation, model_id)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO jobs (key, incident_id, condition, perturbation, model_id,"
            " provider, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (key, incident_id, condition, perturbation, model_id, provider, self.clock()),
        )
        return cur.rowcount == 1

    # --- rate limits -------------------------------------------------------

    def _usage(self, provider: str, since: float) -> tuple[int, int]:
        row = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens), 0) FROM usage WHERE provider=? AND ts>=?",
            (provider, since),
        ).fetchone()
        return int(row[0]), int(row[1])

    def wait_for(self, provider: str, est_tokens: int) -> float:
        """Seconds until one request of est_tokens fits every cap (0 = now)."""
        lim = self.limits.get(provider)
        if lim is None:
            raise KeyError(f"no rate limits configured for provider {provider!r}")
        now = self.clock()
        wait = 0.0
        for window, req_cap, tok_cap in ((MINUTE, lim.rpm, lim.tpm), (DAY, lim.rpd, lim.tpd)):
            if tok_cap is not None and est_tokens > tok_cap:
                raise ValueError(f"{provider}: one request ({est_tokens} tokens) exceeds cap")
            reqs, toks = self._usage(provider, now - window)
            if (req_cap is not None and reqs + 1 > req_cap) or (
                tok_cap is not None and toks + est_tokens > tok_cap
            ):
                wait = max(
                    wait, self._free_at(provider, window, req_cap, tok_cap, est_tokens) - now
                )
        return max(0.0, wait)

    def _free_at(
        self, provider: str, window: float, req_cap: int | None, tok_cap: int | None, need: int
    ) -> float:
        """Earliest time old usage rows age out enough for one more request."""
        now = self.clock()
        rows = self.db.execute(
            "SELECT ts, tokens FROM usage WHERE provider=? AND ts>=? ORDER BY ts",
            (provider, now - window),
        ).fetchall()
        reqs, toks = len(rows), sum(t for _, t in rows)
        free = now
        for ts, tokens in rows:
            fits = (req_cap is None or reqs + 1 <= req_cap) and (
                tok_cap is None or toks + need <= tok_cap
            )
            if fits:
                break
            # Once this row ages out of the window, one more request fits.
            reqs, toks = reqs - 1, toks - tokens
            free = ts + window
        return free

    def record_usage(self, provider: str, tokens: int) -> None:
        self.db.execute(
            "INSERT INTO usage (provider, ts, tokens) VALUES (?, ?, ?)",
            (provider, self.clock(), tokens),
        )

    # --- job lifecycle -----------------------------------------------------

    def claim(self) -> Job | None:
        """Take the next eligible pending job, or None."""
        with self._tx() as db:
            row = db.execute(
                "SELECT key, incident_id, condition, perturbation, model_id, provider, attempts"
                " FROM jobs WHERE status='pending' AND next_eligible_at<=?"
                " ORDER BY next_eligible_at, key LIMIT 1",
                (self.clock(),),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status='running', updated_at=? WHERE key=?",
                (self.clock(), row[0]),
            )
        return Job(*row)

    def defer(self, job: Job, seconds: float) -> None:
        """Put a job back without counting an attempt (waiting for a cap)."""
        self.db.execute(
            "UPDATE jobs SET status='pending', next_eligible_at=?, updated_at=? WHERE key=?",
            (self.clock() + seconds, self.clock(), job.key),
        )

    def done(self, job: Job, record: dict[str, object]) -> None:
        self.db.execute(
            "UPDATE jobs SET status='done', record=?, last_error=NULL, updated_at=? WHERE key=?",
            (json.dumps(record, sort_keys=True), self.clock(), job.key),
        )

    def fail(self, job: Job, error: str, retryable: bool) -> None:
        """Record a failure: back off with full jitter, or give up."""
        attempts = job.attempts + 1
        if not retryable or attempts >= MAX_ATTEMPTS:
            self.db.execute(
                "UPDATE jobs SET status='failed', attempts=?, last_error=?, updated_at=?"
                " WHERE key=?",
                (attempts, error, self.clock(), job.key),
            )
            return
        delay = self.rng.uniform(0, min(BACKOFF_CAP, BACKOFF_BASE * 2**attempts))
        self.db.execute(
            "UPDATE jobs SET status='pending', attempts=?, last_error=?, next_eligible_at=?,"
            " updated_at=? WHERE key=?",
            (attempts, error, self.clock() + delay, self.clock(), job.key),
        )

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
        return {s: n for s, n in rows}

    def next_eligible_in(self) -> float | None:
        row = self.db.execute(
            "SELECT MIN(next_eligible_at) FROM jobs WHERE status='pending'"
        ).fetchone()
        return None if row[0] is None else max(0.0, row[0] - self.clock())

    def records(self) -> list[dict[str, object]]:
        rows = self.db.execute(
            "SELECT record FROM jobs WHERE status='done' ORDER BY key"
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def failures(self) -> list[tuple[str, str]]:
        return self.db.execute(
            "SELECT key, last_error FROM jobs WHERE status='failed' ORDER BY key"
        ).fetchall()
