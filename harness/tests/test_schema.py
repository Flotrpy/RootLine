import json

import pytest

from rootline_harness.schema import ModelOutput, json_schema, parse_output

VALID = {
    "abstain": False,
    "layer": "application",
    "hypotheses": [
        {
            "rank": 1,
            "service": "payment",
            "category": "error",
            "confidence": 0.72,
            "evidence": ["T-0013", "L-0201"],
        },
        {
            "rank": 2,
            "service": "checkout",
            "category": "latency",
            "confidence": 0.1,
            "evidence": [],
        },
    ],
    "action": {"type": "disable_feature", "target": "payment"},
}


def test_valid_output_parses() -> None:
    out, err = parse_output(json.dumps(VALID))
    assert err is None
    assert out is not None
    top = out.top()
    assert top is not None and top.service == "payment"


def test_code_fence_is_tolerated() -> None:
    out, err = parse_output("```json\n" + json.dumps(VALID) + "\n```")
    assert err is None and out is not None


def mutate(**changes: object) -> str:
    d = json.loads(json.dumps(VALID))
    for path, value in changes.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[int(k)] if k.isdigit() else node[k]
        last = keys[-1]
        if value is _DELETE:
            del node[last]
        else:
            node[int(last) if last.isdigit() else last] = value
    return json.dumps(d)


_DELETE = object()


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("not json", "invalid JSON"),
        ("Here you go: " + json.dumps(VALID), "invalid JSON"),
        (mutate(layer="database"), "layer"),
        (mutate(abstain="false"), "abstain"),
        (mutate(hypotheses__0__confidence=1.5), "confidence"),
        (mutate(hypotheses__0__rank=0), "rank"),
        (mutate(hypotheses__1__rank=1), "unique"),
        (mutate(action__type="exec"), "action.type"),
        (mutate(action__target=None), "needs a target"),
        (mutate(extra_field=1), "extra_field"),
        (mutate(hypotheses__0__evidence=_DELETE), "evidence"),
    ],
)
def test_invalid_outputs_are_rejected(raw: str, fragment: str) -> None:
    out, err = parse_output(raw)
    assert out is None
    assert err is not None and fragment in err


def test_no_action_rejects_target() -> None:
    raw = mutate(action__type="no_action", action__target="payment")
    out, err = parse_output(raw)
    assert out is None and err is not None and "no_action" in err


def test_ranked_sorts_by_rank() -> None:
    d = json.loads(json.dumps(VALID))
    d["hypotheses"].reverse()
    out = ModelOutput.model_validate(d)
    assert [h.rank for h in out.ranked()] == [1, 2]


def test_json_schema_is_compact_json() -> None:
    s = json.loads(json_schema())
    assert set(s["required"]) == {"abstain", "layer", "hypotheses", "action"}
