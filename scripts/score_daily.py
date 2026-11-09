"""One day of scoring on a rate-limited provider, resumable across machines.

The queue file lives in a private Hugging Face dataset, not in git (runs
stay private until release). Each run downloads it, queues any snapshot
not yet queued, works until the provider's daily cap would make it wait,
exports, and uploads the queue and the export again.

    uv run --project harness python scripts/score_daily.py --model gpt-oss-120b@groq

Needs a Hugging Face token with write access (and the provider's key) in
the environment or injected by a proxy.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError

ROOT = Path(__file__).resolve().parents[1]
WORK_REPO = os.environ.get("ROOTLINE_HF_WORK", "Flotrpy/rootline-work")


def run(*args: str) -> str:
    cmd = [sys.executable, "-m", "rootline_harness.run", *args]
    out = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    sys.stderr.write(out.stderr[-4000:])
    return out.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-wait", default="900", help="seconds; longer waits end the day")
    args = ap.parse_args()
    name = args.model.split("@")[-1]
    db = ROOT / "data" / f"queue-{name}.sqlite"
    runs = ROOT / "data" / "runs" / f"runs-{name}.parquet"
    token = os.environ.get("HF_TOKEN", "proxy-injected")
    # LiteLLM refuses to start without a key variable; a proxy replaces it.
    os.environ.setdefault("GROQ_API_KEY", "proxy-injected")
    api = HfApi(token=token)
    api.create_repo(WORK_REPO, repo_type="dataset", private=True, exist_ok=True)
    if not api.repo_info(WORK_REPO, repo_type="dataset").private:
        raise SystemExit(f"{WORK_REPO} is public; refusing to store runs there")

    if not db.exists():
        try:
            got = hf_hub_download(WORK_REPO, db.name, repo_type="dataset", token=token)
            db.write_bytes(Path(got).read_bytes())
            print(f"resumed {db.name} from {WORK_REPO}")
        except EntryNotFoundError:
            print(f"no {db.name} in {WORK_REPO} yet: starting a new queue")

    print(run("--db", str(db), "enqueue", "--models", args.model))
    print(run("--db", str(db), "work", "--max-wait", args.max_wait))
    print(run("--db", str(db), "export", "--out", str(runs)))
    status = run("--db", str(db), "status")
    print(status)

    for path in (db, runs):
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=path.name,
            repo_id=WORK_REPO,
            repo_type="dataset",
            commit_message=f"{args.model}: {status.splitlines()[0]}",
        )
    print(f"uploaded {db.name} and {runs.name} to {WORK_REPO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
