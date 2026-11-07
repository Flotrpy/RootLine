import json
import shutil

import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai.model import ModelOutput, get_model

from rootline_harness.tasks.rootline import rootline
from tests.synth import LABEL
from tests.test_runner import GOOD


@pytest.fixture
def data(tmp_path, snapshot_dir, monkeypatch):
    snaps, labels = tmp_path / "snapshots", tmp_path / "labels"
    shutil.copytree(snapshot_dir, snaps / "paymentFailure-r1")
    labels.mkdir()
    (labels / "paymentFailure-r1.json").write_text(json.dumps(LABEL))
    monkeypatch.setenv("ROOTLINE_SNAPSHOTS", str(snaps))
    monkeypatch.setenv("ROOTLINE_LABELS", str(labels))
    return tmp_path


def _eval(tmp_path, *outputs: str):
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(model="mockllm/model", content=o) for o in outputs
        ],
    )
    [log] = inspect_eval(
        rootline(condition="combined"),
        model=model,
        log_dir=str(tmp_path / "logs"),
        display="none",
    )
    assert log.status == "success", log.error
    assert log.samples is not None
    return log.samples[0]


def test_task_scores_like_the_scheduler(data) -> None:
    sample = _eval(data, GOOD)
    assert sample.scores is not None
    value = sample.scores["rootline_scorer"].value
    assert isinstance(value, dict)
    assert value["top1"] and value["layer_ok"] and value["parsed_ok"]
    assert sample.metadata["prompt_tokens"] <= 6000


def test_task_retries_once(data) -> None:
    sample = _eval(data, "not json", GOOD)
    assert sample.scores is not None
    value = sample.scores["rootline_scorer"].value
    assert isinstance(value, dict) and value["parsed_ok"] and value["top1"]
    assert "rejected" in str(sample.messages[-2].content)


def test_task_rejects_bad_condition(data) -> None:
    with pytest.raises(ValueError):
        rootline(condition="everything")
