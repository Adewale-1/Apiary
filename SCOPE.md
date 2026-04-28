# Research Scope

Read this file before proposing or executing any experiment.
It defines what agents are allowed to change and what is locked.

  <!-- SETUP: Replace the sections below with your project's specifics.
  The orchestration layer (apiary/) is never edited here. -->


## Editable files

The following files may be freely modified by code-editing agents:

- `<your-runner>.py` — the experiment runner. All model architecture, feature
  engineering, hyperparameters, and training logic live here.

## Frozen files — do not modify

- `SCOPE.md` — this file
- `program.md` — agent behavior contract
- `BEGIN_EXPERIMENT_LOOP.md` — loop entry instructions
- `apiary.toml` — orchestration configuration
- `apiary/` — the entire orchestration package
<!-- Add the files or directories that should not be editted -->

## Objective

<!-- One sentence describing the goal and the metric. -->

Minimize **`<metric>`** on the **`<benchmark>`** task.

## Constraints

- Do not install new packages. Use only what is declared in `pyproject.toml`.
- Do not change the evaluation logic inside the runner — the metric output must
  remain comparable across all experiments so the leaderboard is meaningful.
- **Simplicity criterion**: a small metric improvement that adds significant
  complexity is not worth keeping. Prefer clarity.
- A `discard` is not a failure — it means the idea was tried, measured, and
  cleanly reverted. Record it and move on.
