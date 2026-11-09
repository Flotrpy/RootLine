import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from rootline_harness.packers import load_snapshot
from rootline_harness.prompt import build_prompt
from rootline_harness.run import Worker, export, gate2, main
from rootline_harness.runner import RUN_COLUMNS, Completion, ModelError, run_one
from rootline_harness.scheduler import MODELS, Limits, Queue
from rootline_harness.scorers import Label
from tests.synth import LABEL

MODEL = MODELS["gpt-oss-120b@groq"]

GOOD = json.dumps(
    {
        "abstain": False,
        "layer": "application",
        "hypotheses": [
            {
                "rank": 1,
                "service": "payment",
                "category": "error",
                "confidence": 0.8,
                "evidence": ["M-0002", "L-0001"],
            }
        ],
        "action": {"type": "disable_feature", "target": "payment"},
    }
)


class Scripted:
    """Returns replies in order and records every prompt it was sent."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, model, prompt: str) -> Completion:
        self.prompts.append(prompt)
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return Completion(text=r, prompt_tokens=100, completion_tokens=20, latency_ms=5)


@pytest.fixture
def prompt(snapshot):
    return build_prompt(snapshot, "combined")


def run(prompt, client) -> dict[str, object]:
    return run_one(
        run_id="r",
        prompt=prompt,
        label=Label.from_dict(LABEL),
        model=MODEL,
        client=client,
        condition="combined",
        perturbation="p0",
    )


def test_good_output_scores_and_matches_contract(prompt) -> None:
    rec = run(prompt, Scripted(GOOD))
    assert tuple(rec) == RUN_COLUMNS
    assert rec["parsed_ok"] and rec["top1"] and rec["layer_ok"]
    assert rec["prompt_tokens"] == 100 and rec["tier"] == "C"


def test_one_retry_with_error_appended(prompt) -> None:
    client = Scripted("not json", GOOD)
    rec = run(prompt, client)
    assert len(client.prompts) == 2
    assert client.prompts[1].startswith(client.prompts[0])
    assert "rejected: invalid JSON" in client.prompts[1]
    assert rec["parsed_ok"] and rec["top1"]
    assert rec["prompt_tokens"] == 200  # both attempts counted


def test_second_failure_scores_as_abstain(prompt) -> None:
    client = Scripted("nope", "still nope")
    rec = run(prompt, client)
    assert len(client.prompts) == 2
    assert not rec["parsed_ok"] and not rec["top1"]
    assert rec["raw_output"] == "still nope"


@pytest.fixture
def workspace(tmp_path, snapshot_dir):
    snaps, labels = tmp_path / "snapshots", tmp_path / "labels"
    shutil.copytree(snapshot_dir, snaps / "paymentFailure-r1")
    labels.mkdir()
    (labels / "paymentFailure-r1.json").write_text(json.dumps(LABEL))
    return tmp_path, snaps, labels


def test_worker_drains_queue_and_exports(workspace) -> None:
    root, snaps, labels = workspace
    q = Queue(root / "q.sqlite", {"groq": Limits(None, None, None, None)})
    for cond in ("metrics", "traces", "logs", "combined"):
        q.enqueue("paymentFailure-r1", cond, "p0", MODEL.id, "groq")
    w = Worker(q, Scripted(GOOD), snaps, labels, sleep=lambda s: None, log=lambda m: None)
    assert w.drain() == {"done": 4}
    out = root / "runs.parquet"
    assert export(q, out) == 4
    df = pl.read_parquet(out)
    assert tuple(df.columns) == RUN_COLUMNS
    assert df["top1"].all()


def test_worker_waits_for_rate_limit(workspace) -> None:
    root, snaps, labels = workspace
    now = [1_000_000.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    q = Queue(
        root / "q.sqlite",
        {"groq": Limits(rpm=1, rpd=None, tpm=None, tpd=None)},
        clock=lambda: now[0],
    )
    q.enqueue("paymentFailure-r1", "logs", "p0", MODEL.id, "groq")
    q.enqueue("paymentFailure-r1", "metrics", "p0", MODEL.id, "groq")
    w = Worker(q, Scripted(GOOD), snaps, labels, sleep=sleep, log=lambda m: None)
    assert w.drain() == {"done": 2}
    assert slept and sum(slept) >= 60 - 1e-6  # second request waited a minute


def test_worker_retries_rate_limit_errors(workspace) -> None:
    root, snaps, labels = workspace
    q = Queue(root / "q.sqlite", {"groq": Limits(None, None, None, None)})
    q.enqueue("paymentFailure-r1", "logs", "p0", MODEL.id, "groq")
    client = Scripted(ModelError("429", retryable=True), GOOD)
    w = Worker(q, client, snaps, labels, sleep=lambda s: None, log=lambda m: None)
    # next_eligible_at is in the real future; run until it drains.
    assert w.run_job_once()
    assert q.counts() == {"pending": 1}


def test_missing_label_fails_job_visibly(workspace) -> None:
    root, snaps, labels = workspace
    (labels / "paymentFailure-r1.json").unlink()
    q = Queue(root / "q.sqlite", {"groq": Limits(None, None, None, None)})
    q.enqueue("paymentFailure-r1", "logs", "p0", MODEL.id, "groq")
    w = Worker(q, Scripted(GOOD), snaps, labels, sleep=lambda s: None, log=lambda m: None)
    w.drain()
    assert q.counts() == {"failed": 1}
    assert "FileNotFoundError" in q.failures()[0][1]


def test_gate2_passes_for_deterministic_model(workspace) -> None:
    root, snaps, labels = workspace
    q = Queue(root / "q.sqlite", {"groq": Limits(None, None, None, None)})
    w = Worker(q, Scripted(GOOD), snaps, labels, sleep=lambda s: None, log=lambda m: None)
    same, runs = gate2(w, "paymentFailure-r1", "combined", "p0", MODEL.id)
    assert same and runs[0]["top1"] == runs[1]["top1"]


def test_gate2_fails_when_scores_differ(workspace) -> None:
    root, snaps, labels = workspace
    q = Queue(root / "q.sqlite", {"groq": Limits(None, None, None, None)})
    w = Worker(
        q,
        Scripted(GOOD, "garbage", "garbage"),
        snaps,
        labels,
        sleep=lambda s: None,
        log=lambda m: None,
    )
    same, _ = gate2(w, "paymentFailure-r1", "combined", "p0", MODEL.id)
    assert not same


def test_cli_enqueue_status_export(workspace, capsys) -> None:
    root, snaps, labels = workspace
    base = ["--db", str(root / "q.sqlite"), "--snapshots", str(snaps), "--labels", str(labels)]
    assert main([*base, "enqueue", "--models", MODEL.id]) == 0
    assert "queued 4 new jobs" in capsys.readouterr().out
    assert main([*base, "enqueue", "--models", MODEL.id]) == 0
    assert "queued 0 new jobs" in capsys.readouterr().out
    assert main([*base, "status"]) == 0
    assert "'pending': 4" in capsys.readouterr().out
    assert main([*base, "export", "--out", str(root / "r.parquet")]) == 0
    assert Path(root / "r.parquet").exists()


def test_prompt_cache_reuses_snapshot(workspace) -> None:
    root, snaps, labels = workspace
    q = Queue(root / "q.sqlite", {"groq": Limits(None, None, None, None)})
    w = Worker(q, Scripted(GOOD), snaps, labels)
    a = w.prompt("paymentFailure-r1", "logs", "p0")
    assert w.prompt("paymentFailure-r1", "logs", "p0") is a
    assert a.pack.incident_id == load_snapshot(snaps / "paymentFailure-r1").incident_id


def _raise(exc: Exception):
    def completion(**kwargs):
        raise exc

    return completion


@pytest.mark.parametrize(
    ("make_exc", "retryable"),
    [
        (lambda e: e.RateLimitError("slow down", "groq", "m"), True),
        (lambda e: e.Timeout("timed out", "m", "groq"), True),
        (lambda e: e.BadRequestError("bad", "m", "groq"), False),
        (lambda e: e.AuthenticationError("no key", "groq", "m"), False),
    ],
)
def test_litellm_errors_are_classified(monkeypatch, make_exc, retryable) -> None:
    import litellm
    from litellm import exceptions

    from rootline_harness.runner import LiteLLMClient

    monkeypatch.setattr(litellm, "completion", _raise(make_exc(exceptions)))
    client = LiteLLMClient({"groq": Limits(None, None, None, None)})
    with pytest.raises(ModelError) as info:
        client.complete(MODEL, "hi")
    assert info.value.retryable is retryable


def test_litellm_client_reads_usage(monkeypatch) -> None:
    import litellm

    from rootline_harness.runner import LiteLLMClient

    seen: dict[str, object] = {}

    class Msg:
        content = GOOD

    class Choice:
        message = Msg()

    class Usage:
        prompt_tokens = 321
        completion_tokens = 45

    class Resp:
        choices = (Choice(),)
        usage = Usage()

    def completion(**kwargs):
        seen.update(kwargs)
        return Resp()

    monkeypatch.setattr(litellm, "completion", completion)
    lim = {"ollama": Limits(None, None, None, None, api_base="http://localhost:11434")}
    local = MODELS["gpt-oss-120b@groq"].__class__("tiny", "ollama/tiny", "A", "ollama")
    c = LiteLLMClient(lim).complete(local, "prompt")
    assert (c.prompt_tokens, c.completion_tokens, c.text) == (321, 45, GOOD)
    assert seen["temperature"] == 0.0 and seen["seed"] == 0 and seen["num_retries"] == 0
    assert seen["api_base"] == "http://localhost:11434"
    assert "num_ctx" not in seen

    # Local models get the full context window, and Qwen3 skips thinking.
    seen.clear()
    LiteLLMClient(lim).complete(MODELS["qwen3-8b-q4@ollama"], "prompt")
    assert seen["model"] == "ollama_chat/qwen3:8b"
    assert seen["num_ctx"] == 12288 and seen["reasoning_effort"] == "none"
