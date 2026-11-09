# v0.1 checklist

v0.1 answers RQ1 and RQ2 only. Tick items as they are done.

## Setup

- [x] Laptop: WSL Ubuntu, Docker Desktop, Go, uv, rootlinectl built
- [x] Both boards set up; `rootlinectl hw check` all PASS
- [x] Demo images pulled; demo running with `compose.override.yml`
- [x] Gate 1: one test incident end to end
- [x] Scope narrowed to RQ1 and RQ2; limitations section in the README

## Data (overnight, unattended)

- [ ] Pilot campaign: 30 snapshots (5 rerun after the database fix)
- [ ] Hardware campaign: 12 snapshots on the boards
- [ ] Check `data/overnight.log`: every snapshot finished, nothing left pending

## Models and results

- [x] Choose the models: gpt-oss-120b (Cerebras), Qwen3 8B and Gemma 3 4B (Ollama)
- [ ] Cerebras account and API key, set as `CEREBRAS_API_KEY` on the laptop (never in the repo)
- [ ] Install Ollama on the laptop and `ollama pull qwen3:8b && ollama pull gemma3:4b` (after the campaign)
- [ ] Gate 2: the same snapshot scored twice gives the same answer
- [ ] Score all snapshots, default (P0) runs only: `run enqueue`, `run work`, `run export`
- [ ] `make reproduce`: results table and the RQ1 and RQ2 charts
- [ ] Publish the results table in the README, even if the result is negative
- [ ] `make paper`: read the report

## Release (flotrpy only)

- [ ] Decide or list as limitations every `TODO(flotrpy)` (`make release-check` lists them)
- [ ] `make release-check`: no FAIL
- [ ] Hugging Face account; confirm the dataset id in `analysis/dataset.py`
- [ ] `make dataset`, then upload to Hugging Face (CC BY 4.0)
- [ ] Turn on Zenodo's GitHub integration (gives the release a DOI)
- [ ] Merge the PR with "Create a merge commit"
- [ ] Tag `v0.1.0` and create the GitHub release from `docs/RELEASE_NOTES_v0.1.0.md`
- [ ] Run the `pages` workflow to deploy the results site

## Cleanup (later)

- [ ] Uninstall what is no longer needed: see `docs/INSTALLED_SOFTWARE.txt`

## v0.2 (held back)

- [ ] RQ3 name reliance (P1 runs), RQ4 cascade, RQ5 remediation trials, RQ6 baseline
- [ ] Second testbed on Kubernetes (Docker Desktop single-node cluster, demo's Helm chart; network faults via Chaos Mesh or in-cluster Toxiproxy). Only after v0.1, with the Compose demo stopped
