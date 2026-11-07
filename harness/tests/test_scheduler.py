import random

import pytest

from rootline_harness.scheduler import MODELS, Limits, Queue, load_limits
from rootline_harness.scheduler.queue import MAX_ATTEMPTS


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


LIMITS = {
    "groq": Limits(rpm=2, rpd=5, tpm=10_000, tpd=12_000),
    "local": Limits(rpm=None, rpd=None, tpm=None, tpd=None),
}


@pytest.fixture
def q(tmp_path):
    clock = Clock()
    queue = Queue(tmp_path / "q.sqlite", LIMITS, clock=clock, rng=random.Random(0))
    return queue, clock


def test_enqueue_is_idempotent(q) -> None:
    queue, _ = q
    assert queue.enqueue("a-r1", "logs", "p0", "m", "groq")
    assert not queue.enqueue("a-r1", "logs", "p0", "m", "groq")
    assert queue.counts() == {"pending": 1}


def test_per_minute_request_cap(q) -> None:
    queue, clock = q
    assert queue.wait_for("groq", 100) == 0
    queue.record_usage("groq", 100)
    clock.t += 10
    queue.record_usage("groq", 100)
    # Third request in the same minute must wait until the first ages out.
    assert queue.wait_for("groq", 100) == pytest.approx(50)
    clock.t += 50
    assert queue.wait_for("groq", 100) == 0


def test_daily_token_cap(q) -> None:
    queue, clock = q
    for _ in range(2):
        queue.record_usage("groq", 5_000)
        clock.t += 120
    # 10k used today; another 5k would break the 12k/day cap.
    wait = queue.wait_for("groq", 5_000)
    assert wait == pytest.approx(86_400 - 240)
    assert queue.wait_for("groq", 1_000) == 0
    with pytest.raises(ValueError):
        queue.wait_for("groq", 20_000)


def test_caps_survive_restart(tmp_path) -> None:
    clock = Clock()
    path = tmp_path / "q.sqlite"
    a = Queue(path, LIMITS, clock=clock)
    a.record_usage("groq", 100)
    a.record_usage("groq", 100)
    b = Queue(path, LIMITS, clock=clock)
    assert b.wait_for("groq", 100) > 0


def test_unlimited_provider(q) -> None:
    queue, _ = q
    for _ in range(1000):
        queue.record_usage("local", 6000)
    assert queue.wait_for("local", 6000) == 0


def test_claim_done_and_records(q) -> None:
    queue, _ = q
    queue.enqueue("a-r1", "logs", "p0", "m", "groq")
    job = queue.claim()
    assert job is not None and job.incident_id == "a-r1"
    assert queue.claim() is None
    queue.done(job, {"top1": True})
    assert queue.counts() == {"done": 1}
    assert queue.records() == [{"top1": True}]


def test_backoff_then_give_up(q) -> None:
    queue, clock = q
    queue.enqueue("a-r1", "logs", "p0", "m", "groq")
    for attempt in range(1, MAX_ATTEMPTS):
        job = queue.claim()
        assert job is not None
        queue.fail(job, "429", retryable=True)
        assert queue.counts() == {"pending": 1}
        wait = queue.next_eligible_in()
        assert wait is not None and 0 <= wait <= 2.0 * 2**attempt
        clock.t += 1_000
    job = queue.claim()
    assert job is not None
    queue.fail(job, "429", retryable=True)
    assert queue.counts() == {"failed": 1}
    assert queue.failures()[0][1] == "429"


def test_non_retryable_fails_at_once(q) -> None:
    queue, _ = q
    queue.enqueue("a-r1", "logs", "p0", "m", "groq")
    job = queue.claim()
    assert job is not None
    queue.fail(job, "400 bad request", retryable=False)
    assert queue.counts() == {"failed": 1}


def test_crashed_running_jobs_are_requeued(tmp_path) -> None:
    clock = Clock()
    path = tmp_path / "q.sqlite"
    a = Queue(path, LIMITS, clock=clock)
    a.enqueue("a-r1", "logs", "p0", "m", "groq")
    assert a.claim() is not None
    b = Queue(path, LIMITS, clock=clock)
    assert b.counts() == {"pending": 1}


def test_shipped_config_covers_every_model() -> None:
    limits = load_limits()
    for m in MODELS.values():
        assert m.provider in limits
