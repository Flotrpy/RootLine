# v0.1 checklist

v0.1 answers RQ1 and RQ2 only. Tick items as they are done.

## Setup

- [x] PC (AffanPC): WSL Ubuntu, Docker Desktop, Go, uv, rootlinectl built
- [x] Both boards set up; `rootlinectl hw check` all PASS
- [x] Demo images pulled; demo running with `compose.override.yml`
- [x] Gate 1: one test incident end to end
- [x] Scope narrowed to RQ1 and RQ2; limitations section in the README

## Data (overnight, unattended)

- [x] Pilot campaign: 30 snapshots (5 rerun after the database fix, 2 more for unhealthy baselines)
- [x] Hardware campaign: 12 snapshots on the boards
- [x] Check `data/overnight.log`: every snapshot finished, nothing left pending
- [x] Fault-visibility check run on all 42 (`python -m analysis fault-visibility`)

## Models and results

- [x] Choose the models: gpt-oss-120b (Groq, no card), Qwen3 8B and Gemma 3 4B (Ollama)
- [x] Groq account and API key, saved on the cloud environment (never in the repo)
- [x] Small models on Kaggle's free GPU: 336 runs (`scripts/kaggle_score.ipynb`)
- [x] Gate 2: the same snapshot scored twice gives the same answer (gpt-oss-120b, paymentFailure-r1)
- [x] Groq runs: 168 runs, finished Nov 15 (queue in `Flotrpy/rootline-work`)
- [x] Merge the Groq and Kaggle exports: 504 runs
- [x] `make reproduce`: results table and the RQ1 and RQ2 charts (also checked from a fresh download)
- [x] Publish the results table in the README, even if the result is negative
- [x] `make paper`: report built and read

## Release (flotrpy only)

- [x] Decide or list as limitations every `TODO(flotrpy)` (only the release-day DOI is left)
- [x] `make release-check`: no FAIL
- [x] Hugging Face account (Flotrpy); dataset id `Flotrpy/rootline` set in `analysis/dataset.py`
- [x] Private upload to Hugging Face: all 42 snapshots and labels; data out of git
- [x] Upload again with all 42 snapshots and 504 runs (private)
- [x] Make the Hugging Face dataset public at release (CC BY 4.0)
- [x] Zenodo: DOI 10.5281/zenodo.24270040 (all versions: 10.5281/zenodo.24270039)
- [x] Release notes and CITATION.cff updated for the v0.1 scope
- [x] Report: prior work with checked references, limitations, fault-visibility table
- [x] Merge the PR with "Create a merge commit"
- [x] Tag `v0.1.0` and create the GitHub release from `docs/RELEASE_NOTES_v0.1.0.md`
- [x] Run the `pages` workflow to deploy the results site (flotrpy.github.io/RootLine)

## After the release

- [x] DOI in `CITATION.cff` and the README
- [ ] Attach `rootline-v0.1.pdf` to the v0.1.0 GitHub release
- [ ] JOSS `paper.md`
- [ ] Expanded report

## Cleanup (later)

- [ ] Uninstall what is no longer needed: see `docs/INSTALLED_SOFTWARE.txt`

## v0.2 (held back)

- [ ] RQ3 name reliance (P1 runs), RQ4 cascade, RQ5 remediation trials, RQ6 baseline
- [ ] Second testbed on Kubernetes (Docker Desktop single-node cluster, demo's Helm chart; network faults via Chaos Mesh or in-cluster Toxiproxy). Only after v0.1, with the Compose demo stopped
