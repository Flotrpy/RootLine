# Release runbook: from first snapshot to launch

Everything below the line "flotrpy only" is a step the build prompt reserves
for you: marking PR #1 ready, merging, tagging and publishing.

## Order of work

The steps run in this order because they share one demo stack: the hardware
campaign reroutes checkout → payment through Board A, so it must not overlap
the emulated runs.

| # | Step | Command | Needs |
|---|------|---------|-------|
| 1 | Gate 1: one dry-run incident | README "Running the pilot", steps 1–4 | demo on the laptop |
| 2 | Overnight campaign, 30 snapshots | `./bin/rootlinectl campaign --plan plans/pilot.yaml` | ~6.5 h, unattended |
| 3 | Gate 2 and model runs (Tier C on APIs, Tier A/B on Kaggle) | README "Running the models" | snapshots from step 2 |
| 4 | 15 live remediation trials | `python -m analysis plan-remediation`, then the printed commands | demo with the normal (Toxiproxy) wiring |
| 5 | **Boards: set up, then the hardware campaign** | `docs/HARDWARE.md` | steps 2 and 4 finished |
| 6 | Score the 12 hardware snapshots | `run enqueue` + `run work` + `run export` again | step 5 |
| 7 | Regenerate everything | `make reproduce && make paper` | all runs |
| 8 | Final gate | `make release-check` (no FAIL) | everything above |

### When to plug in the boards

- **Any time, even while the overnight campaign runs:** flash Board B's
  sketch, wire the buttons and LEDs, and install the relay on Board A
  (`docs/HARDWARE.md` sections 1 and 3). This touches only the boards.
- **Only after steps 2 and 4 are finished:** restart the demo with
  `compose.hardware.yml` and run `plans/hardware.yaml`. That reroutes
  checkout → payment through Board A, which would corrupt the emulated
  snapshots and the remediation trials if they were still running.
- In the charter's schedule that is Sunday 18:00 (setup) and 20:30–23:00
  (the 12 hardware snapshots, about 2.6 hours, with you at the keyboard).

If time runs short, cut in the charter's order: site polish, then Rust CLI
extras, then the optional panel display. Never cut Gate 1, Gate 2, the
healthy controls or the authorship checks.

## flotrpy only: release

1. **Resolve or accept the open decisions.** `make release-check` lists the
   `TODO(flotrpy)` markers; each one is either decided in code or noted as a
   limitation in the report.
2. **Read the report.** `paper/rootline-v0.1.pdf` and
   `paper/figures/results.json`. Every number comes from the runs.
3. **Publish the dataset (CC BY 4.0).**

   ```bash
   make dataset
   ```

   ```bash
   huggingface-cli upload flotrpy/rootline dist/rootline-v0.1-data --repo-type dataset
   ```

   Confirm the dataset id in `analysis/dataset.py` first.
4. **Turn on Zenodo's GitHub integration for the repository** before the
   GitHub release, so the release gets a DOI (`.zenodo.json` holds the
   metadata).
5. **Mark PR #1 ready, then merge with "Create a merge commit".** Never
   squash (it collapses the history) and never rebase-merge (it rewrites
   every commit).
6. **Tag and release.**

   ```bash
   git checkout main && git pull
   ```

   ```bash
   git tag -s v0.1.0 -m "Rootline v0.1.0 pilot"
   ```

   ```bash
   git push origin v0.1.0
   ```

   Create the GitHub release from the tag with `docs/RELEASE_NOTES_v0.1.0.md`.
7. **Deploy the site.** Run the `pages` workflow by hand (Actions → pages →
   Run workflow). It downloads the published dataset, builds the site with
   labels, and deploys it.
8. **Submit.** The report to arXiv once you have an endorsement, then JOSS.
9. **Launch, Monday 09:00 ET.** Blog post, Show HN, r/MachineLearning [R],
   r/sre or r/devops, LinkedIn, the Board B demo video.

After the merge, launch feedback goes into GitHub issues for a v0.2 pull
request (P2, P3, the private holdout, the DOI in `CITATION.cff`).
